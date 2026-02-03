#!/usr/bin/env python3
"""
bleachpdf - PII redaction for PDF documents.

Renders each page to an image, OCRs it, matches against PEG grammar patterns,
draws black boxes over matches, and reassembles into a new PDF.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

import fitz
import pytesseract
import yaml
from parsimonious.grammar import Grammar
from PIL import Image, ImageDraw
from platformdirs import site_config_dir, user_config_dir
from reportlab.pdfgen import canvas

if TYPE_CHECKING:
    from parsimonious.nodes import Node

__version__ = "0.1.0"

APP_NAME = "bleachpdf"
CONFIG_FILENAME = "pii.yaml"

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONFIG_ERROR = 1
EXIT_FILE_ERROR = 2
EXIT_NO_MATCHES = 3
EXIT_VERIFICATION_FAILED = 4

log = logging.getLogger(APP_NAME)


# =============================================================================
# Data Types
# =============================================================================


@dataclass(frozen=True, slots=True)
class Word:
    """A word extracted from OCR with its bounding box."""

    text: str
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True, slots=True)
class TextStream:
    """Concatenated normalized text with mapping back to source words."""

    text: str
    word_map: tuple[int, ...]  # char index -> word index


@dataclass(frozen=True, slots=True)
class Box:
    """A rectangular region to redact."""

    left: int
    top: int
    right: int
    bottom: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(frozen=True)
class JobResult:
    """Result from processing a single PDF."""

    input_path: str
    output_path: str
    redactions: int
    leaked: int  # 0 if verification passed or was skipped
    error_code: int = EXIT_SUCCESS
    retried_dpi: int | None = None  # DPI used on retry, or None if no retry


# =============================================================================
# Text Processing
# =============================================================================


def normalize(text: str) -> str:
    """Strip everything except alphanumeric characters."""
    return re.sub(r"[^A-Za-z0-9]", "", text)


def build_stream(words: list[Word]) -> TextStream:
    """
    Concatenate normalized words into a single text stream.

    Returns a TextStream where each character maps back to its source word index,
    allowing pattern matches to span word boundaries.
    """
    chars: list[str] = []
    mapping: list[int] = []

    for i, word in enumerate(words):
        normalized = normalize(word.text)
        chars.append(normalized)
        mapping.extend([i] * len(normalized))

    return TextStream(text="".join(chars), word_map=tuple(mapping))


# =============================================================================
# OCR
# =============================================================================


def ocr_page(img: Image.Image) -> list[Word]:
    """Extract words with bounding boxes from an image using Tesseract."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    words: list[Word] = []

    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if text:
            words.append(
                Word(
                    text=text,
                    left=data["left"][i],
                    top=data["top"][i],
                    width=max(1, data["width"][i]),
                    height=max(1, data["height"][i]),
                )
            )

    return words


# =============================================================================
# Pattern Matching
# =============================================================================


def compile_grammars(patterns: list[str]) -> list[Grammar]:
    """Compile PEG patterns into Grammar objects, warning on invalid patterns."""
    grammars: list[Grammar] = []

    for pattern in patterns:
        try:
            grammars.append(Grammar(pattern))
        except Exception as e:
            # Only log in main process (workers don't have logging configured)
            if log.handlers:
                log.warning("Invalid grammar: %s (%s)", pattern.strip()[:50], e)

    return grammars


def find_matches(stream: TextStream, grammars: list[Grammar]) -> set[int]:
    """
    Find all pattern matches in the text stream.

    Returns the set of word indices that are part of any match.
    """
    matched_words: set[int] = set()

    for grammar in grammars:
        for start in range(len(stream.text)):
            try:
                node: Node | None = grammar.match(stream.text, start)
                if node:
                    for i in range(start, start + len(node.text)):
                        if i < len(stream.word_map):
                            matched_words.add(stream.word_map[i])
            except Exception:
                pass

    return matched_words


