"""
Integration tests for bleachpdf using the olmOCR-bench dataset.

Each PDF test case becomes a separate pytest test, giving visibility
into progress as tests run.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from bleachpdf import Config, _process_single_pdf, normalize

from .conftest import (
    OUTPUT_DIR,
    escape_peg_regex,
)


def run_redaction_test(
    pdf_path: Path,
    text: str,
    test_id: str,
    save_output: bool,
    lang: str = "eng",
) -> dict:
    """
    Run a single redaction test case.

    Returns dict with result details for tracking.
    """
    # Build pattern from text
    pattern = normalize(text)
    escaped = escape_peg_regex(pattern)
    peg_pattern = f'match = ~"(?i){escaped}"'

    # Determine output path
    if save_output:
        output_path = OUTPUT_DIR / f"{test_id}.pdf"
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # Use temp file
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="bleachpdf_test_")
        os.close(fd)
        output_path = Path(tmp_path)

    # Limit Tesseract's internal threading
    os.environ["OMP_THREAD_LIMIT"] = "1"

    # Run bleachpdf
    config = Config(dpi=300, lang=lang, verify=True)
    result = _process_single_pdf(
        (
            str(pdf_path),
            str(output_path),
            [peg_pattern],
            config,
        )
    )

    # Clean up temp file if not saving
    if not save_output and output_path.exists():
        output_path.unlink()

    return {
        "test_id": test_id,
        "input_path": result.input_path,
        "output_path": result.output_path,
        "redactions": result.redactions,
        "leaked": result.leaked,
        "passed": result.leaked == 0,
    }


def test_redaction(redaction_case, request):
    """
    Test redaction of a single PDF.

    This test is parametrized via pytest_generate_tests in conftest.py,
    creating one test per PDF case for progress visibility.
    """
    pdf_path, text, test_id, test_type = redaction_case
    save_output = request.config.getoption("--save-output")
    lang = request.config.getoption("--lang")

    result = run_redaction_test(pdf_path, text, test_id, save_output, lang=lang)

    # Store result data for aggregation in conftest hooks
    # This works with xdist because user_properties are serialized back to controller
    request.node.user_properties.append(("redactions", result["redactions"]))
    request.node.user_properties.append(("leaked", result["leaked"]))
    request.node.user_properties.append(("test_id", test_id))

    # Assert verification passed (no text leaked)
    assert result["leaked"] == 0, (
        f"Verification failed: {result['leaked']} matches still visible after redaction"
    )
