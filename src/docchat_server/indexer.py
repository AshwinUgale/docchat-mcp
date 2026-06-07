"""Doc indexer - fetch + chunk + embed + store for one (library, version).

Ported from docchat/sidecar/src/docchat_sidecar/indexer.py with two changes:

1. Uses ``QdrantClient`` in embedded mode (local path, no Docker) instead
   of ``AsyncQdrantClient`` against a running server. The embedded mode
   writes to ``~/.docchat-server/qdrant/`` and is fine for the
   single-user / hundreds-of-thousands-of-vectors scale this MCP server
   serves. Users can override via the ``QDRANT_PATH`` env var.
2. Drops the streaming-progress protocol (IndexProgress / IndexComplete
   frames). The MCP server doesn't need WebSocket-style progress events;
   the CLI prints a simple progress line per page fetched.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from docchat_server.library_config import collection_name_for, urls_for

__all__ = ["DocIndexer", "default_qdrant_path", "open_qdrant"]

logger = logging.getLogger(__name__)

# Mirrors docchat: text-embedding-3-small at 1536 dims, ~500-token chunks.
_DEFAULT_EMBED_MODEL = "text-embedding-3-small"
_DEFAULT_DIMENSIONS = 1536
_CHUNK_TARGET_CHARS = 2000
_MDX_NOISE_RE = re.compile(r"^(import |export )", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_H2_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")


def default_qdrant_path() -> Path:
    """Embedded-Qdrant storage directory. ``$QDRANT_PATH`` overrides."""
    import os

    override = os.environ.get("QDRANT_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".docchat-server" / "qdrant"


def open_qdrant(path: Path | None = None) -> QdrantClient:
    """Open the embedded Qdrant store, creating the parent dir if needed."""
    p = path or default_qdrant_path()
    p.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(p))


@dataclass(frozen=True, kw_only=True)
class _Chunk:
    source_url: str
    chunk_index: int
    text: str
    api_name: str
    section_heading: str | None


class DocIndexer:
    """Fetch + chunk + embed + write docs for one (library, version).

    Synchronous (since embedded Qdrant is sync). Progress is reported via
    a callable so the CLI can print to stderr; pass ``progress=None`` for
    silent operation.
    """

    def __init__(
        self,
        *,
        qdrant: QdrantClient,
        openai: OpenAI,
        embed_model: str = _DEFAULT_EMBED_MODEL,
        embed_dimensions: int = _DEFAULT_DIMENSIONS,
        http: httpx.Client | None = None,
    ) -> None:
        self._qdrant = qdrant
        self._openai = openai
        self._embed_model = embed_model
        self._embed_dimensions = embed_dimensions
        self._http = http

    def index(
        self,
        library: str,
        version: str,
        *,
        progress: "Callable[[str], None] | None" = None,
    ) -> int:
        """Index one (library, version). Returns count of chunks upserted.

        Raises:
            ValueError: library not in LIBRARY_CONFIG.
            RuntimeError: fetched 0 chunks (network or source-URL drift).
        """
        urls = urls_for(library, version)
        if not urls:
            raise ValueError(
                f"no indexer wired for {library!r}; supported: react, fastapi, vue. "
                "Add a LibraryConfig entry in library_config.py to extend."
            )

        collection = collection_name_for(library, version)
        self._reset_collection(collection)

        owns_http = self._http is None
        http = self._http or httpx.Client(timeout=30.0, follow_redirects=True)

        chunks: list[_Chunk] = []
        try:
            for page_index, url in enumerate(urls):
                if progress:
                    progress(f"fetching {page_index + 1}/{len(urls)}: {url.rsplit('/', 1)[-1]}")
                try:
                    response = http.get(url)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning("skipping %s: %s", url, exc)
                    continue
                text = _clean_mdx(response.text)
                api_name = _api_name_from_url(url)
                for idx, (chunk_text, section_heading) in enumerate(_split_into_chunks(text)):
                    chunks.append(
                        _Chunk(
                            source_url=url,
                            chunk_index=idx,
                            text=chunk_text,
                            api_name=api_name,
                            section_heading=section_heading,
                        )
                    )

            total = len(chunks)
            if total == 0:
                raise RuntimeError(
                    f"fetched 0 chunks for {library}@{version}; check network or "
                    "source URLs in library_config.py"
                )

            BATCH = 16
            for batch_start in range(0, total, BATCH):
                batch = chunks[batch_start : batch_start + BATCH]
                vectors = self._embed([c.text for c in batch])
                points = [
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={
                            "library": library,
                            "version": version,
                            "source_url": c.source_url,
                            "chunk_index": c.chunk_index,
                            "text": c.text,
                            "api_name": c.api_name,
                            "section_heading": c.section_heading,
                        },
                    )
                    for c, vector in zip(batch, vectors, strict=True)
                ]
                self._qdrant.upsert(collection_name=collection, points=points)
                if progress:
                    done = min(batch_start + BATCH, total)
                    progress(f"embedded + upserted {done}/{total}")

            return total
        finally:
            if owns_http:
                http.close()

    def _reset_collection(self, collection: str) -> None:
        """Drop + recreate the collection so re-indexing is idempotent."""
        if self._qdrant.collection_exists(collection_name=collection):
            self._qdrant.delete_collection(collection_name=collection)
        self._qdrant.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=self._embed_dimensions, distance=Distance.COSINE),
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._openai.embeddings.create(model=self._embed_model, input=texts)
        return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# Helpers (module-private; tested via the public DocIndexer)
# ---------------------------------------------------------------------------


def _api_name_from_url(url: str) -> str:
    """Derive a stable API name from a doc-source URL.

    Examples:
        ".../reference/react/useState.md"        -> "useState"
        ".../docs/tutorial/dependencies/index.md" -> "dependencies"
    """
    tail = url.rsplit("/", 1)[-1]
    stem = tail.removesuffix(".md").removesuffix(".mdx")
    if stem == "index":
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2]
    return stem


def _clean_mdx(raw: str) -> str:
    """Strip MDX frontmatter + import/export lines so we're left with prose."""
    no_frontmatter = _FRONTMATTER_RE.sub("", raw, count=1)
    no_imports = _MDX_NOISE_RE.sub("", no_frontmatter)
    return no_imports.strip()


def _split_into_chunks(text: str) -> Iterable[tuple[str, str | None]]:
    """Paragraph-aware splitter targeting ~500-token chunks, with H2 heading capture."""
    if not text.strip():
        return
    buffer: list[str] = []
    buffer_len = 0
    current_heading: str | None = None
    chunk_start_heading: str | None = None
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        first_line = paragraph.splitlines()[0]
        match = _H2_HEADING_RE.match(first_line)
        if match:
            current_heading = match.group(1).strip()
        para_len = len(paragraph)
        if buffer and buffer_len + para_len > _CHUNK_TARGET_CHARS:
            yield "\n\n".join(buffer), chunk_start_heading
            buffer = [paragraph]
            buffer_len = para_len
            chunk_start_heading = current_heading
        else:
            if not buffer:
                chunk_start_heading = current_heading
            buffer.append(paragraph)
            buffer_len += para_len + 2
    if buffer:
        yield "\n\n".join(buffer), chunk_start_heading


# Re-export so callers can type-hint without an extra import.
from collections.abc import Callable as _Callable  # noqa: E402
Callable = _Callable  # type: ignore[assignment]


def _eprint(*args: object) -> None:
    """stderr print helper - the CLI passes this as progress to keep stdout clean."""
    print(*args, file=sys.stderr, flush=True)
