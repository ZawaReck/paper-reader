from __future__ import annotations

from pathlib import Path

import fitz
from typer.testing import CliRunner

from paper_reader.cli import app


def create_sample_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def test_cli_processes_single_pdf(tmp_path: Path) -> None:
    runner = CliRunner()
    pdf_path = tmp_path / "paper.pdf"
    output_dir = tmp_path / "texts"
    create_sample_pdf(pdf_path, "CLI test content that should be extracted as readable text.")

    result = runner.invoke(
        app,
        ["extract", "--input", str(pdf_path), "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    assert (output_dir / "paper.txt").exists()


def test_cli_processes_directory(tmp_path: Path) -> None:
    runner = CliRunner()
    input_dir = tmp_path / "pdfs"
    output_dir = tmp_path / "texts"
    input_dir.mkdir()
    create_sample_pdf(input_dir / "one.pdf", "One paper text with enough content to be extracted.")
    create_sample_pdf(input_dir / "two.pdf", "Two paper text with enough content to be extracted.")

    result = runner.invoke(
        app,
        ["extract", "--input", str(input_dir), "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    assert (output_dir / "one.txt").exists()
    assert (output_dir / "two.txt").exists()


def test_cli_fails_for_missing_input(tmp_path: Path) -> None:
    runner = CliRunner()
    output_dir = tmp_path / "texts"

    result = runner.invoke(
        app,
        ["extract", "--input", str(tmp_path / "missing"), "--output", str(output_dir)],
    )

    assert result.exit_code != 0
    assert "Input path does not exist" in result.output


def test_cli_accepts_ocr_flag(tmp_path: Path) -> None:
    runner = CliRunner()
    pdf_path = tmp_path / "paper.pdf"
    output_dir = tmp_path / "texts"
    create_sample_pdf(pdf_path, "OCR flag parsing test with enough embedded text to avoid OCR.")

    result = runner.invoke(
        app,
        ["extract", "--input", str(pdf_path), "--output", str(output_dir), "--ocr"],
    )

    assert result.exit_code == 0


def test_cli_accepts_ai_readable_options(tmp_path: Path) -> None:
    runner = CliRunner()
    pdf_path = tmp_path / "paper.pdf"
    output_dir = tmp_path / "texts"
    create_sample_pdf(pdf_path, "Abstract\nCLI mode parsing test with enough embedded text to avoid OCR.")

    result = runner.invoke(
        app,
        [
            "extract",
            "--input",
            str(pdf_path),
            "--output",
            str(output_dir),
            "--mode",
            "ai-readable",
            "--include-visual-hints",
            "--exclude-references",
        ],
    )

    assert result.exit_code == 0
