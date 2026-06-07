"""Doc retrieval - the body of the ``search_docs`` MCP tool.

Ported from docchat/sidecar/src/docchat_sidecar/tools.py SearchDocsTool.
Two differences from the upstream:

1. Synchronous (embedded Qdrant is sync). The MCP server runs the call
   in a thread pool when invoked from an async tool handler.
2. Returns a formatted text string + citation list directly, no
   intermediate ``ToolResult`` dataclass - the MCP server flattens this
   into a single string the client model consumes.

Per-library cosine score floors carry over from docchat's eval-tuned
defaults (ADR-008 / ADR-011 / ADR-012): React 0.15 (default),
FastAPI 0.10, Vue 0.05. Empirical, not principled - reflects how dense
each library's doc corpus is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from openai import OpenAI
from qdrant_client import QdrantClient

from docchat_server.library_config import collection_name_for

__all__ = ["Citation", "SearchResult", "search_docs"]

logger = logging.getLogger(__name__)

_DEFAULT_FLOOR = 0.15
_FLOORS_BY_LIBRARY: dict[str, float] = {
    "fastapi": 0.10,
    "vue": 0.05,
}


@dataclass(frozen=True, kw_only=True)
class Citation:
    """Citation surfaced alongside a retrieval result."""

    library: str
    version: str
    source: str
    source_url: str | None = None

    def render(self) -> str:
        return f"[{self.library}@{self.version}:{self.source}]"


@dataclass(frozen=True, kw_only=True)
class SearchResult:
    """Top-K retrieval result for a single search_docs call."""

    text: str
    citations: tuple[Citation, ...]
    top_scores: tuple[float, ...]


def _floor_for(library: str, override: float | None) -> float:
    if override is not None:
        return override
    return _FLOORS_BY_LIBRARY.get(library.lower(), _DEFAULT_FLOOR)


def search_docs(
    *,
    qdrant: QdrantClient,
    openai: OpenAI,
    library: str,
    version: str,
    query: str,
    api_name: str | None = None,
    top_k: int = 5,
    score_floor: float | None = None,
    embed_model: str = "text-embedding-3-small",
) -> SearchResult:
    """Retrieve top-k chunks from the (library, version) collection.

    Drops hits below the per-library cosine floor. Returns a canonical
    "No relevant chunks found" string when nothing clears the floor - the
    calling LLM should treat that as a refusal signal rather than guess.

    Args:
        api_name: optional post-filter on chunk payload.api_name
            (case-insensitive startswith). Use when the user's query
            names a specific API to constrain to chunks for that API.
    """
    collection = collection_name_for(library, version)
    if not qdrant.collection_exists(collection_name=collection):
        return SearchResult(
            text=(
                f"No indexed docs for {library}@{version}. "
                f"Run `docchat-server index {library} {version}` to populate."
            ),
            citations=(),
            top_scores=(),
        )

    response = openai.embeddings.create(model=embed_model, input=[query])
    query_vector = response.data[0].embedding

    query_response = qdrant.query_points(
        collection_name=collection,
        query=query_vector,
        limit=top_k,
    )
    raw_hits = query_response.points

    top_scores = tuple(round(getattr(h, "score", 0.0), 3) for h in raw_hits[:5])
    floor = _floor_for(library, score_floor)
    if raw_hits:
        logger.info(
            "search_docs %s@%s floor=%.2f top-scores=%r query=%r",
            library, version, floor, list(top_scores), query,
        )

    hits = [h for h in raw_hits if getattr(h, "score", 0.0) >= floor]
    if api_name:
        api_lower = api_name.lower()
        hits = [
            h
            for h in hits
            if (h.payload or {}).get("api_name", "").lower().startswith(api_lower)
        ]

    if not hits:
        return SearchResult(
            text=f"No relevant chunks found for {query!r}.",
            citations=(),
            top_scores=top_scores,
        )

    text_parts: list[str] = []
    citations: list[Citation] = []
    seen_sources: set[str] = set()
    for hit in hits:
        payload = hit.payload or {}
        chunk_text = payload.get("text", "")
        source_url = payload.get("source_url", "")
        source_label = source_url.rsplit("/", 1)[-1] if source_url else "doc"
        payload_lib = payload.get("library", library)
        payload_ver = payload.get("version", version)
        hit_api_name = payload.get("api_name")
        section_heading = payload.get("section_heading")
        header = f"## {payload_lib}@{payload_ver}"
        if hit_api_name:
            header += f" - {hit_api_name}"
        location_bits: list[str] = [source_label] if source_label else []
        if section_heading:
            location_bits.append(section_heading)
        if location_bits:
            header += f"  ({' / '.join(location_bits)})"
        text_parts.append(f"{header}\n\n{chunk_text}")
        if source_label not in seen_sources:
            citations.append(
                Citation(
                    library=payload_lib,
                    version=payload_ver,
                    source=source_label,
                    source_url=source_url or None,
                )
            )
            seen_sources.add(source_label)

    return SearchResult(
        text="\n\n---\n\n".join(text_parts),
        citations=tuple(citations),
        top_scores=top_scores,
    )
