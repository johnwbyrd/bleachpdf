# Redactor

PII redaction tool for PDF documents. Uses OCR to find text, then matches against patterns defined in a YAML config file and draws black boxes over matches.

## Why This Tool?

Most PII redaction tools use NLP/ML models (spaCy, Microsoft Presidio, OpenAI) to detect entities like "any SSN" or "any phone number." That approach works for generic detection but can miss unusual formats or produce false positives.

This tool takes a different approach: **you define exact patterns using PEG grammars**. This is ideal when you know the specific values you need to redact—your own SSN, specific account numbers, known identifiers—rather than trying to detect "anything that looks like an SSN."

| Approach | Best For |
|----------|----------|
| ML/NLP (Presidio, etc.) | Unknown documents, generic PII detection |
| PEG patterns (this tool) | Known values, specific identifiers, precise control |

## How It Works

1. **PDF to Image**: Each PDF page is rendered at 300 DPI using PyMuPDF
2. **OCR**: Tesseract extracts words with bounding box coordinates
3. **Normalization**: Text is stripped of non-alphanumeric characters for matching
4. **Pattern Matching**: PEG grammars match against the normalized text stream
5. **Redaction**: Black rectangles are drawn over matched words
6. **Reassembly**: Redacted images are combined back into a PDF at 300 DPI

## Requirements

- Python 3.9+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system

## Installation

```bash
# Install Tesseract (Ubuntu/Debian)
sudo apt install tesseract-ocr

# Install Tesseract (macOS)
brew install tesseract

# Install Python dependencies
uv sync
# or
pip install -e .
```

## Configuration

Copy the example config and add your patterns:

```bash
cp pii.example.yaml pii.yaml
```

Edit `pii.yaml` to define patterns to redact. Each pattern is a [PEG grammar](https://github.com/erikrose/parsimonious) with `match` as the entry point.

**Important**: `pii.yaml` is gitignored to prevent accidentally committing sensitive patterns.

### Pattern Examples

```yaml
patterns:
  # Literal match - exact string (after normalization)
  - 'match = "123456789"'

  # SSN pattern - 9 consecutive digits
  - |
    match = d d d d d d d d d
    d = ~"[0-9]"

  # Account number with prefix
  - |
    match = "ACCT" d d d d d d
    d = ~"[0-9]"

  # Case-insensitive match using regex
  - 'match = ~"[Jj][Oo][Hh][Nn][Dd][Oo][Ee]"'

  # Partial match - last 4 digits of known number
  - 'match = "1234"'
```

### Text Normalization

Before matching, all text is normalized by removing non-alphanumeric characters. This means:
- `123-45-6789` becomes `123456789`
- `John Doe` becomes `JohnDoe`
- `ACCT#12345` becomes `ACCT12345`

Your patterns should match against the normalized form.

## Usage

```bash
# Single file
python redactor.py document.pdf

# Multiple files
python redactor.py file1.pdf file2.pdf

# Directory (recursive)
python redactor.py data/

# Glob pattern
python redactor.py "documents/*.pdf"
```

Output goes to `output/` by default, preserving directory structure:
- `data/statements/jan.pdf` → `output/statements/jan.pdf`

## Project Structure

```
redactor/
├── redactor.py       # Main redaction logic and CLI
├── assembler.py      # PDF assembly from images
├── pii.yaml          # Your patterns (gitignored)
├── pii.example.yaml  # Example patterns (committed)
├── pyproject.toml    # Project configuration
└── output/           # Redacted PDFs (gitignored)
```

## Dependencies

- **pytesseract**: Python wrapper for Tesseract OCR
- **Pillow**: Image processing
- **PyMuPDF**: PDF reading and rendering
- **reportlab**: PDF generation
- **PyYAML**: Config file parsing
- **parsimonious**: PEG grammar parsing
