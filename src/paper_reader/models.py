from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


OutputFormat = Literal["txt"]
ExtractionMode = Literal["ai-readable", "debug"]


@dataclass(slots=True)
class VisualSupplement:
    index: int
    kind: str
    bbox: tuple[float, float, float, float]
    caption_hint: str | None = None
    note: str | None = None


@dataclass(slots=True)
class PageText:
    number: int
    text: str
    visuals: list[VisualSupplement] = field(default_factory=list)


@dataclass(slots=True)
class ExtractionResult:
    source_path: Path
    extracted_at: str
    method: str
    mode: ExtractionMode
    pages: list[PageText] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    references: str | None = None
    title: str | None = None
    doi: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass(slots=True)
class ExtractionOptions:
    enable_ocr: bool = False
    force: bool = False
    limit: int | None = None
    verbose: bool = False
    output_format: OutputFormat = "txt"
    mode: ExtractionMode = "ai-readable"
    include_visual_hints: bool = False
    include_tables: bool = False
    exclude_references: bool = False
