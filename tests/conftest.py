"""
Pytest configuration for bleachpdf integration tests.

Downloads the olmOCR-bench dataset on first run and provides fixtures
for parameterized redaction testing.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import pytest

# =============================================================================
# Constants
# =============================================================================

DATASET_REPO = "allenai/olmOCR-bench"
DATASET_DIR = Path(__file__).parent / "olmocr-bench"
BENCH_DATA_DIR = DATASET_DIR / "bench_data"
OUTPUT_DIR = Path(__file__).parent / "output"

# Categories available in the dataset
CATEGORIES = [
    "arxiv_math",
    "headers_footers",
    "long_tiny_text",
    "multi_column",
    "old_scans",
    "old_scans_math",
    "table_tests",
]

# Test types and which fields contain redactable text
TEXT_FIELDS = {
    "present": ["text"],
    "absent": ["text"],
    "order": ["before", "after"],
    "table": ["cell", "up", "down", "left", "right", "top_heading", "left_heading"],
}

# Default test types to run (skip absent, math, baseline)
DEFAULT_TYPES = ["present", "order", "table"]


# =============================================================================
# Test Result Tracking
# =============================================================================


class TestResultTracker:
    """Track test results with redaction details."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.threshold = 0.0
        # Detailed redaction tracking
        self.with_redactions = 0  # Tests that actually redacted something
        self.zero_redactions = 0  # Tests with 0 redactions (suspicious)
        self.zero_redaction_tests: list[str] = []  # Test IDs for investigation

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100

# Global tracker instance
_result_tracker = TestResultTracker()


# =============================================================================
# Tesseract Check
# =============================================================================


def check_tesseract() -> None:
    """Verify Tesseract is installed, exit with instructions if not."""
    if shutil.which("tesseract") is None:
        pytest.exit(
            "Tesseract is not installed.\n\n"
            "Install it with:\n"
            "  Linux:   sudo apt install tesseract-ocr\n"
            "  macOS:   brew install tesseract\n"
            "  Windows: choco install tesseract\n",
            returncode=1,
        )


# =============================================================================
# Dataset Download
# =============================================================================


def download_dataset() -> None:
    """Download the olmOCR-bench dataset using huggingface_hub."""
    from huggingface_hub import snapshot_download

    print(f"Downloading {DATASET_REPO} to {DATASET_DIR}...")
    snapshot_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        local_dir=str(DATASET_DIR),
    )
    print("Download complete.")


def ensure_dataset() -> None:
    """Download dataset if not already present."""
    if not BENCH_DATA_DIR.exists():
        download_dataset()

    # Verify we have the expected structure
    if not any(BENCH_DATA_DIR.glob("*.jsonl")):
        pytest.exit(
            f"Dataset downloaded but no JSONL files found in {BENCH_DATA_DIR}.\n"
            "The dataset structure may have changed.",
            returncode=1,
        )


# =============================================================================
# Test Case Loading
# =============================================================================


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def extract_texts(entry: dict) -> list[str]:
    """Extract all redactable text strings from a test entry."""
    test_type = entry.get("type", "")
    fields = TEXT_FIELDS.get(test_type, [])

    texts = []
    for field in fields:
        value = entry.get(field)
        if value and isinstance(value, str):
            # Skip very short strings (likely noise) and very long ones (performance)
            if 3 <= len(value) <= 200:
                texts.append(value)

    return texts


def load_test_cases(
    categories: list[str] | None = None,
    types: list[str] | None = None,
    pdf_filter: str | None = None,
    limit: int | None = None,
    sample: int | None = None,
) -> list[tuple[Path, str, str, str]]:
    """
    Load test cases from the dataset.

    Returns list of (pdf_path, text, test_id, test_type) tuples.
    """
    if categories is None:
        categories = CATEGORIES
    if types is None:
        types = DEFAULT_TYPES

    cases: list[tuple[Path, str, str, str]] = []

    for category in categories:
        jsonl_path = BENCH_DATA_DIR / f"{category}.jsonl"
        if not jsonl_path.exists():
            continue

        entries = load_jsonl(jsonl_path)

        for entry in entries:
            pdf_name = entry.get("pdf", "")
            if not pdf_name:
                continue

            # Filter by test type
            test_type = entry.get("type", "unknown")
            if test_type not in types:
                continue

            # Apply PDF filter
            if pdf_filter and pdf_filter not in pdf_name:
                continue

            pdf_path = BENCH_DATA_DIR / "pdfs" / pdf_name
            if not pdf_path.exists():
                continue

            test_id_base = entry.get("id", pdf_name)
            texts = extract_texts(entry)

            for i, text in enumerate(texts):
                test_id = f"{category}/{test_id_base}/{i}" if len(texts) > 1 else f"{category}/{test_id_base}"
                cases.append((pdf_path, text, test_id, test_type))

    # Apply sampling
    if sample and sample < len(cases):
        cases = random.sample(cases, sample)

    # Apply limit
    if limit and limit < len(cases):
        cases = cases[:limit]

    return cases


