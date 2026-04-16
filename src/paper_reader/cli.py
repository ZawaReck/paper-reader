from __future__ import annotations

import logging
from pathlib import Path

import typer

from .extractor import ExtractionError, extract_pdf, write_result
from .models import ExtractionOptions
from .utils import ensure_directory

app = typer.Typer(
    add_completion=False,
    help="Convert academic PDFs into stable txt files for downstream AI reading workflows.",
)


@app.callback()
def main_callback() -> None:
    """Root CLI for paper-reader."""


@app.command("extract")
def extract_command(
    input_path: Path = typer.Option(..., "--input", exists=False, help="PDF file or directory to read."),
    output_path: Path = typer.Option(..., "--output", help="Directory to write txt outputs."),
    glob_pattern: str = typer.Option("*.pdf", "--glob", help="Glob pattern for directory input."),
    enable_ocr: bool = typer.Option(False, "--ocr", help="Enable OCR fallback for image-based PDFs."),
    mode: str = typer.Option("ai-readable", "--mode", help="Extraction mode: ai-readable or debug."),
    include_visual_hints: bool = typer.Option(
        False,
        "--include-visual-hints",
        help="Include concise figure-caption hints in ai-readable mode.",
    ),
    include_tables: bool = typer.Option(
        False,
        "--include-tables",
        help="Keep table-like data blocks in ai-readable mode.",
    ),
    exclude_references: bool = typer.Option(
        False,
        "--exclude-references",
        help="Exclude the references section from output.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing txt outputs."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Limit the number of PDFs processed."),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose logging."),
    output_format: str = typer.Option("txt", "--format", help="Output format. Currently only txt is supported."),
) -> None:
    if output_format != "txt":
        raise typer.BadParameter("Only --format txt is currently supported.")

    if not input_path.exists():
        raise typer.BadParameter(f"Input path does not exist: {input_path}")
    if mode not in {"ai-readable", "debug"}:
        raise typer.BadParameter("Only --mode ai-readable or --mode debug is supported.")

    ensure_directory(output_path)
    logger = _configure_logger(output_path, verbose)
    options = ExtractionOptions(
        enable_ocr=enable_ocr,
        force=force,
        limit=limit,
        verbose=verbose,
        output_format="txt",
        mode=mode,
        include_visual_hints=include_visual_hints,
        include_tables=include_tables,
        exclude_references=exclude_references,
    )

    pdf_paths = _collect_pdf_paths(input_path, glob_pattern)
    if limit is not None:
        pdf_paths = pdf_paths[:limit]

    if not pdf_paths:
        raise typer.BadParameter(f"No PDF files found for input: {input_path}")

    processed = 0
    failed = 0

    for pdf_path in pdf_paths:
        target_path = output_path / f"{pdf_path.stem}.txt"
        if target_path.exists() and not force:
            logger.info("Skipping existing output: %s", target_path)
            continue
        try:
            result = extract_pdf(pdf_path, options)
            written_path = write_result(result, output_path)
            logger.info("Extracted %s -> %s using %s", pdf_path, written_path, result.method)
            processed += 1
        except ExtractionError as exc:
            logger.error("Extraction failed for %s: %s", pdf_path, exc)
            failed += 1
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected error for %s: %s", pdf_path, exc)
            failed += 1

    typer.echo(f"Processed: {processed}, Failed: {failed}, Total: {len(pdf_paths)}")
    if failed:
        raise typer.Exit(code=1)


def _collect_pdf_paths(input_path: Path, glob_pattern: str) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise typer.BadParameter(f"Input file is not a PDF: {input_path}")
        return [input_path.resolve()]
    return sorted(path.resolve() for path in input_path.glob(glob_pattern) if path.is_file())


def _configure_logger(output_dir: Path, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("paper_reader")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    file_handler = logging.FileHandler(output_dir / "extract_errors.log", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    if verbose:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(console_handler)

    return logger


def main() -> None:
    app()
