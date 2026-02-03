"""
Integration tests for bleachpdf using the olmOCR-bench dataset.

Each test takes a known text string from the dataset, creates a PEG pattern,
runs bleachpdf to redact it, and verifies the text is no longer visible.
"""

from __future__ import annotations

from pathlib import Path


def test_redaction(
    pdf_path: Path,
    text: str,
    test_id: str,
    run_bleachpdf,
) -> None:
    """
    Test that bleachpdf successfully redacts the given text from the PDF.

    The test passes if:
    - bleachpdf exits with code 0 (verification passed)

    The test fails if:
    - bleachpdf exits with code 1 (verification failed - text still visible)
    - bleachpdf crashes or has other errors
    """
    result = run_bleachpdf(pdf_path)

    # Build informative error message
    if result.returncode != 0:
        error_msg = (
            f"Redaction failed for: {text[:50]}...\n"
            f"PDF: {pdf_path.name}\n"
            f"Test ID: {test_id}\n"
            f"Exit code: {result.returncode}\n"
        )
        if result.stderr:
            error_msg += f"Stderr:\n{result.stderr}\n"
        if result.stdout:
            error_msg += f"Stdout:\n{result.stdout}\n"

        assert False, error_msg
