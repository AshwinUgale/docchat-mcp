# docchat-server

> Version-pinned documentation retrieval as a Model Context Protocol server. Gives Claude Code / Cursor / any MCP-aware AI grounded answers from the docs of the exact library version your lockfile pins.

[![status](https://img.shields.io/badge/status-alpha-orange)](#)
[![license](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![version](https://img.shields.io/badge/version-0.0.1-blue)](./pyproject.toml)

**Status:** v0.0 — initial scaffold. v0.1 ships PyPI + Smithery registration once the FastMCP server is locally verified.

---

## What it is

Claude Code, Cursor, and other AI coding assistants answer library questions from training data. If your project pins `react@18.2.0` and the latest is `19.1.0`, you get React 19 APIs in your React 18 file — the model has no way to know which version actually matters.

`docchat-server` is an MCP server that fixes that. Index a library at the version you pin once. Register the server with your MCP host. Now every query to your coding assistant can be grounded in the docs for the *exact pinned version*, with hard refusal when the docs don't cover the question.

It's the [DocChat VS Code extension](https://github.com/AshwinUgale/docchat) stripped of its agent + chat UI, exposed as an MCP tool surface instead. The retrieval logic, version-aware routing, and per-library cosine score floors are identical (and identically eval-tuned).

---

## Install

```bash
pip install docchat-server        # or: uvx --from docchat-server docchat-server
```

Requires Python 3.11+ and an `OPENAI_API_KEY` env var (used for query + index-time embeddings). The Qdrant vector store runs *embedded* — no Docker, no separate server.

---

## Use (3 steps)

### 1. Index the libraries you care about

```bash
export OPENAI_API_KEY=sk-...

docchat-server index react 18.2.0
docchat-server index fastapi 0.100.0
docchat-server index vue 3.4.0
```

Each index takes ~30–60 seconds and a few cents of embedding cost. Stored at `~/.docchat-server/qdrant/`.

### 2. Verify

```bash
docchat-server list
```

```
Indexed collections:
  - react_18_2_0    (47 chunks)
  - fastapi_0_100_0 (38 chunks)
  - vue_3_4_0       (62 chunks)

Supported libraries: fastapi, react, vue
```

### 3. Register with your MCP host

Claude Desktop / Claude Code: add to your MCP config (`~/.config/claude/mcp-config.json` on Mac/Linux, `%APPDATA%\Claude\mcp-config.json` on Windows):

```json
{
  "mcpServers": {
    "docchat": {
      "command": "docchat-server",
      "args": ["serve"],
      "env": {
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

Restart your MCP host. The `docchat` server should appear with two tools: `search_docs` and `list_indexed`.

---

## The tools

### `search_docs(library, version, query, api_name?, top_k?)`

Retrieves top-K chunks from the indexed docs of the exact pinned version. Returns the chunks with citations, or `"No relevant chunks found"` if nothing clears the per-library cosine floor (a hard signal to the model that it should refuse rather than guess).

### `list_indexed()`

Returns the collections currently populated locally. Useful as a session-start probe — your assistant can call this once to know what's available before answering anything.

---

## Sibling project

The same retrieval engine ships as a [VS Code extension on the Marketplace](https://marketplace.visualstudio.com/items?itemName=AshwinUgale.docchat). Source: https://github.com/AshwinUgale/docchat. If you want a chat panel instead of MCP-tool integration, install that.

---

## Roadmap

- **v0.1** — PyPI publish, Smithery listing, README screenshots from real Claude Code session
- **v0.2** — `detect_pinned_libraries(workspace_path)` tool (parse package.json / pyproject.toml / requirements.txt and report pinned versions to the assistant)
- **v0.3** — `--repo` / `--paths` flags for arbitrary library indexing (extend beyond the built-in react / fastapi / vue)
- **v0.4** — local embeddings via sentence-transformers (drop the OpenAI dependency for the embed step)

---

## License

MIT. See [LICENSE](./LICENSE).
