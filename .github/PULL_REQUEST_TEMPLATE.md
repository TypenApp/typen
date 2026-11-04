## Summary

<!-- Briefly describe what this pull request changes and why. -->

## Related Issue

<!-- Link any related issue, e.g. Fixes #123 or TypenApp/language-data#45 -->

## Changes Made

- 

## Verification & Quality Checklist

- [ ] `pytest` passes locally (including held-out quality tests in `tests/test_engine_quality_heldout.py`)
- [ ] `ruff check src pipeline tests` passes with zero warnings
- [ ] `python -m autocorrect.launcher --headless-check` prints `OK`
- [ ] No network calls added to the Layer 1 offline typing path
- [ ] No raw keystrokes or user text written to logs or disk
- [ ] No GPLv3-only Qt modules imported (`src/autocorrect/ui/lgpl_compliance.py`)
