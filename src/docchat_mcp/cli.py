"""docchat-mcp CLI.

Subcommands:
- ``docchat-mcp serve``                  - run the MCP server on stdio.
- ``docchat-mcp index <library> <ver>``  - populate the local Qdrant.
- ``docchat-mcp list``                   - show indexed collections.

The ``serve`` subcommand is what an MCP host (Claude Code, Cursor, Cline)
spawns. The ``index`` and ``list`` subcommands are for the user, run
manually to set up before pointing an MCP host at the server.
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from docchat_mcp import __version__


def _cmd_serve(_args: argparse.Namespace) -> int:
    # Import inside the handler so `docchat-mcp index` doesn't pull in
    # FastMCP (which checks OPENAI_API_KEY at import time in server.py).
    from docchat_mcp.server import main as serve_main

    serve_main()
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "ERROR: OPENAI_API_KEY is not set. docchat-mcp uses OpenAI's "
            "embeddings API. Set it in your shell or a .env file.",
            file=sys.stderr,
        )
        return 2

    from openai import OpenAI

    from docchat_mcp.indexer import DocIndexer, open_qdrant

    qdrant = open_qdrant()
    indexer = DocIndexer(qdrant=qdrant, openai=OpenAI())

    def _progress(msg: str) -> None:
        print(f"[indexer] {msg}", file=sys.stderr, flush=True)

    try:
        total = indexer.index(args.library, args.version, progress=_progress)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"indexed {total} chunks into {args.library}@{args.version}")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    from docchat_mcp.indexer import open_qdrant
    from docchat_mcp.library_config import LIBRARY_CONFIG

    qdrant = open_qdrant()
    collections = qdrant.get_collections().collections
    print("Indexed collections:")
    if not collections:
        print("  (none yet - run `docchat-mcp index <library> <version>`)")
    for c in collections:
        try:
            count = qdrant.count(collection_name=c.name).count
        except Exception:
            count = "?"
        print(f"  - {c.name}  ({count} chunks)")
    print()
    print(f"Supported libraries: {', '.join(sorted(LIBRARY_CONFIG.keys()))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="docchat-mcp",
        description="Version-pinned doc retrieval as an MCP server.",
    )
    parser.add_argument("--version", action="version", version=f"docchat-mcp {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the MCP server on stdio")
    p_serve.set_defaults(func=_cmd_serve)

    p_index = sub.add_parser(
        "index", help="fetch + embed + upsert docs for one (library, version)"
    )
    p_index.add_argument("library", help="e.g. react, fastapi, vue")
    p_index.add_argument("version", help="e.g. 18.2.0, 0.100.0, 3.4.0")
    p_index.set_defaults(func=_cmd_index)

    p_list = sub.add_parser("list", help="show indexed collections")
    p_list.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
