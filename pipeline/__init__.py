"""
Global Language Intelligence Maintenance Pipeline.
Ingests, validates, compiles into zero-copy mmap binary formats,
runs Golden Corpus regression tests, and signs versioned resource releases.

Every tool here is run as ``python -m pipeline.<tool>`` from the repository
root. The application package lives under ``src/`` (a src-layout), so unless
the project has been ``pip install -e .``'d the import ``autocorrect`` would
fail. Importing this package puts ``src/`` on ``sys.path`` when needed, so the
tools work from a plain checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> None:
    try:
        import autocorrect  # noqa: F401
    except ModuleNotFoundError:
        src = Path(__file__).resolve().parent.parent / "src"
        if (src / "autocorrect").is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))


_ensure_src_on_path()
