# Sample Workflow Notes

This project does not require a config file for basic usage. A typical workflow is:

```bash
python -m paper_reader extract \
  --input /absolute/or/relative/path/to/research-project/refs/papers \
  --output /absolute/or/relative/path/to/research-project/refs/papers_text \
  --ocr \
  --verbose
```

Suggested conventions in a research project:

- source PDFs: `refs/papers/`
- extracted text: `refs/papers_text/`
- downstream AI reading: combine extracted `.txt` with project notes and background documents