# =============================================================================
# Pytest Hooks and Fixtures
# =============================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command-line options."""
    parser.addoption(
        "--pdf",
        action="store",
        default=None,
        help="Filter to PDFs containing this string",
    )
    parser.addoption(
        "--category",
        action="store",
        default=None,
        help="Comma-separated list of categories to test (default: all)",
    )
    parser.addoption(
        "--types",
        action="store",
        default=None,
        help="Comma-separated list of test types (default: present,order,table)",
    )
    parser.addoption(
        "--sample",
        action="store",
        type=int,
        default=None,
        help="Randomly sample N test cases",
    )
    parser.addoption(
        "--limit",
        action="store",
        type=int,
        default=None,
        help="Limit to first N test cases",
    )
    parser.addoption(
        "--save-output",
        action="store_true",
        default=True,
        help="Save redacted PDFs to tests/output/ for inspection (default: enabled)",
    )
    parser.addoption(
        "--no-save-output",
        action="store_false",
        dest="save_output",
        help="Don't save redacted PDFs (for CI/CD)",
    )
    parser.addoption(
        "--pass-threshold",
        action="store",
        type=float,
        default=0.0,
        help="Minimum pass rate (0-100) required. Fail if below threshold. Default: 0 (disabled)",
    )
    parser.addoption(
        "--jobs",
        action="store",
        type=int,
        default=None,
        help="Number of parallel workers (default: half the CPU count)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Run setup checks before tests."""
    check_tesseract()
    ensure_dataset()

    # Store threshold for later use
    _result_tracker.threshold = config.getoption("--pass-threshold")


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    """Print summary and enforce pass threshold."""
    tracker = _result_tracker

    # Print summary
    print("\n" + "=" * 70)
    print("REDACTION TEST SUMMARY")
    print("=" * 70)
    print(f"  Passed:  {tracker.passed}")
    print(f"  Failed:  {tracker.failed}")
    print(f"  Total:   {tracker.total}")
    print(f"  Pass rate: {tracker.pass_rate:.1f}%")
    print()
    print("  Redaction breakdown:")
    print(f"    With redactions:    {tracker.with_redactions}")
    print(f"    Zero redactions:    {tracker.zero_redactions}  (suspicious - OCR may have failed)")

    if tracker.zero_redaction_tests:
        print()
        print("  Zero-redaction tests (first 10):")
        for test_id in tracker.zero_redaction_tests[:10]:
            print(f"    - {test_id}")
        if len(tracker.zero_redaction_tests) > 10:
            print(f"    ... and {len(tracker.zero_redaction_tests) - 10} more")

    if tracker.threshold > 0:
        print()
        print(f"  Threshold: {tracker.threshold:.1f}%")

        if tracker.pass_rate < tracker.threshold:
            print(f"\n  THRESHOLD NOT MET: {tracker.pass_rate:.1f}% < {tracker.threshold:.1f}%")
            # Force failure exit status
            session.exitstatus = 1
        else:
            print(f"\n  THRESHOLD MET: {tracker.pass_rate:.1f}% >= {tracker.threshold:.1f}%")

    print("=" * 70)


def escape_peg_regex(s: str) -> str:
    """Escape special regex characters for use in PEG pattern."""
    # Characters that need escaping in regex
    special = r"\.^$*+?{}[]|()"
    result = []
    for c in s:
        if c in special:
            result.append(f"\\{c}")
        else:
            result.append(c)
    return "".join(result)
