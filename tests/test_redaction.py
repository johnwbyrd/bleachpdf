"""
Integration tests for bleachpdf using the olmOCR-bench dataset.

Runs all test cases in parallel using bleachpdf's ProcessPoolExecutor
infrastructure - the same code path used by the CLI.
"""

from __future__ import annotations

import os
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from bleachpdf import _process_single_pdf, get_worker_count, normalize

from .conftest import (
    OUTPUT_DIR,
    _result_tracker,
    escape_peg_regex,
    load_test_cases,
)


def build_job_args(
    cases: list[tuple[Path, str, str, str]],
    output_dir: Path,
    dpi: int = 300,
    verify: bool = True,
) -> list[tuple[str, str, str, list[str], int, bool, str]]:
    """
    Build job arguments for parallel processing.

    Returns list of (input_path, output_path, test_id, patterns, dpi, verify, test_type) tuples.
    Extended from bleachpdf's format to include test_id and test_type for result tracking.
    """
    jobs = []
    for pdf_path, text, test_id, test_type in cases:
        # Build pattern from text
        pattern = normalize(text)
        escaped = escape_peg_regex(pattern)
        peg_pattern = f'match = ~"(?i){escaped}"'

        # Output path mirrors test_id structure
        output_path = output_dir / f"{test_id}.pdf"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        jobs.append((
            str(pdf_path),
            str(output_path),
            test_id,
            [peg_pattern],
            dpi,
            verify,
            test_type,
        ))

    return jobs


def process_single_test(args: tuple) -> dict:
    """
    Worker function that wraps _process_single_pdf and adds test metadata.

    Takes extended args: (input_path, output_path, test_id, patterns, dpi, verify, test_type)
    Returns dict with result and test metadata.
    """
    input_path, output_path, test_id, patterns, dpi, verify, test_type = args

    # Call bleachpdf's worker function
    result = _process_single_pdf((input_path, output_path, patterns, dpi, verify))

    return {
        "test_id": test_id,
        "test_type": test_type,
        "input_path": result.input_path,
        "output_path": result.output_path,
        "redactions": result.redactions,
        "leaked": result.leaked,
        "passed": result.leaked == 0,
    }


def test_redaction_batch(request):
    """
    Run all redaction tests in parallel using bleachpdf's infrastructure.

    This test collects all test cases, runs them through the same
    ProcessPoolExecutor machinery that the CLI uses, then reports results.
    """
    # Get filter options from pytest config
    pdf_filter = request.config.getoption("--pdf")
    category_opt = request.config.getoption("--category")
    types_opt = request.config.getoption("--types")
    sample = request.config.getoption("--sample")
    limit = request.config.getoption("--limit")
    save_output = request.config.getoption("--save-output")
    jobs_opt = request.config.getoption("--jobs", default=None)

    categories = None
    if category_opt:
        categories = [c.strip() for c in category_opt.split(",")]

    types = None
    if types_opt:
        types = [t.strip() for t in types_opt.split(",")]

    # Load test cases
    cases = load_test_cases(
        categories=categories,
        types=types,
        pdf_filter=pdf_filter,
        limit=limit,
        sample=sample,
    )

    if not cases:
        pytest.skip("No test cases match the specified filters")

    # Determine output directory
    if save_output:
        output_dir = OUTPUT_DIR
    else:
        # Use temp directory that gets cleaned up
        import tempfile
        output_dir = Path(tempfile.mkdtemp(prefix="bleachpdf_test_"))

    # Build job arguments
    job_args = build_job_args(cases, output_dir)

    # Determine parallelism
    num_workers = get_worker_count(jobs_opt, len(job_args))

    # Limit Tesseract's internal threading to avoid oversubscription
    os.environ["OMP_THREAD_LIMIT"] = "1"

    # Process all tests in parallel
    results = []
    if num_workers == 1:
        # Sequential processing
        for args in job_args:
            results.append(process_single_test(args))
    else:
        # Parallel processing using bleachpdf's infrastructure
        with ProcessPoolExecutor(max_workers=num_workers) as pool:
            results = list(pool.map(process_single_test, job_args))

    # Aggregate results
    passed = 0
    failed = 0
    with_redactions = 0
    zero_redactions = 0
    zero_redaction_test_ids = []
    failed_test_ids = []

    for r in results:
        if r["passed"]:
            passed += 1
        else:
            failed += 1
            failed_test_ids.append(r["test_id"])

        # Track redaction counts for ALL tests
        if r["redactions"] > 0:
            with_redactions += 1
        else:
            zero_redactions += 1
            zero_redaction_test_ids.append(r["test_id"])

    # Update global tracker for session summary
    _result_tracker.passed = passed
    _result_tracker.failed = failed
    _result_tracker.with_redactions = with_redactions
    _result_tracker.zero_redactions = zero_redactions
    _result_tracker.zero_redaction_tests = zero_redaction_test_ids

    # Clean up temp directory if not saving
    if not save_output and output_dir.exists():
        shutil.rmtree(output_dir, ignore_errors=True)

    # Assert no verification failures (text leaked through redaction)
    if failed > 0:
        error_msg = f"{failed} tests failed verification (text still visible after redaction):\n"
        for test_id in failed_test_ids[:20]:
            error_msg += f"  - {test_id}\n"
        if len(failed_test_ids) > 20:
            error_msg += f"  ... and {len(failed_test_ids) - 20} more\n"
        pytest.fail(error_msg)
