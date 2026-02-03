#!/usr/bin/env python3
"""
PII redaction for PDF documents.

Uses OCR to find text, then matches against patterns defined in pii.yaml.
Patterns can be literal strings or PEG grammars (if they contain '=').
"""

import os
import re
import pytesseract
import yaml
from PIL import Image, ImageDraw
from parsimonious.grammar import Grammar


def load_config(config_path=None):
    """Load patterns from YAML config file."""
    if config_path is None:
        config_path = os.path.join(os.path.dirname(__file__), "pii.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config not found: {config_path}\n"
            "Copy pii.example.yaml to pii.yaml and fill in your values."
        )

    with open(config_path) as f:
        return yaml.safe_load(f)


_config = load_config()
PATTERNS = [str(p) for p in _config.get("patterns", [])]


def ocr_page(img):
    """OCR image, return list of {text, left, top, width, height}."""
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    words = []
    for i in range(len(data["text"])):
        text = data["text"][i].strip()
        if text:
            words.append({
                "text": text,
                "left": data["left"][i],
                "top": data["top"][i],
                "width": max(1, data["width"][i]),
                "height": max(1, data["height"][i]),
            })
    return words


def normalize(text):
    """Strip everything except alphanumeric."""
    return re.sub(r"[^A-Za-z0-9]", "", text)


def build_text_stream(words):
    """
    Concatenate normalized words into a stream.
    Returns (stream, mappings) where mappings[char_index] = word_index.
    """
    stream = ""
    mappings = []
    for i, w in enumerate(words):
        norm = normalize(w["text"])
        for _ in norm:
            mappings.append(i)
        stream += norm
    return stream, mappings


def find_matches(stream, mappings, patterns):
    """Find all pattern matches, return set of word indices."""
    matched_words = set()
    for pattern in patterns:
        try:
            grammar = Grammar(pattern)
        except Exception as e:
            print(f"Warning: invalid grammar: {pattern} ({e})")
            continue

        for start in range(len(stream)):
            try:
                node = grammar.match(stream, start)
                if node:
                    for i in range(start, start + len(node.text)):
                        if i < len(mappings):
                            matched_words.add(mappings[i])
            except:
                pass  # No match at this position
    return matched_words


def words_to_box(words, indices, img_w, img_h, pad=4):
    """Compute bounding box for a set of word indices."""
    ws = [words[i] for i in indices]
    if not ws:
        return None
    left = min(w["left"] for w in ws) - pad
    top = min(w["top"] for w in ws) - pad
    right = max(w["left"] + w["width"] for w in ws) + pad
    bottom = max(w["top"] + w["height"] for w in ws) + pad
    return (
        max(0, left),
        max(0, top),
        min(img_w, right),
        min(img_h, bottom),
    )


def group_adjacent_words(matched_indices, words):
    """Group matched word indices that are on the same line and adjacent."""
    if not matched_indices:
        return []

    sorted_indices = sorted(matched_indices)
    groups = []
    current_group = [sorted_indices[0]]

    for idx in sorted_indices[1:]:
        prev_idx = current_group[-1]
        prev_w = words[prev_idx]
        curr_w = words[idx]
        same_line = abs(prev_w["top"] - curr_w["top"]) < prev_w["height"] * 1.5
        close = idx == prev_idx + 1 or (
            curr_w["left"] - (prev_w["left"] + prev_w["width"]) < 50
        )
        if same_line and close:
            current_group.append(idx)
        else:
            groups.append(current_group)
            current_group = [idx]

    groups.append(current_group)
    return groups


def redact_page(img):
    """Main entry: takes PIL Image, returns (redacted_image, num_redactions)."""
    img = img.copy()
    w, h = img.size

    words = ocr_page(img)
    if not words:
        return img, 0

    stream, mappings = build_text_stream(words)
    matched = find_matches(stream, mappings, PATTERNS)

    if not matched:
        return img, 0

    groups = group_adjacent_words(matched, words)

    draw = ImageDraw.Draw(img)
    for group in groups:
        box = words_to_box(words, group, w, h)
        if box:
            draw.rectangle([int(c) for c in box], fill="black")

    return img, len(groups)


def redact_pdf(input_path, output_path=None, output_dir="output", base_dir=None):
    """Redact a PDF file. Returns (output_path, total_redactions)."""
    import fitz
    from assembler import images_to_pdf

    if output_path is None:
        if base_dir:
            rel_path = os.path.relpath(input_path, base_dir)
            output_path = os.path.join(output_dir, rel_path)
        else:
            output_path = os.path.join(output_dir, os.path.basename(input_path))
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    doc = fitz.open(input_path)
    images = []
    total_redactions = 0

    for page in doc:
        pix = page.get_pixmap(dpi=300)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        redacted, count = redact_page(img)
        images.append(redacted)
        total_redactions += count

    doc.close()
    images_to_pdf(images, output_path)
    return output_path, total_redactions


if __name__ == "__main__":
    import sys
    import glob

    if len(sys.argv) < 2:
        print("Usage: python redactor.py <file.pdf|directory|glob> [...]")
        sys.exit(1)

    jobs = []
    for arg in sys.argv[1:]:
        if "*" in arg:
            for p in glob.glob(arg):
                jobs.append((p, None))
        elif arg.endswith(".pdf"):
            jobs.append((arg, None))
        else:
            for p in glob.glob(f"{arg}/**/*.pdf", recursive=True):
                jobs.append((p, arg))

    if not jobs:
        print("No PDF files found.")
        sys.exit(1)

    for path, base_dir in jobs:
        print(f"Processing {path}...")
        output, count = redact_pdf(path, base_dir=base_dir)
        print(f"  -> {output} ({count} redactions)")
