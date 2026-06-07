"""docchat-server - version-pinned documentation retrieval as an MCP server.

Stripped-down sibling of docchat (https://github.com/AshwinUgale/docchat).
Exposes ``search_docs`` and ``list_indexed`` MCP tools that Claude Code,
Cursor, Cline, or any other MCP-aware client can call to ground library
questions in the exact pinned-version docs instead of training data.
"""

from __future__ import annotations

__version__ = "0.0.1"
__all__ = ["__version__"]
