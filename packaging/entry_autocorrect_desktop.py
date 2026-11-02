"""PyInstaller entry stub for `AutoCorrectDesktop.exe` (see `autocorrect.launcher`)."""

from __future__ import annotations

import multiprocessing
import sys

from autocorrect.launcher import main

if __name__ == "__main__":
    # Required for `multiprocessing.connection` listeners inside a frozen Windows build.
    multiprocessing.freeze_support()
    sys.exit(main())
