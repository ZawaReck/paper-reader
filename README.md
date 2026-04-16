# paper-reader

Japanese README: [README.ja.md](./README.ja.md)

`paper-reader` is a local Python CLI for converting academic PDFs into stable, reusable UTF-8 `.txt` files that AI systems can read more reliably than raw PDF input.

The goal is not to interpret paper content. This tool is a PDF extraction foundation for research workflows: extract text, preserve page boundaries, record metadata, and leave downstream interpretation to a separate AI workflow.

## Features

- Process a single PDF or a directory of PDFs
- Read PDFs from outside this repository via `--input`
- Write extracted `.txt` files directly into another project via `--output`
- Prefer embedded-text extraction first, with fallback strategies
- Optional OCR fallback for image-based PDFs
- Stable per-paper output files with metadata headers
- `ai-readable` mode for AI-friendly paper reading
- Optional figure-caption hints without bbox noise
- References separated from the main body by default
- Error logging for failures instead of silent skips
- Design leaves room for future `markdown` output support

## Directory Layout

```text
paper-reader/
  README.md
  pyproject.toml
  src/paper_reader/__init__.py
  src/paper_reader/__main__.py
  src/paper_reader/cli.py
  src/paper_reader/extractor.py
  src/paper_reader/models.py
  src/paper_reader/ocr.py
  src/paper_reader/utils.py
  tests/test_cli.py
  tests/test_extractor.py
  examples/sample_config.md
```

## Setup

### Base install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Main dependencies

- `PyMuPDF`: primary extractor
- `pdfplumber`: secondary layout-oriented extractor
- `pypdf`: metadata/page counting fallback
- `typer`: CLI

### Optional OCR dependencies

Install the extra Python dependencies:

```bash
pip install -e .[ocr]
```

System dependencies are still required:

- `tesseract`
- `ocrmypdf`

On macOS with Homebrew:

```bash
brew install tesseract ocrmypdf
```

If these tools are unavailable, OCR mode remains optional and the CLI will log a clear error.

## Typical Usage

Process a directory of PDFs from another research project:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable
```

Process a single PDF with OCR enabled:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers/paper.pdf \
  --output /path/to/research-project/refs/papers_text \
  --ocr
```

Use a custom glob:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --glob "*.PDF"
```

Overwrite existing outputs and limit the number of files:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --force \
  --limit 10 \
  --verbose
```

Enable concise visual hints:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable \
  --include-visual-hints
```

Keep table-like blocks in output when needed:

```bash
python -m paper_reader extract \
  --input /path/to/research-project/refs/papers \
  --output /path/to/research-project/refs/papers_text \
  --mode ai-readable \
  --include-tables
```

## Output Format

Each paper becomes one UTF-8 `.txt` file.

Example:

```txt
SOURCE: /abs/path/to/paper.pdf
EXTRACTED_AT: 2026-04-16T12:34:56+09:00
METHOD: pymupdf
PAGES: 12
MODE: ai-readable

===== PAGE 1 =====
...

===== PAGE 2 =====
...
```

The output is intended to be read by AI together with other project context or background notes.
In `ai-readable` mode, visual bbox logs are hidden by default. If `--include-visual-hints` is enabled, only concise caption-style hints are emitted.

## Extraction Strategy

The extractor prefers stability over perfect formatting:

1. Direct text extraction with `PyMuPDF`
2. AI-oriented cleanup: Unicode normalization, boilerplate reduction, heading normalization, references split
3. Layout-oriented fallback with `pdfplumber`
4. OCR fallback when `--ocr` is enabled

The chosen method is recorded in each output file so extraction quality can be inspected later.

## Logs

- Extraction failures are written to `extract_errors.log` in the output directory
- Existing outputs are preserved unless `--force` is used
- Failures do not stop the whole batch

## Tests

Run:

```bash
pytest
```

The tests cover:

- single PDF processing
- directory batch processing
- output `.txt` creation
- invalid input handling
- OCR flag acceptance in the CLI

## Known Limits

- Multi-column PDFs may produce reading-order mistakes
- Mathematical expressions may degrade into plain text approximations
- Figures and tables are not reconstructed semantically
- Scanned PDFs depend on local OCR quality and installed OCR tools
- Figure-heavy or publisher-heavy first pages may still require heuristic tuning

## Intended Role In Research Workflows

This repository is a shared PDF extraction layer. In a research project, the expected flow is:

1. Store source PDFs under a project path such as `refs/papers/`
2. Run `paper-reader` from this separate repository using that external path as `--input`
3. Write `.txt` outputs back into a project path such as `refs/papers_text/`
4. Feed the generated `.txt` files to AI together with project-specific background materials

The tool does not interpret or summarize papers. It only turns PDFs into reusable text assets.
