#!/usr/bin/env python3
"""
bleachpdf - PII redaction for PDF documents.

Uses OCR to find text, then matches against PEG grammar patterns
defined in a YAML config file and draws black boxes over matches.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import sys
import tempfile
from typing import TYPE_CHECKING

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

log = logging.getLogger(APP_NAME)


# --- Types ---

WordInfo = dict[str, str | int]


# --- Config ---


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


def load_config(path: str) -> list[str]:
    """Load patterns from YAML config file."""
    with open(path) as f:
        config = yaml.safe_load(f)
    return [str(p) for p in config.get("patterns", [])]


# --- OCR ---


def ocr_page(img: Image.Image) -> list[WordInfo]:
    """OCR image, return list of {text, left, top, width, height}."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    words: list[WordInfo] = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if text:
            words.append(
                {
                    "text": text,
                    "left": data["left"][i],
                    "top": data["top"][i],
                    "width": max(1, data["width"][i]),
                    "height": max(1, data["height"][i]),
                }
            )
    return words


# --- Pattern Matching ---


def normalize(text: str) -> str:
    """Strip everything except alphanumeric."""
    return re.sub(r"[^A-Za-z0-9]", "", text)


def build_text_stream(words: list[WordInfo]) -> tuple[str, list[int]]:
    """
    Concatenate normalized words into a stream.
    Returns (stream, mappings) where mappings[char_index] = word_index.
    """
    stream = ""
    mappings: list[int] = []
    for i, w in enumerate(words):
        norm = normalize(str(w["text"]))
        for _ in norm:
            mappings.append(i)
        stream += norm
    return stream, mappings


def find_matches(stream: str, mappings: list[int], patterns: list[str]) -> set[int]:
    """Find all pattern matches, return set of word indices."""
    matched_words: set[int] = set()
    for pattern in patterns:
        try:
            grammar = Grammar(pattern)
        except Exception as e:
            log.warning("Invalid grammar: %s (%s)", pattern, e)
            continue

        for start in range(len(stream)):
            try:
                node: Node | None = grammar.match(stream, start)
                if node:
                    log.debug("Matched: %s", node.text)
                    for i in range(start, start + len(node.text)):
                        if i < len(mappings):
                            matched_words.add(mappings[i])
            except Exception:
                pass
    return matched_words


# --- Redaction ---


def group_adjacent_words(matched_indices: set[int], words: list[WordInfo]) -> list[list[int]]:
    """Group matched word indices that are on the same line and adjacent."""
    if not matched_indices:
        return []

    sorted_indices = sorted(matched_indices)
    groups: list[list[int]] = []
    current_group = [sorted_indices[0]]

    for idx in sorted_indices[1:]:
        prev_idx = current_group[-1]
        prev_w = words[prev_idx]
        curr_w = words[idx]
        prev_top = int(prev_w["top"])
        curr_top = int(curr_w["top"])
        prev_height = int(prev_w["height"])
        prev_left = int(prev_w["left"])
        prev_width = int(prev_w["width"])
        curr_left = int(curr_w["left"])

        same_line = abs(prev_top - curr_top) < prev_height * 1.5
        close = idx == prev_idx + 1 or (curr_left - (prev_left + prev_width) < 50)

        if same_line and close:
            current_group.append(idx)
        else:
            groups.append(current_group)
            current_group = [idx]

    groups.append(current_group)
    return groups


def words_to_box(
    words: list[WordInfo], indices: list[int], img_w: int, img_h: int, pad: int = 4
) -> tuple[int, int, int, int] | None:
    """Compute bounding box for a set of word indices."""
    ws = [words[i] for i in indices]
    if not ws:
        return None
    left = min(int(w["left"]) for w in ws) - pad
    top = min(int(w["top"]) for w in ws) - pad
    right = max(int(w["left"]) + int(w["width"]) for w in ws) + pad
    bottom = max(int(w["top"]) + int(w["height"]) for w in ws) + pad
    return (
        max(0, left),
        max(0, top),
        min(img_w, right),
        min(img_h, bottom),
    )


def redact_page(img: Image.Image, patterns: list[str]) -> tuple[Image.Image, int]:
    """Redact a single page image. Returns (redacted_image, num_redactions)."""
    img = img.copy()
    w, h = img.size

    words = ocr_page(img)
    if not words:
        return img, 0

    stream, mappings = build_text_stream(words)
    matched = find_matches(stream, mappings, patterns)

    if not matched:
        return img, 0

    groups = group_adjacent_words(matched, words)

    draw = ImageDraw.Draw(img)
    for group in groups:
        box = words_to_box(words, group, w, h)
        if box:
            draw.rectangle(box, fill="black")

    return img, len(groups)


# --- PDF I/O ---


def images_to_pdf(images: list[Image.Image], output_path: str, dpi: int = 300) -> None:
    """Convert images to PDF at specified DPI."""
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


def redact_pdf(input_path: str, output_path: str, patterns: list[str], dpi: int = 300) -> int:
    """Redact a PDF file. Returns total redaction count."""
    doc = fitz.open(input_path)
    images: list[Image.Image] = []
    total_redactions = 0

    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        redacted, count = redact_page(img, patterns)
        images.append(redacted)
        total_redactions += count

    doc.close()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    images_to_pdf(images, output_path, dpi=dpi)

    log.info("%s -> %s (%d redactions)", input_path, output_path, total_redactions)

    return total_redactions


# --- CLI ---


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

    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
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
        "-c",
        "--config",
        metavar="CONFIG",
        help="path to config file (default: pii.yaml)",
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
        help="show matched patterns",
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
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    args = parser.parse_args()

    setup_logging(quiet=args.quiet, verbose=args.verbose)

    # Find and load config
    config_path = find_config(args.config)
    if not config_path:
        locations = [
            "./pii.yaml",
            os.path.join(user_config_dir(APP_NAME), CONFIG_FILENAME),
            os.path.join(site_config_dir(APP_NAME), CONFIG_FILENAME),
        ]
        log.error("No config file found. Searched:")
        for loc in locations:
            log.error("  %s", loc)
        log.error("")
        log.error("Set $BLEACHPDF_CONFIG or use -c to specify a config file.")
        sys.exit(1)

    log.info("Using config: %s", config_path)

    patterns = load_config(config_path)
    if not patterns:
        log.error("No patterns defined in config file.")
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

    # Process files
    for input_path, base_dir in jobs:
        output_path = resolve_output(input_path, args.output, base_dir)
        redact_pdf(input_path, output_path, patterns, dpi=args.dpi)


if __name__ == "__main__":
    main()
