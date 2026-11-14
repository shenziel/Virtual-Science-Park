"""``python -m agents.profiler …`` runs the profiler CLI.

Same entry point as ``python -m agents.profiler.profiler``; this one avoids the
``runpy`` double-import warning, so the demo command is clean.
"""
from __future__ import annotations

from .profiler import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
