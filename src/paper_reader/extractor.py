from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from pathlib import Path

import fitz
import pdfplumber
from pypdf import PdfReader

from .models import ExtractionOptions, ExtractionResult, PageText, VisualSupplement
from .ocr import OcrUnavailableError, extract_with_ocrmypdf
from .utils import current_timestamp, normalize_text, relative_output_name, render_txt

SECTION_HEADINGS = {
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "methodology",
    "experimental setup",
    "experiment",
    "experiments",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "conclusions",
    "references",
}

HEADING_PATTERN = re.compile(
    r"^(?:(\d+(?:\.\d+)*)\s+)?"
    r"(Abstract|Introduction|Related Work|Background|Method(?:ology)?|Methods|"
    r"Experimental Setup|Experiment(?:s)?|Results|Discussion|Limitations|"
    r"Conclusion(?:s)?|References)\s*$",
    re.IGNORECASE,
)
AUTHORS_LINE_PATTERN = re.compile(r"^(?:[A-Z][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]+){1,5})(?:\s*,\s*(?:[A-Z][A-Za-zÀ-ÿ'’.-]+(?:\s+[A-Z][A-Za-zÀ-ÿ'’.-]+){1,5}))*\.?$")
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
FRONT_MATTER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^pdf download\b",
        r"\btotal citations\b",
        r"\btotal downloads\b",
        r"^published:",
        r"^latest updates:",
        r"^citation in bibtex format\b",
        r"^conference sponsors?\b",
        r"^open access support provided by\b",
        r"^acm reference format\b",
        r"^recommended citation\b",
        r"^permission to make digital or hard copies",
        r"^author version\b",
        r"^downloaded from\b",
        r"^proceedings of\b",
        r"\bisbn[:\s]",
        r"^copyright\b",
        r"^©",
        r"^doi[:\s]",
        r"^https?://",
        r"^www\.",
    ]
]
NOISE_LINE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^ccs concepts?$",
        r"^additional key words and phrases$",
        r"^keywords$",
        r"^acm reference format$",
        r"^permission to make digital or hard copies",
        r"^for personal or classroom use",
        r"^this work is licensed under",
    ]
]


class ExtractionError(RuntimeError):
    """Raised when all extraction methods fail."""


@dataclass(slots=True)
class TextBlock:
    text: str
    bbox: tuple[float, float, float, float]
    is_heading: bool = False
    max_font_size: float = 0.0
    page_number: int = 1

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def x1(self) -> float:
        return self.bbox[2]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


def extract_pdf(pdf_path: Path, options: ExtractionOptions) -> ExtractionResult:
    warnings: list[str] = []
    metadata_title = _extract_metadata_title(pdf_path)

    direct_pages = _extract_with_pymupdf(pdf_path)
    if _has_meaningful_text(direct_pages):
        result = _postprocess_result(
            pdf_path=pdf_path,
            pages=direct_pages,
            method="pymupdf",
            options=options,
            warnings=warnings,
            metadata_title=metadata_title,
        )
        if _has_meaningful_text(result.pages):
            return result

    layout_pages = _extract_with_pdfplumber(pdf_path)
    if _has_meaningful_text(layout_pages):
        warnings.append("PyMuPDF extraction was empty or too sparse; used pdfplumber fallback.")
        result = _postprocess_result(
            pdf_path=pdf_path,
            pages=layout_pages,
            method="pdfplumber",
            options=options,
            warnings=warnings,
            metadata_title=metadata_title,
        )
        if _has_meaningful_text(result.pages):
            return result

    if options.enable_ocr:
        try:
            ocr_pages = extract_with_ocrmypdf(pdf_path)
        except OcrUnavailableError as exc:
            raise ExtractionError(str(exc)) from exc
        if _has_meaningful_text(ocr_pages):
            warnings.append("Text extraction failed; used OCR fallback.")
            result = _postprocess_result(
                pdf_path=pdf_path,
                pages=ocr_pages,
                method="ocrmypdf",
                options=options,
                warnings=warnings,
                metadata_title=metadata_title,
            )
            if _has_meaningful_text(result.pages):
                return result

    page_count = _count_pages(pdf_path)
    raise ExtractionError(
        f"Failed to extract meaningful text from {pdf_path} after {page_count} pages."
    )


