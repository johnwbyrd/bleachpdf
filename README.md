# bleachpdf

A tool that blacks out sensitive information in PDF files.

## What Does This Do?

You have a PDF with your Social Security number, bank account numbers, or home address. You need to share it, but you want that private stuff hidden first. This tool finds the sensitive text and covers it with black boxes.

## Important: Always Verify Your Results

No automated redaction system is perfect.  By Rice's theorem, none ever can be.

This tool does a reasonable job with vector PDFs and high-quality scans of printed material. It does less well with handwriting and poor-quality scans. OCR makes mistakes. Patterns can miss edge cases. Unusual fonts or layouts can confuse the text recognition.

**You should manually check every redacted document before sharing it.** Open the output file, look at each page, and verify that:

- All sensitive information is actually covered
- No extra text was accidentally redacted
- Nothing slipped through

Never trust this tool -- or *ANY* automated redaction tool -- to do a perfect job for you. Treat it as a helpful first pass, not a replacement for human review.

## Why Use This Instead of Adobe Acrobat?

**It's free and open source.** You can read every line of code. No subscription, no account, no uploading your sensitive documents to someone else's server. Everything runs on your computer and stays there.

**It works on scanned documents.** Most redaction tools read the text embedded inside a PDF file. That works fine for PDFs created digitally, but fails completely on scanned documents, faxes, or PDFs that are really just pictures of pages.

This tool takes a different approach: it treats every PDF like a scanned document. It converts each page to an image, reads the text using optical character recognition (OCR), finds your sensitive information, draws black boxes over it, and saves a new PDF. The original text layer is ignored entirely, so nothing slips through.

The output is a clean PDF containing only images. There's no hidden text layer that could accidentally leak your information.

## How It Works

1. Each page becomes an image
2. OCR reads the words and their positions
3. Your patterns are matched against the text
4. Black boxes cover the matches
5. A new PDF is created from the redacted images
6. The output is scanned again to make sure nothing was missed

## Requirements

- Python 3.9 or newer
- Tesseract, the OCR engine (this does the actual text recognition)

## Installation

First, install Tesseract on your system:

```bash
# On Ubuntu or Debian
sudo apt install tesseract-ocr

# On macOS
brew install tesseract
```

Then install bleachpdf:

```bash
pip install bleachpdf
```

## Setting Up Your Patterns

You need to tell the tool what to look for. Create a file(redactor) jbyrd@dev03:~/git/redactor$ python -m pytest tests/ --limit=100
============================================== test session starts ==============================================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/jbyrd/git/redactor
configfile: pyproject.toml
plugins: anyio-4.12.1
collected 1 item                                                                                                

tests/test_redaction.(redactor) jbyrd@dev03:~/git/redactor$ python -m pytest tests/ --limit=100
============================================== test session starts ==============================================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/jbyrd/git/redactor
configfile: pyproject.toml
plugins: anyio-4.12.1
collected 1 item                                                                                                

tests/test_redaction.py .                                                                                 [100%]
======================================================================
REDACTION TEST SUMMARY
======================================================================
  Passed:  100
  Failed:  0
  Total:   100
  Pass rate: 100.0%

  Redaction breakdown:
    With redactions:    0
    Zero redactions:    0  (suspicious - OCR may have failed)
    Absent-type tests:  100  (0 redactions expected)
======================================================================
py .                                                                                 [100%]
======================================================================
REDACTION TEST SUMMARY
======================================================================
  Passed:  100
  Failed:  0
  Total:   100
  Pass rate: 100.0%

  Redaction breakdown:
    With redactions:    0
    Zero redactions:    0  (suspicious - OCR may have failed)
    Absent-type tests:  100  (0 redactions expected)
======================================================================
 called `pii.yaml` in the folder where you'll run the command. There's an example file to get you started:

```bash
cp pii.example.yaml pii.yaml
```

Then edit `pii.yaml` to add your own sensitive values.

### Writing Patterns

The simplest pattern is just the exact text you want to redact:

```yaml
patterns:
  # Your Social Security number (without dashes)
  - 'match = "123456789"'

  # Your name
  - 'match = ~"(?i)johndoe"'

  # Last 4 digits of an account
  - 'match = "1234"'
```

