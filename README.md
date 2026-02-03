# bleachpdf

PII redaction tool for PDF documents. Uses OCR to find text, then matches against PEG grammar patterns defined in a YAML config file and draws black boxes over matches.

**Works on both scanned documents and text-based PDFs.** Because it uses OCR rather than PDF text extraction, it handles scanned bank statements, faxed documents, and image-based PDFs just as well as native digital documents.

## Why This Tool?

Most PII redaction tools use NLP/ML models (spaCy, Microsoft Presidio, OpenAI) to detect entities like "any SSN" or "any phone number." That approach works for generic detection but can miss unusual formats or produce false positives. Many also only work on text-layer PDFs, failing on scanned documents.

This tool takes a different approach: **you define exact patterns using PEG grammars**. This is ideal when you know the specific values you need to redact—your own SSN, specific account numbers, known identifiers—rather than trying to detect "anything that looks like an SSN."

| Approach | Best For |
|----------|----------|
| ML/NLP (Presidio, etc.) | Unknown documents, generic PII detection |
| Text-layer tools | Native digital PDFs only |
| **PEG + OCR (this tool)** | Known values, scanned docs, precise control |

## How It Works

1. **PDF to Image**: Each PDF page is rendered at configurable DPI (default 300) using PyMuPDF
2. **OCR**: Tesseract extracts words with bounding box coordinates
3. **Normalization**: Text is stripped of non-alphanumeric characters for matching
4. **Pattern Matching**: PEG grammars match against the normalized text stream
5. **Redaction**: Black rectangles are drawn over matched words
6. **Reassembly**: Redacted images are combined back into a PDF

## Requirements

- Python 3.9+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system

## Installation

```bash
# Install Tesseract (Ubuntu/Debian)
sudo apt install tesseract-ocr

# Install Tesseract (macOS)
brew install tesseract

# Install bleachpdf
pip install bleachpdf

# Or install from source
pip install -e .
```

## Configuration

Create a config file with your PII patterns. The tool searches for config in this order:

1. `-c/--config` command line argument
2. `$BLEACHPDF_CONFIG` environment variable
3. `./pii.yaml` (current directory)
4. `~/.config/bleachpdf/pii.yaml` (user config)
5. `/etc/xdg/bleachpdf/pii.yaml` (system config)

Copy the example config to get started:

```bash
cp pii.example.yaml pii.yaml
```

### Pattern Examples

Each pattern is a [PEG grammar](https://github.com/erikrose/parsimonious) with `match` as the entry point:

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

Before matching, all text is normalized by removing non-alphanumeric characters:
- `123-45-6789` becomes `123456789`
- `John Doe` becomes `JohnDoe`
- `ACCT#12345` becomes `ACCT12345`

Your patterns should match against the normalized form.

## Usage

```bash
# Single file (output to output/document.pdf)
bleachpdf document.pdf

# Single file with specific output
bleachpdf document.pdf -o redacted.pdf

# Single file to output directory
bleachpdf document.pdf -o out/

# Directory (recursive, preserves structure)
bleachpdf data/ -o output/

# Glob pattern (quote to prevent shell expansion)
bleachpdf "docs/**/*.pdf" -o output/

# Specify config file
bleachpdf -c mypatterns.yaml document.pdf

# Quiet mode
bleachpdf -q document.pdf

# Verbose mode (shows matched patterns)
bleachpdf -v document.pdf
```

### Options

| Option | Description |
|--------|-------------|
| `-o, --output` | Output file or directory (default: `output/`) |
| `-c, --config` | Path to config file |
| `-d, --dpi` | Resolution for rendering and output (default: 300) |
| `-q, --quiet` | Suppress output |
| `-v, --verbose` | Show matched patterns |
| `-h, --help` | Show help |

### Output Behavior

| Inputs | `-o` value | Result |
|--------|------------|--------|
| Single file | (none) | `output/<filename>.pdf` |
| Single file | `redacted.pdf` | `redacted.pdf` |
| Single file | `out/` | `out/<filename>.pdf` |
| Multiple files | (none) | `output/` preserving structure |
| Multiple files | `out/` | `out/` preserving structure |
| Multiple files | `single.pdf` | **Error** |

## Dependencies

- **pytesseract**: Python wrapper for Tesseract OCR
- **Pillow**: Image processing
- **PyMuPDF**: PDF reading and rendering
- **reportlab**: PDF generation
- **PyYAML**: Config file parsing
- **parsimonious**: PEG grammar parsing
- **platformdirs**: Cross-platform config directory support