# =============================================================================
# Redaction Geometry
# =============================================================================


def group_adjacent_words(matched_indices: set[int], words: list[Word]) -> list[list[int]]:
    """
    Group matched word indices that are on the same line and adjacent.

    This allows drawing a single box over "John Doe" rather than two separate boxes.
    """
    if not matched_indices:
        return []

    sorted_indices = sorted(matched_indices)
    groups: list[list[int]] = []
    current_group = [sorted_indices[0]]

    for idx in sorted_indices[1:]:
        prev_idx = current_group[-1]
        prev = words[prev_idx]
        curr = words[idx]

        # Same line: vertical positions within 0.5x the height (strict to avoid cross-line grouping)
        same_line = abs(prev.top - curr.top) < prev.height * 0.5

        # Adjacent: sequential indices or horizontally close
        adjacent = idx == prev_idx + 1 or (curr.left - prev.right < 50)

        if same_line and adjacent:
            current_group.append(idx)
        else:
            groups.append(current_group)
            current_group = [idx]

    groups.append(current_group)
    return groups


def compute_box(words: list[Word], indices: list[int], img_size: tuple[int, int], pad: int = 4) -> Box:
    """Compute the bounding box for a group of words, with padding."""
    img_w, img_h = img_size
    group_words = [words[i] for i in indices]

    return Box(
        left=max(0, min(w.left for w in group_words) - pad),
        top=max(0, min(w.top for w in group_words) - pad),
        right=min(img_w, max(w.right for w in group_words) + pad),
        bottom=min(img_h, max(w.bottom for w in group_words) + pad),
    )


# =============================================================================
# Image Redaction
# =============================================================================


def draw_redactions(img: Image.Image, boxes: list[Box]) -> Image.Image:
    """Draw black rectangles over the specified regions."""
    img = img.copy()
    draw = ImageDraw.Draw(img)

    for box in boxes:
        draw.rectangle(box.as_tuple(), fill="black")

    return img


def redact_image(img: Image.Image, grammars: list[Grammar]) -> tuple[Image.Image, int]:
    """
    Redact PII from a single image.

    Returns (redacted_image, number_of_redactions).
    """
    words = ocr_page(img)
    if not words:
        return img, 0

    stream = build_stream(words)
    matched = find_matches(stream, grammars)
    if not matched:
        return img, 0

    groups = group_adjacent_words(matched, words)
    boxes = [compute_box(words, group, img.size) for group in groups]

    return draw_redactions(img, boxes), len(boxes)


# =============================================================================
# PDF Operations
# =============================================================================


def render_page(page: fitz.Page, dpi: int) -> Image.Image:
    """Render a PDF page to a PIL Image."""
    pix = page.get_pixmap(dpi=dpi)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def images_to_pdf(images: list[Image.Image], output_path: str, dpi: int) -> None:
    """Assemble images into a PDF at the specified DPI."""
    c = canvas.Canvas(output_path)

    for img in images:
        px_w, px_h = img.size
        pt_w = px_w * 72 / dpi
        pt_h = px_h * 72 / dpi
        c.setPageSize((pt_w, pt_h))

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            img.save(tmp, "PNG")
            tmp_path = tmp.name

        c.drawImage(tmp_path, 0, 0, pt_w, pt_h)
        c.showPage()
        os.unlink(tmp_path)

    c.save()


def redact_pdf(
    input_path: str, output_path: str, grammars: list[Grammar], dpi: int = 300
) -> int:
    """
    Redact a PDF file.

    Returns the total number of redactions made.
    """
    doc = fitz.open(input_path)
    images: list[Image.Image] = []
    total_redactions = 0

    for page in doc:
        img = render_page(page, dpi)
        redacted, count = redact_image(img, grammars)
        images.append(redacted)
        total_redactions += count

    doc.close()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    images_to_pdf(images, output_path, dpi)

    return total_redactions