def write_result(result: ExtractionResult, output_dir: Path) -> Path:
    output_path = output_dir / relative_output_name(result.source_path)
    output_path.write_text(render_txt(result), encoding="utf-8")
    return output_path


def _postprocess_result(
    pdf_path: Path,
    pages: list[PageText],
    method: str,
    options: ExtractionOptions,
    warnings: list[str],
    metadata_title: str | None,
) -> ExtractionResult:
    if options.mode == "debug":
        title = _extract_title(pdf_path, pages, metadata_title)
        doi = _extract_doi(pages)
        if not options.include_visual_hints:
            for page in pages:
                page.visuals = []
        return ExtractionResult(
            source_path=pdf_path,
            extracted_at=current_timestamp(),
            method=method,
            mode=options.mode,
            pages=pages,
            warnings=warnings,
            title=title,
            doi=doi,
        )

    cleaned_pages = _clean_pages_for_ai(pages, options)
    cleaned_pages = _drop_meaningless_front_pages(cleaned_pages)
    title = _extract_title(pdf_path, cleaned_pages, metadata_title) or _extract_title(
        pdf_path, pages, metadata_title
    )
    doi = _extract_doi(pages)
    references = None if options.exclude_references else _extract_references(cleaned_pages)
    if references:
        cleaned_pages = _remove_reference_content_from_pages(cleaned_pages)

    if not options.include_visual_hints:
        for page in cleaned_pages:
            page.visuals = []
    else:
        for page in cleaned_pages:
            page.visuals = [
                VisualSupplement(
                    index=visual.index,
                    kind=visual.kind,
                    bbox=visual.bbox,
                    caption_hint=visual.caption_hint,
                    note=None,
                )
                for visual in page.visuals
                if visual.caption_hint
            ]

    return ExtractionResult(
        source_path=pdf_path,
        extracted_at=current_timestamp(),
        method=method,
        mode=options.mode,
        pages=cleaned_pages,
        warnings=warnings,
        references=references,
        title=title,
        doi=doi,
    )


