"""URL and file-path guards for the profiler.

Every path the profiler reads or writes is built here, so a string that arrived
from a web page, a model answer or a command line can never address a file
outside the directory it belongs in. The one deliberate exception is a file the
operator names for ``--html`` / ``--existing`` / ``--out``: those are resolved
against the real filesystem, must be regular files, and are never joined to a
cache directory.

A static-analysis finding (path traversal: an untrusted URL reached
``CachedFetcher.fetch()``) prompted this module. The cache file name stays a
hash, ``contained()`` re-checks the result before anything is opened, and only
``http(s)`` URLs ever reach the transport.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import SplitResult, urlsplit

# urllib also understands file://, ftp:// and data:, so "a URL" is not enough:
# only http(s) may ever reach the transport.
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


class UnsafePathError(ValueError):
    """A value that should be a name or a URL tried to address something else."""


def check_url(url: str) -> SplitResult:
    """Return the parsed URL, or refuse it when its scheme is not http(s)."""
    parts = urlsplit(url or "")
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        shown = scheme or "a relative path"
        raise UnsafePathError(f"only http(s) URLs are fetched, not {shown!r}: {url!r}")
    if not parts.hostname:
        raise UnsafePathError(f"URL has no host: {url!r}")
    return parts


def contained(base: Path, name: str) -> Path:
    """Join ``name`` to ``base`` and refuse anything that resolves outside it."""
    root = Path(base).resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise UnsafePathError(f"refusing a path outside {root}: {name!r}")
    return candidate


def readable_file(path: str | Path) -> Path:
    """Resolve a file the operator named explicitly; it must already exist."""
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError as exc:
        raise UnsafePathError(f"cannot read {path}: {exc}") from exc
    if not resolved.is_file():
        raise UnsafePathError(f"not a regular file: {path}")
    return resolved


def writable_file(path: str | Path) -> Path:
    """Resolve an output file the operator named; its directory must exist."""
    resolved = Path(path).resolve()
    if resolved.is_dir():
        raise UnsafePathError(f"is a directory, not a file: {path}")
    if not resolved.parent.is_dir():
        raise UnsafePathError(f"output directory does not exist: {resolved.parent}")
    return resolved
