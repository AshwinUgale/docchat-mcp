"""Per-library doc-source config + Qdrant collection naming.

Ported verbatim from docchat/sidecar/src/docchat_sidecar/indexer.py
(_LIBRARY_CONFIG). Each library declares the source repo, the doc paths to
fetch, and a ``ref_for(version)`` callable that maps the user's pinned
version to a git ref.

For libraries whose docs live in the same repo as the released source
(FastAPI, Flask), ``ref_for`` returns the version tag - so indexing
``fastapi@0.100.0`` fetches Pydantic-v2-era docs from the 0.100.0 tag.
For libraries whose docs live in a separate untagged repo (React, Vue),
``ref_for`` returns ``"main"`` and the chunk metadata still surfaces the
user's pinned version via the collection name + chunk header.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

__all__ = ["LibraryConfig", "LIBRARY_CONFIG", "collection_name_for", "urls_for"]


_REACT_DOC_PATHS: tuple[str, ...] = (
    "src/content/reference/react/useState.md",
    "src/content/reference/react/useEffect.md",
    "src/content/reference/react/useContext.md",
    "src/content/reference/react/useReducer.md",
    "src/content/reference/react/useMemo.md",
    "src/content/reference/react/useCallback.md",
    "src/content/reference/react/useRef.md",
    "src/content/reference/react/useId.md",
    "src/content/reference/react/useSyncExternalStore.md",
    "src/content/reference/react/useTransition.md",
)

_FASTAPI_DOC_PATHS: tuple[str, ...] = (
    "docs/en/docs/tutorial/first-steps.md",
    "docs/en/docs/tutorial/path-params.md",
    "docs/en/docs/tutorial/query-params.md",
    "docs/en/docs/tutorial/body.md",
    "docs/en/docs/tutorial/response-model.md",
    "docs/en/docs/tutorial/dependencies/index.md",
    "docs/en/docs/tutorial/background-tasks.md",
    "docs/en/docs/tutorial/middleware.md",
    "docs/en/docs/tutorial/cors.md",
    "docs/en/docs/tutorial/dependencies/dependencies-with-yield.md",
)

_VUE_DOC_PATHS: tuple[str, ...] = (
    "src/api/reactivity-core.md",
    "src/api/reactivity-utilities.md",
    "src/api/composition-api-setup.md",
    "src/api/composition-api-lifecycle.md",
    "src/api/composition-api-dependency-injection.md",
    "src/api/general.md",
    "src/api/sfc-script-setup.md",
    "src/guide/essentials/reactivity-fundamentals.md",
    "src/guide/essentials/computed.md",
    "src/guide/essentials/watchers.md",
)


@dataclass(frozen=True, kw_only=True)
class LibraryConfig:
    """Per-library doc-source config used by urls_for to build raw-GitHub URLs."""

    repo: str
    paths: tuple[str, ...]
    ref_for: Callable[[str], str]


def _fastapi_ref(version: str) -> str:
    """FastAPI is tagged per release; the docs at that tag reflect the
    correct Pydantic generation (v1 for <0.100, v2 for >=0.100)."""
    return version


def _docs_repo_main(_: str) -> str:
    """React/Vue docs aren't version-tagged; always fetch from main."""
    return "main"


LIBRARY_CONFIG: dict[str, LibraryConfig] = {
    "react": LibraryConfig(
        repo="reactjs/react.dev",
        paths=_REACT_DOC_PATHS,
        ref_for=_docs_repo_main,
    ),
    "fastapi": LibraryConfig(
        repo="tiangolo/fastapi",
        paths=_FASTAPI_DOC_PATHS,
        ref_for=_fastapi_ref,
    ),
    "vue": LibraryConfig(
        repo="vuejs/docs",
        paths=_VUE_DOC_PATHS,
        ref_for=_docs_repo_main,
    ),
}


def collection_name_for(library: str, version: str) -> str:
    """Qdrant collection name for a (library, version) pair.

    Lowercases the library and replaces ``.`` with ``_`` so Qdrant's
    collection-name constraints are satisfied. Example::

        collection_name_for("react", "18.2.0") -> "react_18_2_0"
    """
    safe_lib = re.sub(r"[^a-z0-9]+", "_", library.lower()).strip("_")
    safe_ver = re.sub(r"[^a-z0-9]+", "_", version.lower()).strip("_")
    return f"{safe_lib}_{safe_ver}"


def urls_for(library: str, version: str) -> tuple[str, ...]:
    """Source URLs for a given (library, version), or ()  if unsupported."""
    config = LIBRARY_CONFIG.get(library.lower())
    if config is None:
        return ()
    ref = config.ref_for(version)
    base = f"https://raw.githubusercontent.com/{config.repo}/{ref}"
    return tuple(f"{base}/{path}" for path in config.paths)
