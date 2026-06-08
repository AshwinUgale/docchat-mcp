"""FastMCP server - exposes search_docs + list_indexed as MCP tools.

Transport: stdio (the default for local MCP servers Claude Code + Cursor
spawn). All logging goes to stderr - stdout is reserved for the JSON-RPC
stream and any stray prints will corrupt it.

Tools registered:
- ``search_docs(library, version, query, api_name?, top_k?)`` - the
  version-pinned doc retrieval that's the whole point of this server.
- ``list_indexed()`` - what (library, version) collections are populated
  in the local embedded Qdrant. Use before search_docs if you're unsure
  what's available.

Indexing is deliberately CLI-only (``docchat-server index <lib> <ver>``);
exposing it as an MCP tool would let any connected LLM trigger arbitrary
embedding cost / network calls, which is the wrong default.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP
from openai import OpenAI

from docchat_server import __version__
from docchat_server.indexer import open_qdrant
from docchat_server.library_config import LIBRARY_CONFIG
from docchat_server.retrieval import search_docs as _search_docs

# All logs to stderr so stdout stays clean for MCP JSON-RPC.
logging.basicConfig(
    level=logging.INFO,
    format="%(name)s | %(levelname)s | %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("docchat-server")

# .env in the cwd is a convenience for local development; production
# users should rely on environment variables set by the MCP host.
load_dotenv()


def _require_openai_key() -> None:
    """Fail fast on startup if the embedding key is missing - otherwise
    the first search_docs call would return an opaque error to the LLM."""
    if not os.environ.get("OPENAI_API_KEY"):
        logger.error(
            "OPENAI_API_KEY is not set. docchat-server uses OpenAI's embeddings "
            "API for retrieval. Set the env var in your MCP host config."
        )
        sys.exit(2)


_require_openai_key()

mcp: FastMCP = FastMCP(name="docchat", version=__version__)

# Shared resources opened once per server lifetime. Embedded Qdrant is
# single-process; OpenAI client is connection-pooled.
# v0.0.2: embedded-Qdrant holds a file lock on ~/.docchat-server/qdrant/.
# If another docchat-server (or `docchat-server list/index`) is already
# running, opening fails. Catch + exit with an actionable message instead
# of a 30-line Python traceback the user has to parse.
try:
    _QDRANT = open_qdrant()
except RuntimeError as _exc:
    logger.error(
        "Qdrant storage at ~/.docchat-server/qdrant is locked by another "
        "process. Either (1) another docchat-server is already running "
        "(quit the other MCP client or kill the process), or (2) a previous "
        "process crashed leaving a stale lock (delete any .lock files in "
        "that directory). Underlying error: %s",
        _exc,
    )
    sys.exit(2)
_OPENAI = OpenAI()


@mcp.tool()
async def search_docs(
    library: str,
    version: str,
    query: str,
    api_name: str | None = None,
    top_k: int = 5,
) -> str:
    """Search the version-pinned documentation for a specific library.

    Returns top-K chunks from the indexed docs of the EXACT pinned version
    (e.g. react@18.2.0, not 19.1.0). Use BEFORE answering any library API
    question to avoid version-mismatched APIs.

    If the result starts with "No relevant chunks found" or "No indexed
    docs", do not hallucinate - tell the user the docs aren't available
    at that pinned version.

    Args:
        library: Library name (e.g. "react", "fastapi", "vue"). Lowercase.
        version: Pinned version string (e.g. "18.2.0", "0.100.0").
        query: Natural-language question about the library.
        api_name: Optional - constrain to chunks tagged with this API name
            (case-insensitive startswith). Use when the query names a
            specific API like "useState" or "Depends".
        top_k: Max chunks to return. Default 5.
    """
    # Run sync retrieval in a thread so we don't block the asyncio loop.
    result = await asyncio.to_thread(
        _search_docs,
        qdrant=_QDRANT,
        openai=_OPENAI,
        library=library,
        version=version,
        query=query,
        api_name=api_name,
        top_k=top_k,
    )
    citations_line = (
        "\n\nCitations: " + ", ".join(c.render() for c in result.citations)
        if result.citations
        else ""
    )
    return result.text + citations_line


@mcp.tool()
async def list_indexed() -> dict[str, object]:
    """List all (library, version) collections currently indexed locally.

    Returns a dict with ``collections`` (list of {name, library, version,
    points_count}) and ``supported_libraries`` (which libraries this
    server's indexer knows how to populate).
    """

    def _query() -> dict[str, object]:
        collections = _QDRANT.get_collections().collections
        rows: list[dict[str, object]] = []
        for c in collections:
            try:
                count = _QDRANT.count(collection_name=c.name).count
            except Exception:
                count = -1
            rows.append({"name": c.name, "points_count": count})
        return {
            "collections": rows,
            "supported_libraries": sorted(LIBRARY_CONFIG.keys()),
            "qdrant_path": str(_QDRANT._client.location if hasattr(_QDRANT, "_client") else ""),
        }

    return await asyncio.to_thread(_query)


def main() -> None:
    """Entrypoint when invoked as ``docchat-server serve`` (or directly)."""
    logger.info("docchat-server %s starting on stdio", __version__)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