The `(?i)` makes a pattern case-insensitive, so it matches "JohnDoe", "johndoe", "JOHNDOE", etc.

### About Spaces and Punctuation

Before matching, the tool removes all spaces, dashes, and(redactor) jbyrd@dev03:~/git/redactor$ python -m pytest tests/ --limit=100
============================================== test session starts ==============================================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0
rootdir: /home/jbyrd/git/redactor
configfile: pyproject.toml
plugins: anyio-4.12.1
collected 1 item                                                                                                

tests/test_redaction.py .                                                                                 [100%]
======================================================================
REDACTION TEST SUMMARY
======================================================================
  Passed:  100
  Failed:  0
  Total:   100
  Pass rate: 100.0%

  Redaction breakdown:
    With redactions:    0
    Zero redactions:    0  (suspicious - OCR may have failed)
    Absent-type tests:  100  (0 redactions expected)
======================================================================
 punctuation from the text. So if your document shows `123-45-6789`, the tool sees `123456789`. If it shows `John Doe`, the tool sees `JohnDoe`.

Write your patterns without spaces or punctuation:

| Document shows | Pattern should be |
|----------------|-------------------|
| `123-45-6789` | `"123456789"` |
| `John Doe` | `~"(?i)johndoe"` |
| `ACCT #12345` | `"ACCT12345"` |

### Advanced Patterns

For more complex matching, the tool uses a pattern language called PEG (Parsing Expression Grammar). Here's an example that matches any 9-digit number:

```yaml
patterns:
  - |
    match = d d d d d d d d d
    d = ~"[0-9]"
```

This says "match nine digits in a row" where `d` means any digit 0-9.

### Where the Config File Can Live

The tool looks for your config file in several places, in this order:

1. The path you specify with `-c` or `--config`
2. The `BLEACHPDF_CONFIG` environment variable
3. `pii.yaml` in the current folder
4. `~/.config/bleachpdf/pii.yaml` (your personal config)
5. `/etc/xdg/bleachpdf/pii.yaml` (system-wide config)

## Usage

The basic command is:

```bash
bleachpdf document.pdf
```

This creates a redacted version in the `output/` folder.

### More Examples

```bash
# Save to a specific file
bleachpdf document.pdf -o redacted.pdf

# Save to a specific folder
bleachpdf document.pdf -o redacted/

# Process a whole folder of PDFs
bleachpdf documents/ -o redacted/

# Process multiple files matching a pattern
bleachpdf "reports/*.pdf" -o redacted/

# Use a specific config file
bleachpdf document.pdf -c my-patterns.yaml

# See what's happening
bleachpdf document.pdf -v
```

### Options

| Option | What it does |
|--------|--------------|
| `-o, --output` | Where to save the result (default: `output/`) |
| `-c, --config` | Use a specific config file |
| `-j, --jobs N` | Process multiple files at once (default: half your CPU cores) |
| `-d, --dpi` | Image quality, higher is sharper but slower (default: 300) |
| `--no-verify` | Skip the safety check that re-scans the output |
| `-q, --quiet` | Don't print anything |
| `-v, --verbose` | Print more details |
| `-h, --help` | Show help |

### The Safety Check

After redacting, the tool scans the output file again to make sure nothing was missed. If it still finds matches, something went wrong and it will warn you.

This takes extra time. If you're confident in your patterns and want faster processing, you can skip it with `--no-verify`.

### Processing Multiple Files

When you have many files to redact, the tool processes them in parallel to save time. By default it uses half of your CPU cores. You can change this:

```bash
# Use 4 parallel workers
bleachpdf documents/ -j 4

# Process one file at a time (slower but uses less memory)
bleachpdf documents/ -j 1
```

## What's Under the Hood

These Python libraries do the heavy lifting (installed automatically):

- **pytesseract** — talks to Tesseract for text recognition
- **Pillow** — handles image manipulation
- **PyMuPDF** — converts PDF pages to images
- **reportlab** — creates the output PDF
- **PyYAML** — reads the config file
- **parsimonious** — matches patterns against text
- **platformdirs** — finds the right config folder on your system
