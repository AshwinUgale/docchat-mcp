# Changelog

All notable changes to docchat-server are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.2] - 2026-06-08

### Added
- README screenshots from a real Cursor session showing `search_docs` tool call + grounded answer, the supported-libraries refusal flow, and the connected MCP server panel.
- "Known limitations (v0.0.x)" README section calling out single-MCP-client constraint (embedded-Qdrant file lock), bring-your-own-OpenAI-key model, and CLI-only indexing.
- Clean error handling in `server.py` for Qdrant lock conflicts. Instead of a Python traceback when another `docchat-server` already holds the storage directory, the server now exits with a one-line actionable error pointing at the fix.

### Changed
- README install instruction prefers `uv tool install docchat-server` over `pip install docchat-server` so the CLI lands on PATH automatically (the latter requires `pip install --user` to behave the same on Windows).
- README front-matter rewritten as one paragraph that names the problem (training-data version bias) and the fix (version-pinned retrieval via MCP) before any install instructions.
- Status badge replaced with a live PyPI version badge.

### Notes
- GitHub repo name stays `docchat-mcp` (predates the PyPI rename — `docchat-mcp` was taken on PyPI when this project went to publish). README cross-link surfaces this so users can find the repo.

## [0.0.1] - 2026-06-07

### Added
- Initial release.
- FastMCP server (`docchat-server serve`) exposing two tools: `search_docs(library, version, query, api_name?, top_k?)` and `list_indexed()`.
- Embedded Qdrant vector store at `~/.docchat-server/qdrant/` — no Docker required.
- CLI: `docchat-server index <library> <version>` populates a collection; `docchat-server list` shows what's indexed.
- Built-in support for React (`reactjs/react.dev` main branch), FastAPI (per-version tag fetch from `tiangolo/fastapi`), Vue (`vuejs/docs` main branch).
- Per-library cosine-similarity score floors (React 0.15, FastAPI 0.10, Vue 0.05) ported from the [`docchat`](https://github.com/AshwinUgale/docchat) eval-tuned defaults.
- GitHub Actions release workflow at `.github/workflows/release.yml` triggering on `v*.*.*` tag push, publishing to PyPI via Trusted Publishing (OIDC, no tokens).
