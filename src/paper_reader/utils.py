from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import ExtractionResult


def current_timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def relative_output_name(pdf_path: Path) -> str:
    return f"{pdf_path.stem}.txt"


def render_txt(result: ExtractionResult) -> str:
    header = [
        f"SOURCE: {result.source_path.resolve()}",
        f"EXTRACTED_AT: {result.extracted_at}",
        f"METHOD: {result.method}",
        f"PAGES: {result.page_count}",
        f"MODE: {result.mode}",
    ]
    if result.title:
        header.append(f"TITLE: {result.title}")
    if result.doi:
        header.append(f"DOI: {result.doi}")
    if result.warnings:
        header.append(f"WARNINGS: {' | '.join(result.warnings)}")

    body: list[str] = ["\n".join(header), ""]
    for page in result.pages:
        body.append(f"===== PAGE {page.number} =====")
        if result.mode == "debug" and page.visuals:
            body.append("[VISUAL SUPPLEMENTS]")
            for visual in page.visuals:
                bbox = ", ".join(f"{value:.1f}" for value in visual.bbox)
                body.append(
                    f"- {visual.kind.upper()} {visual.index}: detected at bbox=({bbox})"
                )
                if visual.caption_hint:
                    body.append(f"  CAPTION_HINT: {visual.caption_hint}")
                if visual.note:
                    body.append(f"  NOTE: {visual.note}")
            body.append("")
        elif page.visuals:
            captions = [
                visual.caption_hint
                for visual in page.visuals
                if visual.caption_hint and visual.caption_hint not in page.text
            ]
            for caption in captions:
                body.append("[FIGURE CAPTION]")
                body.append(caption)
                body.append("")
        body.append(page.text)
        body.append("")
    if result.references:
        body.append("===== REFERENCES =====")
        body.append(result.references)
        body.append("")
    return "\n".join(body).rstrip() + "\n"
