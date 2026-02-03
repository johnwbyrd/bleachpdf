# Test Suite Plan for bleachpdf

## Overview

This document describes the strategy for building an integration test suite for bleachpdf using the olmOCR-bench dataset as ground truth.

## The Core Idea

The [olmOCR-bench](https://huggingface.co/datasets/allenai/olmOCR-bench) dataset contains 1,403 PDFs with 7,010 verified text assertions. Each assertion says "this text exists in this PDF."

For bleachpdf, we invert this: if text exists in a PDF, we should be able to redact it. After redaction, bleachpdf's verification mode re-scans the output and confirms the text is gone.

**Test logic:**
1. Take a known text string from the dataset
2. Convert it to a normalized PEG pattern
3. Run bleachpdf with that pattern
4. Verification passes (exit code 0) → text successfully redacted → test passes
5. Verification fails (exit code 1) → text still visible → test fails

## Dataset Structure

The HuggingFace dataset is organized by category:

```
bench_data/
├── arxiv_math.jsonl        # 522 PDFs, 2,927 tests (math formulas)
├── headers_footers.jsonl   # 266 PDFs, 753 tests
├── long_tiny_text.jsonl    # 62 PDFs, 442 tests
├── multi_column.jsonl      # 231 PDFs, 884 tests
├── old_scans.jsonl         # 98 PDFs, 526 tests
├── old_scans_math.jsonl    # 36 PDFs, 458 tests
├── table_tests.jsonl       # 188 PDFs, 1,020 tests
└── pdfs/                   # The actual PDF files (Git LFS)
```

Each jsonl file contains test entries like:

```json
{"pdf": "lincoln_letter.pdf", "page": 1, "id": "...", "type": "present", "text": "January 10th 1864."}
{"pdf": "earnings.pdf", "page": 1, "id": "...", "type": "table", "cell": "Research and development"}
```

## Usable Test Types

Every text field in the dataset is a redaction target:

| Test type | Text fields to extract |
|-----------|------------------------|
| `present` | `text` |
| `absent` | `text` |
| `order` | `before`, `after` |
| `table` | `cell`, `up`, `down`, `left`, `right`, `top_heading`, `left_heading` |
| `math` | Skip — LaTeX won't match OCR output |

## Test Data Management

**Principle: The full dataset is always downloaded. What subset you test is your choice.**

- No sample PDFs checked into the repo
- No "basic" vs "full" distinction
- Dataset is downloaded on first test run via `huggingface_hub` Python API
- User filters with command-line options

### Download Mechanism

Using the Python API (not CLI) for cross-platform compatibility:

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="allenai/olmOCR-bench",
    repo_type="dataset",
    local_dir="./tests/olmocr-bench"
)
```

This handles Git LFS transparently and works on Linux, macOS, and Windows.

### Filtering Options

```bash
# Run all tests (overnight)
pytest tests/

# Single PDF
pytest tests/ --pdf=lincoln_letter.pdf

# Single category
pytest tests/ --category=old_scans

# Multiple categories
pytest tests/ --category=old_scans,multi_column

# Random sample
pytest tests/ --sample=100

# First N tests (quick check)
pytest tests/ --limit=20
```

## Directory Structure

```
tests/
├── conftest.py              # Dataset download, fixtures, CLI options
├── test_redaction.py        # Parameterized integration tests
├── olmocr-bench/            # Downloaded dataset (gitignored)
│   └── bench_data/
│       ├── *.jsonl
│       └── pdfs/
└── README.md                # Setup instructions
```

## conftest.py Responsibilities

1. **Check Tesseract is installed** — Exit with clear instructions if not
2. **Download dataset if missing** — Using `huggingface_hub` Python API
3. **Parse command-line filter options** — `--pdf`, `--category`, `--sample`, `--limit`
4. **Load and filter test cases** — Yield `(pdf_path, text, test_id)` tuples
5. **Provide fixtures** — Temp directories, config file generation

## Test Execution

Each test case:

1. Receives `(pdf_path, text, test_id)` from parameterization
2. Normalizes text (remove spaces, punctuation)
3. Generates a temporary `pii.yaml` with case-insensitive pattern
4. Runs `bleachpdf <pdf> -o <tmpdir>/output.pdf -c <tmpdir>/pii.yaml`
5. Asserts exit code 0 (verification passed)

```python
@pytest.mark.parametrize("pdf_path,text,test_id", load_test_cases())
def test_redaction(pdf_path, text, test_id, tmp_path):
    pattern = normalize(text)
    config = tmp_path / "pii.yaml"
    config.write_text(f'patterns:\n  - \'match = ~"(?i){escape_peg(pattern)}"\'')

    result = subprocess.run(
        ["bleachpdf", str(pdf_path), "-o", str(tmp_path / "out.pdf"), "-c", str(config)],
        capture_output=True
    )

    assert result.returncode == 0, f"Verification failed: {text[:50]}..."
```

## Cross-Platform Support

### huggingface_hub

Pure Python, works everywhere. Use the Python API, not the CLI.

### Paths

Use `pathlib.Path` everywhere, never string concatenation with `/`.

### Tesseract Installation

| Platform | Command |
|----------|---------|
| Linux | `sudo apt install tesseract-ocr` |
| macOS | `brew install tesseract` |
| Windows | `choco install tesseract` |

The test suite checks for Tesseract on startup and exits with instructions if missing.

### Windows Long Paths

Windows has a 260-character path limit by default. If this becomes a problem:
- Document how to enable long paths in Windows
- Or download dataset to a short path like `C:\olmocr`

## CI/CD

```yaml
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - name: Install Tesseract (Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get install -y tesseract-ocr

      - name: Install Tesseract (macOS)
        if: runner.os == 'macOS'
        run: brew install tesseract

      - name: Install Tesseract (Windows)
        if: runner.os == 'Windows'
        run: choco install tesseract

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -e .[dev]

      - name: Cache test dataset
        uses: actions/cache@v4
        with:
          path: tests/olmocr-bench
          key: olmocr-bench-v1

      - name: Run tests
        run: pytest tests/ -v
```

The dataset is cached across CI runs to avoid re-downloading 1GB each time.

## Expected Failures

Some tests will fail for legitimate reasons:

1. **OCR can't read the text** — Handwriting, degraded scans, unusual fonts. bleachpdf can't redact what Tesseract can't read.

2. **OCR character errors** — Pattern expects "January" but OCR reads "Januarv". Exact PEG matching fails.

3. **Redaction geometry issues** — Text still partially visible after redaction. This is a real bug.

Strategy:
- Track failure rates by category
- Investigate unexpected failures
- Mark known OCR limitations with `pytest.mark.xfail` and justification
- Geometry failures are bugs to fix

## Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "huggingface_hub>=0.20.0",
    "ruff>=0.8.0",
]
```

## Open Questions

1. **Fuzzy matching** — Should bleachpdf support fuzzy pattern matching to handle OCR errors? Currently uses exact PEG matching.

2. **Parallel test execution** — pytest-xdist could parallelize, but OCR is CPU-heavy. Need to test if it helps or causes resource contention.

3. **Test output artifacts** — Should failing tests save the redacted PDF for inspection? Useful for debugging but consumes disk space.

## Attribution

The olmOCR-bench dataset is licensed under ODC-BY (Open Data Commons Attribution License). Any use must provide attribution to Allen Institute for AI.