def scan_pdf(input_path: str, grammars: list[Grammar], dpi: int = 300) -> int:
    """
    Scan a PDF for pattern matches without redacting.

    Returns the number of matches found (used for verification).
    """
    doc = fitz.open(input_path)
    total_matches = 0

    for page in doc:
        img = render_page(page, dpi)
        words = ocr_page(img)
        if not words:
            continue

        stream = build_stream(words)
        matched = find_matches(stream, grammars)
        if matched:
            groups = group_adjacent_words(matched, words)
            total_matches += len(groups)

    doc.close()
    return total_matches


# =============================================================================
# Parallel Processing
# =============================================================================


def _process_single_pdf(args: tuple[str, str, list[str], int, bool]) -> JobResult:
    """
    Worker function for parallel PDF processing.

    Takes a tuple of (input_path, output_path, patterns, dpi, verify).
    Compiles grammars in this process since Grammar objects can't be pickled.

    If no matches are found at the initial DPI, retries at 2x DPI.
    """
    input_path, output_path, patterns, dpi, verify = args

    # Compile grammars in this worker process
    grammars = compile_grammars(patterns)

    # First attempt at base DPI
    redactions = redact_pdf(input_path, output_path, grammars, dpi)
    retried_dpi = None

    # Retry at higher DPI if no matches found
    if redactions == 0:
        retried_dpi = dpi * 2
        redactions = redact_pdf(input_path, output_path, grammars, retried_dpi)

    # Determine error code
    error_code = EXIT_SUCCESS
    leaked = 0

    if redactions == 0:
        error_code = EXIT_NO_MATCHES
    elif verify:
        final_dpi = retried_dpi if retried_dpi else dpi
        leaked = scan_pdf(output_path, grammars, final_dpi)
        if leaked > 0:
            error_code = EXIT_VERIFICATION_FAILED

    return JobResult(
        input_path=input_path,
        output_path=output_path,
        redactions=redactions,
        leaked=leaked,
        error_code=error_code,
        retried_dpi=retried_dpi,
    )