def _extract_with_pymupdf(pdf_path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            page_dict = page.get_text("dict", sort=False)
            text = _linearize_page_text(page_dict, page.rect.width)
            visuals = _extract_visual_supplements(page_dict)
            pages.append(PageText(number=page_number, text=text or "[NO TEXT EXTRACTED]", visuals=visuals))
    return pages


def _extract_with_pdfplumber(pdf_path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as document:
        for page_number, page in enumerate(document.pages, start=1):
            text = normalize_text(page.extract_text(layout=False) or "")
            pages.append(PageText(number=page_number, text=text or "[NO TEXT EXTRACTED]"))
    return pages


def _linearize_page_text(page_dict: dict, page_width: float) -> str:
    text_blocks = _collect_text_blocks(page_dict)
    if not text_blocks:
        return ""

    ordered_blocks = _order_blocks_for_reading(text_blocks, page_width)
    paragraphs = [block.text for block in ordered_blocks if block.text]
    return "\n\n".join(paragraphs)


def _collect_text_blocks(page_dict: dict) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    for raw_block in page_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        text = _flatten_block_text(raw_block)
        if not text:
            continue
        bbox = tuple(float(value) for value in raw_block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        max_font_size = 0.0
        for line in raw_block.get("lines", []):
            for span in line.get("spans", []):
                max_font_size = max(max_font_size, float(span.get("size", 0.0)))
        blocks.append(
            TextBlock(
                text=text,
                bbox=bbox,
                is_heading=bool(HEADING_PATTERN.match(text)),
                max_font_size=max_font_size,
            )
        )
    return blocks


def _order_blocks_for_reading(blocks: list[TextBlock], page_width: float) -> list[TextBlock]:
    if not _looks_like_two_column_page(blocks, page_width):
        return sorted(blocks, key=lambda block: (round(block.y0, 1), round(block.x0, 1)))

    left_blocks, right_blocks, spanning_blocks = _split_blocks_by_column(blocks, page_width)
    if len(left_blocks) < 2 or len(right_blocks) < 2:
        return sorted(blocks, key=lambda block: (round(block.y0, 1), round(block.x0, 1)))

    top_spanning, middle_spanning, bottom_spanning = _split_spanning_blocks(
        spanning_blocks, left_blocks, right_blocks
    )

    ordered: list[TextBlock] = []
    ordered.extend(sorted(top_spanning, key=lambda block: (round(block.y0, 1), round(block.x0, 1))))
    ordered.extend(_order_column_blocks(left_blocks))
    ordered.extend(sorted(middle_spanning, key=lambda block: (round(block.y0, 1), round(block.x0, 1))))
    ordered.extend(_order_column_blocks(right_blocks))
    ordered.extend(sorted(bottom_spanning, key=lambda block: (round(block.y0, 1), round(block.x0, 1))))
    return _stitch_heading_anchored_blocks(ordered)


def _looks_like_two_column_page(blocks: list[TextBlock], page_width: float) -> bool:
    if len(blocks) < 6:
        return False

    center_left = page_width * 0.46
    center_right = page_width * 0.54
    narrow_blocks = [block for block in blocks if block.width < page_width * 0.45]
    left_blocks = [block for block in narrow_blocks if block.center_x < center_left]
    right_blocks = [block for block in narrow_blocks if block.center_x > center_right]
    if len(left_blocks) < 2 or len(right_blocks) < 2:
        return False

    left_y = [block.y0 for block in left_blocks]
    right_y = [block.y0 for block in right_blocks]
    if not left_y or not right_y:
        return False

    shared_vertical_band = (
        min(max(left_y), max(right_y)) - max(min(left_y), min(right_y))
    )
    if shared_vertical_band < 80:
        return False

    middle_band_blocks = [
        block
        for block in blocks
        if block.x0 < page_width * 0.48 and block.x1 > page_width * 0.52 and block.width > page_width * 0.55
    ]
    return len(middle_band_blocks) < max(4, len(blocks) // 2)


def _split_blocks_by_column(
    blocks: list[TextBlock], page_width: float
) -> tuple[list[TextBlock], list[TextBlock], list[TextBlock]]:
    left_boundary = page_width * 0.48
    right_boundary = page_width * 0.52
    left_blocks: list[TextBlock] = []
    right_blocks: list[TextBlock] = []
    spanning_blocks: list[TextBlock] = []

    for block in blocks:
        if block.width > page_width * 0.55 or (block.x0 < left_boundary and block.x1 > right_boundary):
            spanning_blocks.append(block)
        elif block.center_x <= page_width / 2:
            left_blocks.append(block)
        else:
            right_blocks.append(block)
    return left_blocks, right_blocks, spanning_blocks


def _split_spanning_blocks(
    spanning_blocks: list[TextBlock],
    left_blocks: list[TextBlock],
    right_blocks: list[TextBlock],
) -> tuple[list[TextBlock], list[TextBlock], list[TextBlock]]:
    if not spanning_blocks:
        return [], [], []

    column_top = min([block.y0 for block in left_blocks + right_blocks], default=0.0)
    column_bottom = max([block.y1 for block in left_blocks + right_blocks], default=0.0)

    top_spanning: list[TextBlock] = []
    middle_spanning: list[TextBlock] = []
    bottom_spanning: list[TextBlock] = []

    for block in spanning_blocks:
        if block.y1 <= column_top + 20:
            top_spanning.append(block)
        elif block.y0 >= column_bottom - 20:
            bottom_spanning.append(block)
        else:
            middle_spanning.append(block)
    return top_spanning, middle_spanning, bottom_spanning


def _order_column_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    ordered = sorted(blocks, key=lambda block: (round(block.y0, 1), round(block.x0, 1)))
    return _stitch_heading_anchored_blocks(ordered)


def _stitch_heading_anchored_blocks(blocks: list[TextBlock]) -> list[TextBlock]:
    if not blocks:
        return []

    stitched: list[TextBlock] = []
    for block in blocks:
        if not stitched:
            stitched.append(block)
            continue

        previous = stitched[-1]
        if _belongs_to_same_section(previous, block):
            stitched[-1] = TextBlock(
                text=f"{previous.text}\n\n{block.text}",
                bbox=(
                    min(previous.x0, block.x0),
                    min(previous.y0, block.y0),
                    max(previous.x1, block.x1),
                    max(previous.y1, block.y1),
                ),
                is_heading=previous.is_heading,
            )
        else:
            stitched.append(block)
    return stitched


def _belongs_to_same_section(previous: TextBlock, current: TextBlock) -> bool:
    if previous.is_heading:
        return current.y0 - previous.y1 < 120
    return False


def _extract_visual_supplements(page_dict: dict) -> list[VisualSupplement]:
    text_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
    image_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 1]

    visuals: list[VisualSupplement] = []
    for index, block in enumerate(image_blocks, start=1):
        bbox = tuple(float(value) for value in block.get("bbox", (0.0, 0.0, 0.0, 0.0)))
        caption_hint = _find_caption_hint(text_blocks, bbox)
        visuals.append(
            VisualSupplement(
                index=index,
                kind="image",
                bbox=bbox,
                caption_hint=caption_hint,
                note="Visual region detected.",
            )
        )
    return visuals


def _find_caption_hint(text_blocks: list[dict], image_bbox: tuple[float, float, float, float]) -> str | None:
    x0, y0, x1, y1 = image_bbox
    candidates: list[tuple[float, str]] = []
    for block in text_blocks:
        bx0, by0, bx1, by1 = block.get("bbox", (0.0, 0.0, 0.0, 0.0))
        block_text = _flatten_block_text(block)
        if not block_text:
            continue

        vertical_gap_below = by0 - y1
        vertical_gap_above = y0 - by1
        horizontal_overlap = min(x1, bx1) - max(x0, bx0)
        overlap_ok = horizontal_overlap > 0 or abs((bx0 + bx1) / 2 - (x0 + x1) / 2) < 120
        looks_like_caption = block_text.lower().startswith(("figure", "fig.", "fig ", "table"))

        if overlap_ok and 0 <= vertical_gap_below <= 80:
            score = vertical_gap_below
            if looks_like_caption:
                score -= 20
            candidates.append((score, block_text))
        elif overlap_ok and 0 <= vertical_gap_above <= 50 and looks_like_caption:
            candidates.append((vertical_gap_above + 10, block_text))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _flatten_block_text(block: dict) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans: list[str] = []
        for span in line.get("spans", []):
            text = span.get("text", "").strip()
            if text:
                spans.append(text)
        if spans:
            lines.append(" ".join(spans))
    return _merge_wrapped_lines(lines)


def _merge_wrapped_lines(lines: list[str]) -> str:
    merged: list[str] = []
    for line in lines:
        normalized_line = _normalize_unicode(line)
        if not normalized_line:
            continue
        if not merged:
            merged.append(normalized_line)
            continue

        previous = merged[-1]
        if previous.endswith("-") and normalized_line:
            merged[-1] = previous[:-1] + normalized_line
        elif _should_keep_line_break(previous, normalized_line):
            merged.append(normalized_line)
        else:
            merged[-1] = previous + " " + normalized_line
    return "\n\n".join(part.strip() for part in merged if part.strip())


def _should_keep_line_break(previous: str, current: str) -> bool:
    if HEADING_PATTERN.match(current):
        return True
    if previous.endswith((".", "?", "!", ":")):
        return True
    if current.startswith(("[", "Figure", "Fig.", "Table")):
        return True
    return False


def _clean_pages_for_ai(pages: list[PageText], options: ExtractionOptions) -> list[PageText]:
    first_two_have_main_heading = any(
        _is_main_section_heading(_normalize_heading_if_needed(_normalize_unicode(paragraph)))
        for page in pages[:2]
        for paragraph in page.text.split("\n\n")
        if paragraph.strip()
    )
    repeated_paragraphs = _find_repeated_header_like_paragraphs(pages)
    cleaned_pages: list[PageText] = []
    inside_abstract = False
    for index, page in enumerate(pages, start=1):
        paragraphs = [paragraph for paragraph in page.text.split("\n\n") if paragraph.strip()]
        page_has_main_heading = any(
            _is_main_section_heading(_normalize_heading_if_needed(_normalize_unicode(paragraph)))
            for paragraph in paragraphs
            if paragraph.strip()
        )
        cleaned_paragraphs = []
        main_heading_seen = False
        skip_caption_continuation = False
        for paragraph in paragraphs:
            normalized = _normalize_unicode(paragraph)
            if not normalized:
                continue
            normalized = re.sub(r"^RESEARCH-ARTICLE\s+", "", normalized, flags=re.IGNORECASE)
            if skip_caption_continuation and len(normalized.split()) <= 30 and not HEADING_PATTERN.match(normalized):
                skip_caption_continuation = False
                continue
            skip_caption_continuation = False
            if normalized in repeated_paragraphs:
                continue
            if _is_running_header_footer_paragraph(normalized):
                continue
            if _is_front_matter_paragraph(normalized, index):
                continue
            if _is_figure_caption_paragraph(normalized):
                skip_caption_continuation = True
                continue
            if _is_author_or_affiliation_paragraph(normalized):
                continue
            if _is_noise_paragraph(normalized):
                continue
            if _is_table_like_paragraph(normalized) and not options.include_tables:
                continue
            normalized_heading = _normalize_heading_if_needed(normalized)
            if normalized_heading == "Abstract":
                inside_abstract = True
            if _is_main_section_heading(normalized_heading):
                main_heading_seen = True
                if normalized_heading != "Abstract":
                    inside_abstract = False
            if index <= 2 and first_two_have_main_heading and not page_has_main_heading:
                if _looks_like_title(normalized_heading) and not cleaned_paragraphs:
                    cleaned_paragraphs.append(normalized_heading)
                continue
            if index <= 2 and first_two_have_main_heading and page_has_main_heading and not main_heading_seen:
                if _looks_like_title(normalized_heading) and not cleaned_paragraphs:
                    cleaned_paragraphs.append(normalized_heading)
                continue
            if inside_abstract and _is_abstract_noise_paragraph(normalized_heading):
                continue
            cleaned_paragraphs.append(normalized_heading)

        text = _cleanup_text("\n\n".join(cleaned_paragraphs))
        cleaned_pages.append(PageText(number=page.number, text=text, visuals=page.visuals))
    return cleaned_pages


def _normalize_unicode(value: str) -> str:
    replacements = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "ft",
        "\ufb06": "st",
        "h\uef3cps": "https",
        "hps": "https",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)

    value = unicodedata.normalize("NFKC", value)
    value = value.replace("\u00ad", "")
    value = "".join(char for char in value if _is_allowed_character(char))
    value = re.sub(r"\s+", " ", value.replace("\n", " \n "))
    value = value.replace(" \n ", "\n")
    return normalize_text(value)


def _is_allowed_character(char: str) -> bool:
    if char in {"\n", "\t"}:
        return True
    category = unicodedata.category(char)
    if category.startswith("C") and char not in {"\n", "\t"}:
        return False
    return True


def _is_front_matter_paragraph(paragraph: str, page_number: int) -> bool:
    lowered = paragraph.lower()
    if page_number <= 2:
        for pattern in FRONT_MATTER_PATTERNS:
            if pattern.search(paragraph):
                return True
    if page_number <= 2 and "bibtex" in lowered:
        return True
    if page_number <= 2 and "permission to make digital or hard copies" in lowered:
        return True
    if page_number <= 2 and lowered.startswith("ccs concepts"):
        return True
    if page_number <= 2 and "publication rights licensed to acm" in lowered:
        return True
    if page_number <= 2 and lowered.startswith("acm, new york"):
        return True
    if page_number <= 2 and "conference on human factors in computing systems" in lowered and "doi.org" in lowered:
        return True
    if page_number <= 2 and re.fullmatch(r"[A-Za-zÀ-ÿ .,'-]+\. 20\d{2}\.", paragraph):
        return True
    if page_number <= 2 and "," in paragraph and len(paragraph.split()) <= 8 and not paragraph.endswith("."):
        return True
    if page_number <= 2 and _is_author_or_affiliation_paragraph(paragraph):
        return True
    return False


def _is_noise_paragraph(paragraph: str) -> bool:
    stripped = paragraph.strip()
    if not stripped:
        return True
    if _is_figure_caption_paragraph(stripped):
        return True
    for pattern in NOISE_LINE_PATTERNS:
        if pattern.search(stripped):
            return True
    if len(stripped) < 3:
        return True
    if stripped.count("|") >= 3:
        return True
    if "human-centered computing" in stripped.lower():
        return True
    if stripped.lower().startswith(("acm reference format", "recommended citation")):
        return True
    return False


def _is_running_header_footer_paragraph(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if " et al." in lowered and ("chi" in lowered or "uist" in lowered):
        return True
    if re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)", lowered):
        if ("chi" in lowered or "uist" in lowered) and len(paragraph.split()) <= 18:
            return True
    if lowered.startswith(("chi ’", "chi '", "uist ’", "uist '")) and len(paragraph.split()) <= 18:
        return True
    return False


def _is_author_or_affiliation_paragraph(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if "@" in paragraph:
        return True
    if AUTHORS_LINE_PATTERN.fullmatch(paragraph.strip()) and len(paragraph.split()) <= 10:
        return True
    affiliation_tokens = [
        "university",
        "institute",
        "department",
        "school",
        "college",
        "laboratory",
        "lab",
        "germany",
        "japan",
        "munich",
        "darmstadt",
        "yokohama",
    ]
    if any(token in lowered for token in affiliation_tokens) and len(paragraph.split()) <= 14:
        return True
    if lowered in {"sigchi"}:
        return True
    return False


def _is_table_like_paragraph(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if _is_figure_caption_paragraph(paragraph):
        return True
    if re.match(r"^table\s+\d+[:.]?", paragraph, re.IGNORECASE):
        return True
    if re.search(r"\b(m|sd|mad|med\.?)\b", lowered) and len(paragraph.split()) <= 24:
        return True
    numeric_tokens = re.findall(r"\b\d+(?:\.\d+)?%?\b", paragraph)
    if len(numeric_tokens) >= 8:
        return True
    short_tokens = paragraph.split()
    if 3 <= len(short_tokens) <= 12 and all(len(token) <= 10 for token in short_tokens):
        if sum(token[:1].isdigit() or token.isupper() for token in short_tokens) >= len(short_tokens) - 2:
            return True
    if re.match(r"^\([a-z]\)\s", lowered):
        return True
    return False


def _is_abstract_noise_paragraph(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if _is_author_or_affiliation_paragraph(paragraph):
        return True
    if _is_running_header_footer_paragraph(paragraph):
        return True
    if DOI_PATTERN.search(paragraph):
        return True
    if re.fullmatch(r"\d{3,5}/[\w./-]+", paragraph.strip()):
        return True
    if lowered.startswith(("keywords", "keyword")):
        return True
    if paragraph.count(",") >= 3 and len(paragraph.split()) <= 20:
        return True
    if "conference on human factors" in lowered or "proceedings of" in lowered:
        return True
    if lowered.startswith(("acm reference format", "recommended citation", "copyright")):
        return True
    return False


def _normalize_heading_if_needed(paragraph: str) -> str:
    match = HEADING_PATTERN.match(paragraph)
    if not match:
        return paragraph
    section_number = match.group(1)
    heading = match.group(2)
    normalized_heading = " ".join(word.capitalize() for word in heading.split())
    if section_number:
        return f"{section_number} {normalized_heading}"
    return normalized_heading


def _cleanup_text(text: str) -> str:
    paragraphs = [normalize_text(part) for part in text.split("\n\n")]
    paragraphs = [part for part in paragraphs if part and not _is_redundant_paragraph(part)]
    return "\n\n".join(paragraphs)


def _is_redundant_paragraph(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if lowered in {"keywords", "ccs concepts"}:
        return True
    if re.fullmatch(r"[0-9]+", paragraph):
        return True
    return False


def _extract_references(pages: list[PageText]) -> str | None:
    collecting = False
    references_parts: list[str] = []
    for page in pages:
        paragraphs = [part for part in page.text.split("\n\n") if part.strip()]
        for paragraph in paragraphs:
            if not collecting and _is_references_heading(paragraph):
                collecting = True
                continue
            if not collecting and _split_inline_references(paragraph) is not None:
                collecting = True
                _, ref_part = _split_inline_references(paragraph)
                if ref_part:
                    references_parts.append(ref_part)
                continue
            if collecting:
                references_parts.append(paragraph)
    if not references_parts:
        return None
    return _cleanup_text("\n\n".join(references_parts)) or None


def _remove_reference_content_from_pages(pages: list[PageText]) -> list[PageText]:
    collecting = False
    result: list[PageText] = []
    for page in pages:
        paragraphs = [part for part in page.text.split("\n\n") if part.strip()]
        kept: list[str] = []
        for paragraph in paragraphs:
            if not collecting and _is_references_heading(paragraph):
                collecting = True
                continue
            if not collecting and _split_inline_references(paragraph) is not None:
                collecting = True
                body_part, _ = _split_inline_references(paragraph)
                if body_part:
                    kept.append(body_part)
                continue
            if not collecting:
                kept.append(paragraph)
        result.append(PageText(number=page.number, text=_cleanup_text("\n\n".join(kept)), visuals=page.visuals))
    return result


def _drop_meaningless_front_pages(pages: list[PageText]) -> list[PageText]:
    result: list[PageText] = []
    for index, page in enumerate(pages, start=1):
        text = page.text.strip()
        if index <= 2 and text:
            paragraphs = [part for part in text.split("\n\n") if part.strip()]
            if all(_is_author_or_affiliation_paragraph(paragraph) or _is_front_matter_paragraph(paragraph, index) for paragraph in paragraphs):
                text = ""
        result.append(PageText(number=page.number, text=text, visuals=page.visuals))
    return result


def _is_references_heading(paragraph: str) -> bool:
    normalized = paragraph.strip().lower()
    return normalized in {"references", "reference"} or bool(re.fullmatch(r"\d+\s+references", normalized))


def _split_inline_references(paragraph: str) -> tuple[str, str] | None:
    match = re.search(r"(?:(?<=^)|(?<=[.!?]\s))References\s+(?=\[\d+\]|\d+\.\s|[A-Z][a-z])", paragraph)
    if not match:
        return None
    before = paragraph[: match.start()].strip()
    after = paragraph[match.end() :].strip()
    if not after:
        return None
    return before, after


def _extract_title(pdf_path: Path, pages: list[PageText], metadata_title: str | None) -> str | None:
    if metadata_title and _is_plausible_title(metadata_title):
        return metadata_title

    visual_title = _extract_visual_title_candidate(pdf_path)
    if visual_title and _is_plausible_title(visual_title):
        return visual_title

    paragraph_title = _extract_paragraph_title_candidate(pages)
    if paragraph_title and _is_plausible_title(paragraph_title):
        return paragraph_title
    return None


def _extract_metadata_title(pdf_path: Path) -> str | None:
    with fitz.open(pdf_path) as document:
        raw_title = (document.metadata or {}).get("title") or ""
    normalized = _normalize_unicode(raw_title)
    if not normalized:
        return None
    return normalized


def _extract_visual_title_candidate(pdf_path: Path) -> str | None:
    with fitz.open(pdf_path) as document:
        candidates: list[tuple[float, str]] = []
        for page_number, page in enumerate(document[:2], start=1):
            page_dict = page.get_text("dict", sort=False)
            for block in _collect_text_blocks(page_dict):
                text = re.sub(r"^RESEARCH-ARTICLE\s+", "", block.text, flags=re.IGNORECASE).strip()
                if not text or not _is_plausible_title(text):
                    continue
                vertical_score = max(0.0, 180.0 - block.y0) / 20.0
                center_distance = abs(block.center_x - page.rect.width / 2)
                center_score = max(0.0, 120.0 - center_distance) / 15.0
                page_score = 3.0 if page_number == 1 else 1.5
                score = block.max_font_size * 2.0 + vertical_score + center_score + page_score
                candidates.append((score, text))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        return candidates[0][1]


def _extract_paragraph_title_candidate(pages: list[PageText]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for page_index, page in enumerate(pages[:2], start=1):
        for paragraph in [part for part in page.text.split("\n\n") if part.strip()]:
            paragraph = re.sub(r"^RESEARCH-ARTICLE\s+", "", paragraph, flags=re.IGNORECASE)
            if not _is_plausible_title(paragraph):
                continue
            score = 0
            lowered = paragraph.lower()
            if "investigating" in lowered or "effects" in lowered:
                score += 5
            if paragraph.endswith("?"):
                score += 3
            if page_index == 1:
                score += 2
            if len(paragraph.split()) <= 18:
                score += 4
            candidates.append((score, paragraph))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    return candidates[0][1]


def _is_plausible_title(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    if HEADING_PATTERN.match(text):
        return False
    if _is_front_matter_paragraph(text, 1):
        return False
    if _is_noise_paragraph(text):
        return False
    if _is_author_or_affiliation_paragraph(text):
        return False
    if _is_table_like_paragraph(text):
        return False
    if lowered.startswith(("abstract", "keywords", "acm reference format", "references")):
        return False
    if re.match(r"^[A-Z]\.\s", text):
        return False
    if len(text.split()) < 4 or len(text.split()) > 24:
        return False
    if text.endswith("."):
        return False
    if DOI_PATTERN.search(text):
        return False
    return True


def _extract_doi(pages: list[PageText]) -> str | None:
    for page in pages[:2]:
        match = DOI_PATTERN.search(page.text)
        if match:
            return match.group(0)
    return None


def _is_figure_caption_paragraph(paragraph: str) -> bool:
    return bool(re.match(r"^(Figure|Fig\.|Table)\s+\d+[:.]?", paragraph, re.IGNORECASE))


def _find_repeated_header_like_paragraphs(pages: list[PageText]) -> set[str]:
    counts: dict[str, int] = {}
    for page in pages:
        for paragraph in [part.strip() for part in page.text.split("\n\n") if part.strip()]:
            normalized = _normalize_unicode(paragraph)
            if len(normalized) > 140:
                continue
            counts[normalized] = counts.get(normalized, 0) + 1

    repeated: set[str] = set()
    for paragraph, count in counts.items():
        lowered = paragraph.lower()
        if count < 2:
            continue
        if "chi" in lowered or "rasch et al" in lowered:
            repeated.add(paragraph)
        elif lowered.endswith("japan"):
            repeated.add(paragraph)
        elif lowered.startswith("ar you on track?"):
            repeated.add(paragraph)
    return repeated


def _is_main_section_heading(paragraph: str) -> bool:
    match = HEADING_PATTERN.match(paragraph)
    return bool(match and match.group(2).lower() in SECTION_HEADINGS)


def _looks_like_title(paragraph: str) -> bool:
    lowered = paragraph.lower()
    if lowered.startswith(("pdf download", "latest updates", "published:", "chi ")):
        return False
    if len(paragraph) < 25:
        return False
    if paragraph.count("@") > 0:
        return False
    return paragraph.endswith("?") or paragraph.istitle() or "investigating" in lowered


def _has_meaningful_text(pages: list[PageText]) -> bool:
    meaningful_chars = sum(len(page.text.replace("[NO TEXT EXTRACTED]", "").strip()) for page in pages)
    return meaningful_chars >= 20


def _count_pages(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)
