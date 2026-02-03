# bleachpdf

Redact sensitive information from PDFs using OCR. Works on scanned documents.

## Quick Start

**1. Install Tesseract** (the OCR engine):

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr

# macOS
brew install tesseract
```

**2. Install bleachpdf:**

```bash
pip install bleachpdf
```

**3. Create a config file** called `pii.yaml`:

```yaml
patterns:
  - 'match = "123456789"'     # SSN (without dashes)
  - 'match = "JohnDoe"'       # Name (without spaces)
```

**4. Run it:**

```bash
bleachpdf document.pdf
```

Output goes to `output/document.pdf` with black boxes over any matches.

## Why This Tool?

**Works on scanned documents.** Most redaction tools read the text layer embedded in a PDF. That fails on scans, faxes, and image-based PDFs. This tool converts each page to an image, runs OCR, and redacts based on what it *sees* — not what's in the hidden text layer.

**No hidden text leaks.** The output is a clean image-only PDF. There's no hidden text layer that could accidentally expose your sensitive data.

**Free and local.** No subscriptions, no uploads. Everything runs on your machine.

## How It Works

1. Convert each PDF page to an image
2. Run OCR to find words and their positions
3. Match your patterns against the text
4. Draw black boxes over matches
5. Reassemble into a new PDF
6. Re-scan the output to verify nothing leaked

## Writing Patterns

Patterns use PEG (Parsing Expression Grammar) — a way to describe text patterns by composing simple rules. Patterns go in a YAML config file; the tool looks for `pii.yaml` by default.

### Literal Text

The simplest pattern matches exact text:

```yaml
patterns:
  - 'match = "123456789"'
  - 'match = "JohnDoe"'
```

For case-insensitive matching, use `~"..."i`:

```yaml
patterns:
  - 'match = ~"johndoe"i'    # matches JohnDoe, JOHNDOE, johndoe, etc.
```

**Note:** The tool normalizes text before matching — it strips spaces, dashes, and punctuation. Write patterns the same way:

| Document shows | Write as |
|----------------|----------|
| `123-45-6789` | `"123456789"` |
| `John Doe` | `~"johndoe"i` |
| `ACCT #12345` | `"ACCT12345"` |

### Building Blocks

Define reusable rules to match categories of characters:

```yaml
patterns:
  - |
    match = digit digit digit digit
    digit = "0" / "1" / "2" / "3" / "4" / "5" / "6" / "7" / "8" / "9"
```

This matches any 4-digit number. The `/` means "or" — a digit is 0 or 1 or 2... etc.

### Sequences

Rules separated by spaces match in order:

```yaml
patterns:
  - |
    match = "ACCT" digit digit digit digit
    digit = "0" / "1" / "2" / "3" / "4" / "5" / "6" / "7" / "8" / "9"
```

This matches "ACCT" followed by exactly 4 digits: `ACCT1234`, `ACCT0001`, etc.

### Repetition

Use `+` for "one or more" and `*` for "zero or more":

```yaml
patterns:
  - |
    match = letter+
    letter = "A"/"B"/"C"/"D"/"E"/"F"/"G"/"H"/"I"/"J"/"K"/"L"/"M"/"N"/"O"/"P"/"Q"/"R"/"S"/"T"/"U"/"V"/"W"/"X"/"Y"/"Z"
```

This matches any sequence of uppercase letters.

### Practical Examples

**Social Security Number** (9 digits):

```yaml
patterns:
  - |
    match = d d d d d d d d d
    d = "0"/"1"/"2"/"3"/"4"/"5"/"6"/"7"/"8"/"9"
```

**Phone Number** (10 digits):

```yaml
patterns:
  - |
    match = d d d d d d d d d d
    d = "0"/"1"/"2"/"3"/"4"/"5"/"6"/"7"/"8"/"9"
```

**Account Number** (ACCT followed by digits):

```yaml
patterns:
  - |
    match = "ACCT" d+
    d = "0"/"1"/"2"/"3"/"4"/"5"/"6"/"7"/"8"/"9"
```

**Name** (case-insensitive):

```yaml
patterns:
  - 'match = ~"johndoe"i'
  - 'match = ~"janedoe"i'
```

### Learning More

Patterns use [parsimonious](https://github.com/erikrose/parsimonious), a Python PEG parser. The README there covers the full grammar syntax including:

- Grouping with parentheses
- Optional elements with `?`
- Lookahead with `&` and `!`
- Comments in grammars

### Config File Locations

The tool searches in order:

1. `-c`/`--config` argument
2. `$BLEACHPDF_CONFIG` environment variable
3. `./pii.yaml`
4. `~/.config/bleachpdf/pii.yaml`
5. `/etc/xdg/bleachpdf/pii.yaml`

## Usage

```bash
bleachpdf document.pdf                    # Basic usage
bleachpdf document.pdf -o redacted.pdf    # Specify output file
bleachpdf documents/ -o output/           # Process a folder
bleachpdf "reports/*.pdf" -o output/      # Glob pattern
bleachpdf document.pdf -v                 # Verbose output
```

### Options

| Option | Description |
|--------|-------------|
| `-o, --output` | Output file or directory (default: `output/`) |
| `-c, --config` | Config file path |
| `-d, --dpi` | Image resolution (default: 300) |
| `-j, --jobs` | Parallel workers (default: half your CPU cores) |
| `--relaxed` | Don't fail on zero matches |
| `--no-verify` | Skip verification scan |
| `-v, --verbose` | Show progress |
| `-q, --quiet` | Suppress output |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Config error |
| 2 | File error |
| 3 | No matches found |
| 4 | Verification failed (text still visible) |

### Strict vs Relaxed Mode

By default, the tool fails (exit 3) if no matches are found. This catches mistakes: wrong document, bad pattern, OCR failure.

Use `--relaxed` when processing batches where some documents legitimately won't have matches:

```bash
bleachpdf documents/ --relaxed
```

Verification failures (exit 4) are always fatal — if text leaks through redaction, that's a hard error.

## Limitations

**OCR isn't perfect.** Handwriting, unusual fonts, low-resolution scans, and dense text can cause recognition errors. The tool retries at higher DPI if the first pass finds nothing, but some documents may still fail.

**Always verify manually.** No automated redaction is 100% reliable. Check every output before sharing:

- Is all sensitive information covered?
- Did anything slip through?
- Was anything over-redacted?

Treat this tool as a first pass, not a replacement for human review.
