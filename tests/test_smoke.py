"""Smoke tests - verify the package imports and core wiring is intact.

Run with:  uv run pytest

Network + OpenAI-key-requiring paths are NOT exercised here; v0.1
verification is end-to-end via `docchat-server index react 18.2.0` against
a real OpenAI key on the developer's machine.
"""

from __future__ import annotations

from pathlib import Path


def test_package_imports() -> None:
    import docchat_server

    assert docchat_server.__version__ == "0.0.1"


def test_library_config_has_react_fastapi_vue() -> None:
    from docchat_server.library_config import LIBRARY_CONFIG

    assert set(LIBRARY_CONFIG.keys()) == {"react", "fastapi", "vue"}
    for name, cfg in LIBRARY_CONFIG.items():
        assert "/" in cfg.repo, f"{name} repo must be 'owner/name', got {cfg.repo!r}"
        assert cfg.paths, f"{name} has no doc paths"
        assert callable(cfg.ref_for)


def test_fastapi_ref_returns_version_react_returns_main() -> None:
    from docchat_server.library_config import LIBRARY_CONFIG

    assert LIBRARY_CONFIG["fastapi"].ref_for("0.100.0") == "0.100.0"
    assert LIBRARY_CONFIG["fastapi"].ref_for("0.95.2") == "0.95.2"
    assert LIBRARY_CONFIG["react"].ref_for("18.2.0") == "main"
    assert LIBRARY_CONFIG["vue"].ref_for("3.4.0") == "main"


def test_collection_name_sanitisation() -> None:
    from docchat_server.library_config import collection_name_for

    assert collection_name_for("react", "18.2.0") == "react_18_2_0"
    assert collection_name_for("FastAPI", "0.100.0") == "fastapi_0_100_0"
    assert collection_name_for("vue", "3.4.0") == "vue_3_4_0"


def test_urls_for_unknown_library_returns_empty() -> None:
    from docchat_server.library_config import urls_for

    assert urls_for("django", "5.0") == ()
    assert urls_for("react", "18.2.0")  # non-empty


def test_urls_for_fastapi_uses_version_tag() -> None:
    from docchat_server.library_config import urls_for

    urls = urls_for("fastapi", "0.100.0")
    assert urls
    for url in urls:
        assert "/tiangolo/fastapi/0.100.0/" in url, f"expected version tag in {url}"


def test_urls_for_react_uses_main() -> None:
    from docchat_server.library_config import urls_for

    urls = urls_for("react", "18.2.0")
    assert urls
    for url in urls:
        assert "/reactjs/react.dev/main/" in url


def test_default_qdrant_path_under_home_dir() -> None:
    from docchat_server.indexer import default_qdrant_path

    p = default_qdrant_path()
    assert isinstance(p, Path)
    assert ".docchat-server" in str(p)


def test_qdrant_path_env_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from docchat_server.indexer import default_qdrant_path

    monkeypatch.setenv("QDRANT_PATH", "/tmp/test-docchat-server-qdrant")
    assert default_qdrant_path() == Path("/tmp/test-docchat-server-qdrant")


def test_cli_help_runs() -> None:
    """argparse subparser registration sanity check."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "docchat_server.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    # argparse exits 0 from --help
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "index" in result.stdout
    assert "list" in result.stdout


def test_indexer_raises_on_unknown_library() -> None:
    from docchat_server.indexer import DocIndexer

    # Construct without ever calling .index() so we don't need a real
    # qdrant or openai client.
    class _FakeQdrant:
        pass

    class _FakeOpenAI:
        pass

    indexer = DocIndexer(qdrant=_FakeQdrant(), openai=_FakeOpenAI())  # type: ignore[arg-type]
    try:
        indexer.index("django", "5.0")
    except ValueError as exc:
        assert "no indexer wired" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported library")