def get_worker_count(jobs_arg: int | None, num_jobs: int) -> int:
    """
    Determine number of workers.

    Default: half the CPU count.
    Clamped to: at least 1, at most the number of jobs.
    """
    cpu_count = os.cpu_count() or 1

    if jobs_arg is None:
        # Default: half the cores
        workers = max(1, cpu_count // 2)
    else:
        workers = jobs_arg

    # Clamp to reasonable bounds
    return max(1, min(workers, num_jobs, cpu_count))


# =============================================================================
# Configuration
# =============================================================================


def find_config(cli_path: str | None = None) -> str | None:
    """
    Find config file in order of precedence:
    1. CLI argument
    2. BLEACHPDF_CONFIG environment variable
    3. ./pii.yaml (current directory)
    4. ~/.config/bleachpdf/pii.yaml (user config)
    5. /etc/xdg/bleachpdf/pii.yaml (site config)
    """
    candidates: list[str] = []

    if cli_path:
        candidates.append(cli_path)

    env_path = os.environ.get("BLEACHPDF_CONFIG")
    if env_path:
        candidates.append(env_path)

    candidates.append(os.path.join(os.getcwd(), CONFIG_FILENAME))
    candidates.append(os.path.join(user_config_dir(APP_NAME), CONFIG_FILENAME))
    candidates.append(os.path.join(site_config_dir(APP_NAME), CONFIG_FILENAME))

    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def load_patterns(path: str) -> list[str]:
    """Load pattern strings from a YAML config file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return [str(p) for p in config.get("patterns", [])]


# =============================================================================
# CLI
# =============================================================================


def resolve_output(input_path: str, output_arg: str | None, base_dir: str | None = None) -> str:
    """
    Determine output path for a given input.

    If output_arg ends with / or is an existing directory, treat as directory.
    Otherwise treat as file path (only valid for single input).
    """
    if output_arg is None:
        output_arg = "output/"

    is_dir = output_arg.endswith("/") or os.path.isdir(output_arg)

    if is_dir:
        if base_dir:
            rel_path = os.path.relpath(input_path, base_dir)
            return os.path.join(output_arg, rel_path)
        else:
            return os.path.join(output_arg, os.path.basename(input_path))
    else:
        return output_arg


def collect_inputs(args: list[str]) -> list[tuple[str, str | None]]:
    """
    Collect PDF files from input arguments.

    Returns list of (input_path, base_dir) tuples.
    """
    jobs: list[tuple[str, str | None]] = []

    for arg in args:
        if "*" in arg or "?" in arg:
            for p in glob.glob(arg, recursive=True):
                if p.endswith(".pdf"):
                    jobs.append((p, None))
        elif os.path.isdir(arg):
            for p in glob.glob(f"{arg}/**/*.pdf", recursive=True):
                jobs.append((p, arg))
        elif arg.endswith(".pdf"):
            jobs.append((arg, None))
        else:
            log.warning("Skipping non-PDF file: %s", arg)

    return jobs


def setup_logging(*, quiet: bool = False, verbose: bool = False) -> None:
    """Configure logging based on CLI flags."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(level)


class HelpOnErrorParser(argparse.ArgumentParser):
    """ArgumentParser that prints full help on error."""

    def error(self, message: str) -> NoReturn:
        self.print_help(sys.stderr)
        sys.stderr.write(f"\nerror: {message}\n")
        sys.exit(2)


def main() -> None:
    parser = HelpOnErrorParser(
        prog="bleachpdf",
        description="Redact PII from PDF documents using OCR and PEG pattern matching.",
        epilog="""
Examples:
  bleachpdf document.pdf
  bleachpdf document.pdf -o redacted.pdf
  bleachpdf data/ -o output/
  bleachpdf "docs/**/*.pdf" -o output/

Config file lookup order:
  1. -c/--config argument
  2. $BLEACHPDF_CONFIG environment variable
  3. ./pii.yaml (current directory)
  4. ~/.config/bleachpdf/pii.yaml
  5. /etc/xdg/bleachpdf/pii.yaml
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="PDF file(s), directory, or glob pattern",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help="output file (single input) or directory (default: output/)",
    )
    parser.add_argument(
        "-m",
        "--match",
        action="append",
        metavar="TEXT",
        dest="matches",
        help="literal text to redact (case-insensitive, repeatable)",
    )
    parser.add_argument(
        "-c",
        "--config",
        metavar="CONFIG",
        help="path to config file (default: pii.yaml)",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        metavar="N",
        help="number of parallel workers (default: half of CPU cores)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress output",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show processing progress",
    )
    parser.add_argument(
        "-d",
        "--dpi",
        type=int,
        default=300,
        metavar="DPI",
        help="resolution for rendering and output (default: 300)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip re-scanning output to verify redaction (faster but less safe)",
    )
    parser.add_argument(
        "--relaxed",
        action="store_true",
        help="don't fail if no matches found (default: strict mode fails with exit code 3)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()
    setup_logging(quiet=args.quiet, verbose=args.verbose)

    # Build patterns from CLI -m arguments
    patterns: list[str] = []
    if args.matches:
        for text in args.matches:
            # Escape special regex chars in the literal text
            escaped = re.escape(text)
            patterns.append(f'match = ~"{escaped}"i')
        log.debug("CLI patterns: %d", len(patterns))

    # Load patterns from config file (optional if -m provided)
    config_path = find_config(args.config)
    if config_path:
        log.info("Using config: %s", config_path)
        config_patterns = load_patterns(config_path)
        patterns.extend(config_patterns)
    elif not patterns:
        # No -m and no config file
        locations = [
            "./pii.yaml",
            os.path.join(user_config_dir(APP_NAME), CONFIG_FILENAME),
            os.path.join(site_config_dir(APP_NAME), CONFIG_FILENAME),
        ]
        log.error("No config file found. Searched:")
        for loc in locations:
            log.error("  %s", loc)
        log.error("")
        log.error("Use -m to specify patterns or -c to specify a config file.")
        sys.exit(EXIT_CONFIG_ERROR)

    if not patterns:
        log.error("No patterns defined. Use -m or add patterns to config file.")
        sys.exit(EXIT_CONFIG_ERROR)

    # Validate patterns by compiling in main process
    grammars = compile_grammars(patterns)
    if not grammars:
        log.error("No valid patterns after compilation.")
        sys.exit(1)

    # Collect input files
    jobs = collect_inputs(args.inputs)
    if not jobs:
        log.error("No PDF files found.")
        sys.exit(1)

    # Validate output for multiple inputs
    if len(jobs) > 1 and args.output:
        is_dir = args.output.endswith("/") or os.path.isdir(args.output)
        if not is_dir:
            log.error(
                "Cannot output %d files to single file '%s'.\n"
                "Use a directory (with trailing /) for multiple inputs.",
                len(jobs),
                args.output,
            )
            sys.exit(1)

    # Build job arguments
    job_args: list[tuple[str, str, list[str], int, bool]] = []
    for input_path, base_dir in jobs:
        output_path = resolve_output(input_path, args.output, base_dir)
        job_args.append((input_path, output_path, patterns, args.dpi, not args.no_verify))

    # Determine parallelism
    num_workers = get_worker_count(args.jobs, len(jobs))

    # Limit Tesseract's internal threading to avoid oversubscription
    os.environ["OMP_THREAD_LIMIT"] = "1"

    log.debug("Processing %d file(s) with %d worker(s)", len(jobs), num_workers)

    # Process files
    verification_failures: list[tuple[str, int]] = []
    no_match_failures: list[str] = []

    def handle_result(result: JobResult) -> None:
        """Process a single result, logging and tracking failures."""
        # Log redaction info
        if result.retried_dpi:
            log.info(
                "%s -> %s (%d redactions, retried at %d DPI)",
                result.input_path, result.output_path, result.redactions, result.retried_dpi,
            )
        else:
            log.info("%s -> %s (%d redactions)", result.input_path, result.output_path, result.redactions)

        # Track failures
        if result.error_code == EXIT_NO_MATCHES:
            log.warning("NO MATCHES: %s", result.input_path)
            no_match_failures.append(result.input_path)
        elif result.error_code == EXIT_VERIFICATION_FAILED:
            log.error("VERIFY FAILED: %s still has %d matches", result.output_path, result.leaked)
            verification_failures.append((result.output_path, result.leaked))
        elif not args.no_verify and result.redactions > 0:
            log.info("VERIFY OK: %s", result.output_path)

    if num_workers == 1:
        # Sequential processing (no subprocess overhead)
        for job in job_args:
            result = _process_single_pdf(job)
            handle_result(result)
    else:
        # Parallel processing
        with ProcessPoolExecutor(max_workers=num_workers) as pool:
            for result in pool.map(_process_single_pdf, job_args):
                handle_result(result)

    # Report and exit with appropriate code
    exit_code = EXIT_SUCCESS

    if verification_failures:
        log.error("")
        log.error("Verification failed for %d file(s):", len(verification_failures))
        for path, count in verification_failures:
            log.error("  %s (%d matches)", path, count)
        exit_code = EXIT_VERIFICATION_FAILED

    if no_match_failures:
        log.warning("")
        log.warning("No matches found in %d file(s):", len(no_match_failures))
        for path in no_match_failures:
            log.warning("  %s", path)
        if not args.relaxed and exit_code == EXIT_SUCCESS:
            exit_code = EXIT_NO_MATCHES

    if exit_code != EXIT_SUCCESS:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
