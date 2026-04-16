from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import PageText
from .utils import normalize_text


class OcrUnavailableError(RuntimeError):
    """Raised when OCR dependencies are not available locally."""


def _check_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise OcrUnavailableError(f"Required OCR binary not found: {name}")


def extract_with_ocrmypdf(pdf_path: Path) -> list[PageText]:
    _check_binary("ocrmypdf")
    with tempfile.TemporaryDirectory(prefix="paper-reader-ocr-") as temp_dir:
        temp_path = Path(temp_dir)
        sidecar = temp_path / "sidecar.txt"
        output_pdf = temp_path / "ocr-output.pdf"

        cmd = [
            "ocrmypdf",
            "--skip-text",
            "--sidecar",
            str(sidecar),
            str(pdf_path),
            str(output_pdf),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"OCR failed for {pdf_path}: {stderr}")

        text = sidecar.read_text(encoding="utf-8", errors="ignore")
        normalized = normalize_text(text)
        if not normalized:
            raise RuntimeError(f"OCR produced empty text for {pdf_path}")

        pages = normalized.split("\f")
        return [
            PageText(number=index, text=page.strip() or "[NO OCR TEXT]")
            for index, page in enumerate(pages, start=1)
        ]
