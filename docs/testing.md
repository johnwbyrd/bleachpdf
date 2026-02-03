# Testing Strategy

bleachpdf uses a rigorous, real-world testing approach that sets it apart from comparable tools. Rather than relying on synthetic test cases, it validates against a standardized OCR benchmark containing hundreds of challenging documents.

## The olmOCR-bench Dataset

Tests run against [olmOCR-bench](https://huggingface.co/datasets/allenai/olmOCR-bench), a benchmark dataset from the Allen Institute for AI. This dataset was designed to challenge OCR systems and contains documents that are genuinely difficult to process:

| Category | Description |
|----------|-------------|
| `arxiv_math` | Academic papers with mathematical notation |
| `headers_footers` | Documents with complex headers and footers |
| `long_tiny_text` | Small or dense text that's hard to recognize |
| `multi_column` | Multi-column layouts common in journals |
| `old_scans` | Aged or degraded scanned documents |
| `old_scans_math` | Old scans containing mathematical content |
| `table_tests` | Documents with tabular data |

The dataset is downloaded automatically on first test run.

## What Gets Tested

Each test case extracts text from the benchmark data, creates a pattern to match it, runs bleachpdf on the corresponding PDF, and then **re-scans the output to verify the text is actually hidden**. This verification step catches cases where:

- OCR found the text but redaction coordinates were wrong
- The black box was too small
- The text appeared in multiple locations and one was missed

A test passes only if the verification scan finds zero matches for the original text.

## Test Types

The benchmark includes several test types:

- **present**: Verify that specific text exists and can be redacted
- **order**: Test text that appears in a specific sequence
- **table**: Test text within table cells and their relationships

By default, tests run against `present`, `order`, and `table` types. Math-heavy and absence tests are skipped as they're less relevant to redaction accuracy.

## Running Tests

Install dev dependencies and run:

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests run in parallel by default using half your CPU cores.

### Useful Options

```bash
# Control parallelism
pytest tests/ --jobs=4        # Use 4 workers
pytest tests/ -n 1            # Run serially

# Filter tests
pytest tests/ --category=old_scans              # Test only old scans
pytest tests/ --types=present,table             # Specific test types
pytest tests/ --pdf=arxiv                       # PDFs containing "arxiv"

# Limit scope
pytest tests/ --limit=50      # First 50 test cases
pytest tests/ --sample=50     # Random sample of 50

# Language support
pytest tests/ --lang=eng+kor  # Test with English + Korean OCR

# Output control
pytest tests/ --save-output   # Save redacted PDFs to tests/output/ (default)
pytest tests/ --no-save-output # Don't save (for CI)

# Quality gates
pytest tests/ --pass-threshold=90  # Fail if pass rate < 90%
```

## Continuous Integration

For CI pipelines, use these flags:

```bash
pytest tests/ --no-save-output --pass-threshold=90
```

This skips saving output files (saves disk space) and enforces a minimum pass rate.

## Why This Matters

Most free redaction tools ship with minimal or no automated testing. The ones that do test typically use a handful of hand-crafted PDFs that don't represent real-world difficulty.

bleachpdf tests against thousands of cases drawn from a standardized benchmark that includes the hardest categories of documents: old scans, dense text, complex layouts, and mathematical notation. Every release must pass this gauntlet before shipping.

This doesn't guarantee perfection -- no tool can -- but it provides confidence that bleachpdf handles difficult documents significantly better than untested alternatives.
