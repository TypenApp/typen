"""
Command-line entry point for building, validating, regression-testing,
and compiling the Global Language Intelligence baseline resources.
"""

from __future__ import annotations

import sys
from pathlib import Path

from autocorrect.intelligence.resource_manager import DEFAULT_BUNDLED_DIR
from pipeline.compile_binary import compile_dataset_to_directory
from pipeline.ingest import build_master_english_dataset
from pipeline.regression_runner import run_golden_corpus_regression
from pipeline.validate import validate_and_sanitize_dataset


def build_and_verify_baseline(output_dir: Path = DEFAULT_BUNDLED_DIR) -> None:
    dataset = build_master_english_dataset()
    val_report = validate_and_sanitize_dataset(dataset)
    if not val_report.passed:
        raise RuntimeError(f"Dataset validation failed: {val_report.errors}")

    compile_dataset_to_directory(dataset, output_dir)
    metrics = run_golden_corpus_regression(output_dir)
    if not metrics.passed_gate:
        raise RuntimeError(
            f"Golden corpus regression gate failed: "
            f"typo_acc={metrics.typo_accuracy:.3f}, "
            f"conf_acc={metrics.confusion_accuracy:.3f}, "
            f"fpr={metrics.false_positive_rate:.5f}"
        )


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BUNDLED_DIR
    build_and_verify_baseline(target)
    print(f"Compiled and verified language resources in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
