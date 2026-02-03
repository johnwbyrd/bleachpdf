"""
Pytest configuration for bleachpdf integration tests.

Downloads the olmOCR-bench dataset on first run and provides fixtures
for parameterized redaction testing.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

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
    # Skip math - LaTeX won't match OCR output
}


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
    pdf_filter: str | None = None,
    limit: int | None = None,
    sample: int | None = None,
) -> list[tuple[Path, str, str]]:
    """
    Load test cases from the dataset.

    Returns list of (pdf_path, text, test_id) tuples.
    """
    if categories is None:
        categories = CATEGORIES

    cases: list[tuple[Path, str, str]] = []

    for category in categories:
        jsonl_path = BENCH_DATA_DIR / f"{category}.jsonl"
        if not jsonl_path.exists():
            continue

        entries = load_jsonl(jsonl_path)

        for entry in entries:
            pdf_name = entry.get("pdf", "")
            if not pdf_name:
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
                cases.append((pdf_path, text, test_id))

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


def pytest_configure(config: pytest.Config) -> None:
    """Run setup checks before tests."""
    check_tesseract()
    ensure_dataset()


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Dynamically parameterize tests based on CLI options."""
    if "pdf_path" in metafunc.fixturenames:
        # Parse CLI options
        pdf_filter = metafunc.config.getoption("--pdf")
        category_opt = metafunc.config.getoption("--category")
        sample = metafunc.config.getoption("--sample")
        limit = metafunc.config.getoption("--limit")

        categories = None
        if category_opt:
            categories = [c.strip() for c in category_opt.split(",")]

        # Load test cases
        cases = load_test_cases(
            categories=categories,
            pdf_filter=pdf_filter,
            limit=limit,
            sample=sample,
        )

        if not cases:
            pytest.skip("No test cases match the specified filters")

        # Parameterize
        metafunc.parametrize(
            "pdf_path,text,test_id",
            cases,
            ids=[c[2] for c in cases],
        )


@pytest.fixture
def config_file(tmp_path: Path, text: str) -> Generator[Path, None, None]:
    """Generate a temporary pii.yaml config file for the test text."""
    from bleachpdf import normalize

    # Normalize the text (remove spaces, punctuation)
    pattern = normalize(text)

    # Escape special regex characters
    escaped = escape_peg_regex(pattern)

    # Create case-insensitive pattern
    config_content = f'patterns:\n  - \'match = ~"(?i){escaped}"\'\n'

    config_path = tmp_path / "pii.yaml"
    config_path.write_text(config_content)

    yield config_path


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


@pytest.fixture
def bleachpdf_path() -> Path:
    """Return the path to the bleachpdf command."""
    # Try to find it in PATH first (installed)
    which = shutil.which("bleachpdf")
    if which:
        return Path(which)

    # Fall back to running as module
    return Path("bleachpdf")


@pytest.fixture
def save_output(request) -> bool:
    """Return whether to save redacted PDFs for inspection."""
    return request.config.getoption("--save-output")


@pytest.fixture
def run_bleachpdf(bleachpdf_path: Path, tmp_path: Path, config_file: Path, save_output: bool, test_id: str):
    """Fixture that returns a function to run bleachpdf."""
    output_path = tmp_path / "output.pdf"

    def _run(pdf_path: Path) -> subprocess.CompletedProcess:
        # Determine how to invoke bleachpdf
        if bleachpdf_path.name == "bleachpdf" and not bleachpdf_path.is_absolute():
            # Run as module
            cmd = [
                "python",
                "-m",
                "bleachpdf",
                str(pdf_path),
                "-o",
                str(output_path),
                "-c",
                str(config_file),
            ]
        else:
            cmd = [
                str(bleachpdf_path),
                str(pdf_path),
                "-o",
                str(output_path),
                "-c",
                str(config_file),
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        # Save output for human inspection if requested
        if save_output and output_path.exists():
            # Create output directory structure from test_id
            # test_id looks like "old_scans/50_262572" or "headers_footers/abc123/0"
            saved_path = OUTPUT_DIR / f"{test_id}.pdf"
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(output_path, saved_path)

        return result

    return _run
