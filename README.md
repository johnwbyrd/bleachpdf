# bleachpdf

A tool that blacks out sensitive information in PDF files. It works on scanned documents, not just digital ones.

## Quick Start

**1. Install Tesseract**, the text recognition engine:

```bash
# Ubuntu/Debian
sudo apt install tesseract-ocr

# macOS
brew install tesseract
```

For non-English documents, install additional language packs:

```bash
# Ubuntu/Debian (Korean, Japanese, Chinese Simplified)
sudo apt install tesseract-ocr-kor tesseract-ocr-jpn tesseract-ocr-chi-sim

# macOS
brew install tesseract-lang
```

**2. Install bleachpdf:**

```bash
pip install bleachpdf
```

**3. Run it:**

```bash
bleachpdf document.pdf -m "123456789" -m "JohnDoe"
```

This creates `output/document.pdf` with black boxes covering any text that matches "123456789" or "JohnDoe".

For more complex patterns, you can put them in a config file instead — see [Writing Patterns](#writing-patterns) below.

## Why Use This?

**It works on scanned documents.** Most redaction tools only read the text layer inside a PDF file. That works fine for documents created on a computer, but fails completely on scanned papers, faxes, or PDFs that are really just pictures of pages.

This tool takes a different approach: it converts each page to an image, uses optical character recognition to read the text, finds your sensitive information, draws black boxes over it, and saves a new PDF. The original text layer is ignored entirely, so nothing slips through.

**No hidden text can leak.** The output is a clean PDF containing only images. There's no hidden text layer that could accidentally expose your information if someone copies and pastes from the document.

**Free and private.** No subscriptions, no accounts, no uploading your documents anywhere. Everything runs on your own computer.

**Actually tested.** Most free redaction tools ship with minimal or no automated testing. bleachpdf runs against [olmOCR-bench](https://huggingface.co/datasets/allenai/olmOCR-bench), a standardized benchmark from the Allen Institute for AI containing thousands of challenging documents -- old scans, dense text, complex layouts, and more. Every test verifies that redacted text is actually hidden by re-scanning the output. See [Testing Strategy](docs/testing.md) for details.

## How It Works

1. Each page gets converted to an image
2. Text recognition finds words and their positions on the page
3. Your patterns are matched against the text
4. Black boxes are drawn over the matches
5. The redacted images become a new PDF
6. The output is scanned again to make sure nothing was missed

## Writing Patterns

For simple cases, use the `-m` flag on the command line:

```bash
bleachpdf document.pdf -m "123456789" -m "JohnDoe"
```

For repeated use or complex patterns, put them in a config file. The tool looks for a file called `pii.yaml` in the current directory (the name comes from "personally identifiable information").

### Exact Text

The simplest pattern matches exact text:

```yaml
patterns:
  - 'match = "123456789"'
  - 'match = "JohnDoe"'
```

**About spaces and punctuation:** The tool strips out spaces, dashes, and punctuation before matching. So if your document shows `123-45-6789`, the tool sees `123456789`. Write your patterns the same way:

| Document shows | Write as |
|----------------|----------|
| `123-45-6789` | `"123456789"` |
| `John Doe` | `"JohnDoe"` |
| `ACCT #12345` | `"ACCT12345"` |

### Ignoring Upper/Lowercase

To match text regardless of capitalization, use `~"..."i`:

```yaml
patterns:
  - 'match = ~"johndoe"i'    # matches JohnDoe, JOHNDOE, johndoe, etc.
```

### Matching Any Digit or Letter

Sometimes you want to match patterns like "any 9-digit number" rather than a specific number. You can define rules for this:

```yaml
patterns:
  - |
    match = d d d d d d d d d
    d = ~"[0-9]"
```

This matches any 9 digits in a row. The `~"[0-9]"` means "any single digit from 0 to 9". Each `d` in the pattern represents one digit, so `d d d d d d d d d` means "nine digits".

Similarly, `~"[A-Za-z]"` matches any letter.

### Combining Text and Patterns

You can mix literal text with patterns:

```yaml
patterns:
  - |
    match = "ACCT" d d d d
    d = ~"[0-9]"
```

This matches "ACCT" followed by exactly 4 digits: `ACCT1234`, `ACCT0001`, etc.

### Repeating Patterns

Use `+` to mean "one or more":

```yaml
patterns:
  - |
    match = "ACCT" d+
    d = ~"[0-9]"
```

This matches "ACCT" followed by any number of digits.

### Common Examples

**Social Security Number** (any 9 digits):

```yaml
patterns:
  - |
    match = d d d d d d d d d
    d = ~"[0-9]"
```

**Phone number** (any 10 digits):

```yaml
patterns:
  - |
    match = d d d d d d d d d d
    d = ~"[0-9]"
```

**A specific name** (ignoring case):

```yaml
patterns:
  - 'match = ~"johndoe"i'
  - 'match = ~"janedoe"i'
```

### Where the Config File Can Live

The tool looks for your config file in these locations, in order:

1. The path you give with `-c` or `--config`
2. The `BLEACHPDF_CONFIG` environment variable
3. `pii.yaml` in the current directory
4. `~/.config/bleachpdf/pii.yaml` (your personal config)
5. `/etc/xdg/bleachpdf/pii.yaml` (system-wide config)

### Learning More About Patterns

The pattern language is called a "parsing expression grammar." If you want to learn more advanced features like optional elements, grouping, and lookahead, see the [parsimonious documentation](https://github.com/erikrose/parsimonious).

## Usage Examples

```bash
bleachpdf document.pdf                    # Redact one file
bleachpdf document.pdf -o redacted.pdf    # Choose the output filename
bleachpdf documents/ -o output/           # Redact all PDFs in a folder
bleachpdf "reports/*.pdf" -o output/      # Redact files matching a pattern
bleachpdf document.pdf -v                 # Show progress while running
```

### Options

| Option | What it does |
|--------|--------------|
| `-m, --match` | Text to redact (case-insensitive). Use multiple times for multiple patterns. |
| `-o, --output` | Where to save the result (default: `output/`) |
| `-c, --config` | Path to a config file |
| `-d, --dpi` | Image quality — higher means sharper but slower (default: 300) |
| `--lang` | Tesseract language(s) for OCR, e.g. `eng`, `eng+kor` (default: `eng`) |
| `-j, --jobs` | How many files to process at once (default: half your CPU cores) |
| `--relaxed` | Don't fail when no matches are found |
| `--no-verify` | Skip the safety check that re-scans the output |
| `-v, --verbose` | Show detailed progress |
| `-q, --quiet` | Don't print anything |

### Exit Codes

When the tool finishes, it returns a number indicating what happened:

| Code | Meaning |
|------|---------|
| 0 | Success — redactions were made |
| 1 | Configuration problem — missing config file, invalid patterns, etc. |
| 2 | File problem — couldn't find input or write output |
| 3 | No matches — the patterns didn't match anything in the document |
| 4 | Verification failed — text is still visible after redaction |

### Strict vs Relaxed Mode

By default, the tool treats "no matches found" as an error. This is intentional — if you're redacting a document, you probably expect it to contain the sensitive text. A missing match could mean:

- You're redacting the wrong document
- The text recognition couldn't read the document
- Your pattern has a typo

If you're processing a batch of documents where some legitimately won't contain matches, use `--relaxed`:

```bash
bleachpdf documents/ --relaxed
```

In relaxed mode, documents with no matches just get a warning instead of causing the tool to fail.

Note that verification failures (text still visible after redaction) are always fatal — that's a serious problem that can't be ignored.

## Limitations

**Text recognition isn't perfect.** Handwriting, unusual fonts, low-quality scans, and very small or dense text can cause recognition errors. The tool automatically retries at higher resolution if the first attempt finds nothing, but some documents may still fail.

**Always check the output yourself.** No automated redaction tool is 100% reliable. Before sharing a redacted document, open it and verify:

- Is all the sensitive information actually covered?
- Did anything slip through?
- Was anything accidentally over-redacted?

Think of this tool as a helpful first pass, not a replacement for careful human review.  Also, note carefully the relevant details in the accompanying LICENSE file.

# No license granted for censorship

No license, right, or permission is granted -- expressly or by implication -- to use this software for censorship. This prohibition applies to all parties without exception, including but not limited to: individuals, companies, corporations, partnerships, nonprofit organizations, religious institutions, schools, universities, municipalities, counties, states, provinces, territories, national governments, intergovernmental bodies, and any agents or contractors acting on their behalf.

For the purposes of this restriction, "censorship" means using this software to suppress, obscure, or redact content in books, films, plays, newspapers, periodicals, websites, broadcasts, academic publications, or any other material created for public distribution or consumption, where the purpose is to prevent an audience from seeing the original content rather than to protect specific private information.

This software is designed to protect personal privacy. It is not designed to silence speech, and its author, John Byrd, does not grant permission for it to be used that way.

## Development

### Running Tests

Each test redacts a document, then re-scans the output to verify the text is actually hidden.

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests run in parallel by default, using half your CPU cores. Override with `--jobs`:

```bash
pytest tests/ --jobs=4        # Use 4 workers
pytest tests/ -n 1            # Run serially (disable parallelism)
pytest tests/ --limit=10      # Only run first 10 test cases
```

For the full testing documentation—including filtering by category, setting pass thresholds, and CI configuration—see [Testing Strategy](docs/testing.md).
