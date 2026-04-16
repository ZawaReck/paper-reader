from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image

from paper_reader.extractor import _merge_wrapped_lines, _normalize_unicode, extract_pdf, write_result
from paper_reader.models import ExtractionOptions


def create_sample_pdf(path: Path, text_by_page: list[str]) -> None:
    document = fitz.open()
    for text in text_by_page:
        page = document.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 520, 760), text)
    document.save(path)
    document.close()


def create_pdf_with_image_and_caption(path: Path, image_path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Main body text for image supplement testing.")
    page.insert_image(fitz.Rect(72, 120, 240, 260), filename=str(image_path))
    page.insert_text((72, 285), "Figure 1. Sample chart of model performance.")
    document.save(path)
    document.close()


def create_two_column_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(60, 60, 535, 120),
        "Sample Two-Column Paper\n\nAbstract",
    )
    page.insert_textbox(
        fitz.Rect(60, 140, 265, 420),
        (
            "Left column paragraph one continues the abstract and should appear first.\n\n"
            "1 Introduction\nThe introduction begins here and stays in the left column.\n\n"
            "2 Related Work\nRelated work subsection 2.1 appears before the right column text."
        ),
    )
    page.insert_textbox(
        fitz.Rect(330, 140, 535, 420),
        (
            "Right column paragraph should appear only after the full left column is read.\n\n"
            "2.1 Prior Systems\nThis subsection belongs after the left-column Related Work heading.\n\n"
            "3 Methodology\nMethod details start in the right column."
        ),
    )
    document.save(path)
    document.close()


def create_title_and_table_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(90, 70, 505, 130),
        "A Better Paper Title for Testing",
        fontsize=20,
        align=1,
    )
    page.insert_textbox(
        fitz.Rect(120, 145, 475, 210),
        "Alice Example\nExample University\nalice@example.com",
        fontsize=11,
        align=1,
    )
    page.insert_textbox(
        fitz.Rect(72, 240, 520, 340),
        "Abstract\nThis abstract should remain readable without affiliation noise.",
        fontsize=12,
    )
    page.insert_textbox(
        fitz.Rect(72, 360, 520, 470),
        "Table 1: Summary\nM SD M SD\n1.0 0.2 2.0 0.3\n3.0 0.4 4.0 0.5",
        fontsize=11,
    )
    document.save(path)
    document.close()


def test_extract_single_pdf_creates_txt(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    create_sample_pdf(pdf_path, ["First page text for testing extraction quality."])

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)

    assert written.exists()
    content = written.read_text(encoding="utf-8")
    assert "SOURCE:" in content
    assert "METHOD: pymupdf" in content
    assert "MODE: ai-readable" in content
    assert "===== PAGE 1 =====" in content
    assert "First page text for testing extraction quality." in content


def test_extract_directory_like_inputs(tmp_path: Path) -> None:
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    create_sample_pdf(pdf_a, ["Alpha text that is long enough to count as meaningful extraction."])
    create_sample_pdf(pdf_b, ["Beta text that is also long enough to count as meaningful extraction."])

    paths = sorted(tmp_path.glob("*.pdf"))

    assert [path.name for path in paths] == ["a.pdf", "b.pdf"]


def test_visual_hints_are_hidden_by_default(tmp_path: Path) -> None:
    pdf_path = tmp_path / "figure-paper.pdf"
    image_path = tmp_path / "figure.png"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()

    image = Image.new("RGB", (64, 64), color="red")
    image.save(image_path)
    create_pdf_with_image_and_caption(pdf_path, image_path)

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    assert "[VISUAL SUPPLEMENTS]" not in content
    assert "detected at bbox=" not in content


def test_visual_hints_can_be_enabled_in_ai_readable_mode(tmp_path: Path) -> None:
    pdf_path = tmp_path / "figure-paper.pdf"
    image_path = tmp_path / "figure.png"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()

    image = Image.new("RGB", (64, 64), color="red")
    image.save(image_path)
    create_pdf_with_image_and_caption(pdf_path, image_path)

    result = extract_pdf(pdf_path, ExtractionOptions(include_visual_hints=True))
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    assert "[FIGURE CAPTION]" in content or "Figure 1. Sample chart of model performance." in content
    assert "detected at bbox=" not in content


def test_merge_wrapped_lines_restores_sentence_flow() -> None:
    merged = _merge_wrapped_lines(
        [
            "With the increasing spread of AR head-mounted displays suitable",
            "for everyday use, interaction with information becomes ubiquitous,",
            "even while walking.",
        ]
    )

    assert (
        merged
        == "With the increasing spread of AR head-mounted displays suitable for everyday use, interaction with information becomes ubiquitous, even while walking."
    )


def test_extract_separates_references_in_ai_mode(tmp_path: Path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    create_sample_pdf(
        pdf_path,
        [
            "Sample Paper Title\n\nAbstract\nThis is the abstract.\n\n1 Introduction\nThis is the introduction.",
            "2 Method\nMethod details.\n\nReferences\n[1] Prior work.",
        ],
    )

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    assert "===== REFERENCES =====" in content
    assert "[1] Prior work." in content
    body_part = content.split("===== REFERENCES =====")[0]
    assert "References" not in body_part


def test_normalize_unicode_repairs_ligatures_and_broken_https() -> None:
    normalized = _normalize_unicode("Eﬀects of AR are shown at hps://example.com in the ﬁnal study.")

    assert normalized == "Effects of AR are shown at https://example.com in the final study."


def test_extract_restores_two_column_reading_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two-column.pdf"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    create_two_column_pdf(pdf_path)

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    left_anchor = "2 Related Work"
    right_anchor = "Right column paragraph should appear only after the full left column is read."
    intro_anchor = "1 Introduction"
    method_anchor = "3 Methodology"

    assert content.index(intro_anchor) < content.index(left_anchor)
    assert content.index(left_anchor) < content.index(right_anchor)
    assert content.index(right_anchor) < content.index(method_anchor)


def test_extract_prefers_visual_title_and_drops_affiliation_noise(tmp_path: Path) -> None:
    pdf_path = tmp_path / "title.pdf"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    create_title_and_table_pdf(pdf_path)

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    assert "TITLE: A Better Paper Title for Testing" in content
    assert "alice@example.com" not in content
    assert "Example University" not in content
    assert "This abstract should remain readable" in content


def test_extract_hides_table_like_blocks_by_default(tmp_path: Path) -> None:
    pdf_path = tmp_path / "table.pdf"
    output_dir = tmp_path / "texts"
    output_dir.mkdir()
    create_title_and_table_pdf(pdf_path)

    result = extract_pdf(pdf_path, ExtractionOptions())
    written = write_result(result, output_dir)
    content = written.read_text(encoding="utf-8")

    assert "M SD M SD" not in content
    assert "1.0 0.2 2.0 0.3" not in content
