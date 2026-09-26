from __future__ import annotations

import difflib
import hashlib
import html
import json
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pymupdf
from PIL import Image, ImageChops, ImageDraw
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as ReportImage,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


Logger = Callable[[str], None]
CancelChecker = Callable[[], None]
RENDER_DPI = 200


@dataclass(frozen=True)
class PdfPageComparison:
    page_number: int
    status: str
    old_present: bool
    new_present: bool
    text_identical: bool
    visual_identical: bool
    fields_identical: bool
    old_text_sha256: str
    new_text_sha256: str
    old_visual_sha256: str
    new_visual_sha256: str
    difference_pixels: int
    total_pixels: int
    difference_ratio: float
    difference_regions: list[list[int]]


@dataclass(frozen=True)
class PdfCompareResult:
    old_path: Path
    new_path: Path
    output_path: Path
    manifest_path: Path
    verdict: str
    identical: bool
    binary_identical: bool
    text_identical: bool
    visual_identical: bool
    fields_identical: bool
    old_sha256: str
    new_sha256: str
    old_page_count: int
    new_page_count: int
    compared_page_count: int
    different_page_count: int
    difference_region_count: int


def compare_pdf_files(
    old_path: str | Path,
    new_path: str | Path,
    output_path: str | Path,
    *,
    log: Logger | None = None,
    cancel: CancelChecker | None = None,
) -> PdfCompareResult:
    logger = log or (lambda _message: None)
    cancel_checker = cancel or (lambda: None)
    old_file = _validate_pdf(old_path, "File PDF cũ")
    new_file = _validate_pdf(new_path, "File PDF mới")
    destination = _validate_output(output_path, old_file, new_file)
    manifest_path = destination.with_suffix(".json")
    destination.parent.mkdir(parents=True, exist_ok=True)

    old_hash = _sha256_file(old_file)
    new_hash = _sha256_file(new_file)
    binary_identical = old_hash == new_hash

    logger(f"Đang đọc PDF cũ: {old_file.name}")
    old_document = pymupdf.open(old_file)
    try:
        logger(f"Đang đọc PDF mới: {new_file.name}")
        new_document = pymupdf.open(new_file)
        try:
            _require_unlocked(old_document, old_file)
            _require_unlocked(new_document, new_file)
            old_count = old_document.page_count
            new_count = new_document.page_count
            page_count = max(old_count, new_count)
            page_results: list[PdfPageComparison] = []
            report_pages: list[dict[str, Any]] = []

            with tempfile.TemporaryDirectory(prefix=".autocompare-pdf-", dir=destination.parent) as temp_dir:
                temp_root = Path(temp_dir)
                for page_index in range(page_count):
                    cancel_checker()
                    old_page = old_document[page_index] if page_index < old_count else None
                    new_page = new_document[page_index] if page_index < new_count else None
                    result, assets = _compare_page(old_page, new_page, page_index + 1, temp_root)
                    page_results.append(result)
                    if result.status != "IDENTICAL":
                        report_pages.append(assets)
                    logger(
                        f"[{page_index + 1}/{page_count}] Trang {page_index + 1}: "
                        f"{result.status}; {len(result.difference_regions)} vùng khác biệt."
                    )

                text_identical = old_count == new_count and all(item.text_identical for item in page_results)
                visual_identical = old_count == new_count and all(item.visual_identical for item in page_results)
                fields_identical = old_count == new_count and all(item.fields_identical for item in page_results)
                identical = text_identical and visual_identical and fields_identical
                verdict = "BINARY IDENTICAL" if binary_identical else ("CONTENT IDENTICAL" if identical else "DIFFERENT")
                different_pages = sum(item.status != "IDENTICAL" for item in page_results)
                region_count = sum(len(item.difference_regions) for item in page_results)

                result = PdfCompareResult(
                    old_path=old_file,
                    new_path=new_file,
                    output_path=destination,
                    manifest_path=manifest_path,
                    verdict=verdict,
                    identical=identical,
                    binary_identical=binary_identical,
                    text_identical=text_identical,
                    visual_identical=visual_identical,
                    fields_identical=fields_identical,
                    old_sha256=old_hash,
                    new_sha256=new_hash,
                    old_page_count=old_count,
                    new_page_count=new_count,
                    compared_page_count=page_count,
                    different_page_count=different_pages,
                    difference_region_count=region_count,
                )
                cancel_checker()
                _write_report(result, page_results, report_pages, temp_root)
                _write_manifest(result, page_results)
        finally:
            new_document.close()
    finally:
        old_document.close()

    logger(f"Đã tạo báo cáo Compare PDF: {destination}")
    logger(f"Đã tạo manifest kiểm chứng: {manifest_path}")
    return result


def _validate_pdf(path_value: str | Path, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} không tồn tại: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"{label} phải có định dạng PDF.")
    return path


def _validate_output(path_value: str | Path, old_path: Path, new_path: Path) -> Path:
    raw = str(path_value).strip()
    if not raw:
        raise ValueError("Vui lòng chọn file báo cáo PDF kết quả.")
    path = Path(raw).expanduser()
    if path.suffix.lower() != ".pdf":
        path = path.with_suffix(".pdf")
    path = path.resolve()
    if path in {old_path, new_path}:
        raise ValueError("File báo cáo phải khác hai file PDF nguồn.")
    return path


def _require_unlocked(document: pymupdf.Document, path: Path) -> None:
    if document.needs_pass:
        raise ValueError(f"PDF đang được bảo vệ bằng mật khẩu: {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compare_page(
    old_page: pymupdf.Page | None,
    new_page: pymupdf.Page | None,
    page_number: int,
    temp_root: Path,
) -> tuple[PdfPageComparison, dict[str, Any]]:
    old_text, old_fields = _semantic_page(old_page)
    new_text, new_fields = _semantic_page(new_page)
    old_image = _render_page(old_page)
    new_image = _render_page(new_page)
    old_canvas, new_canvas = _same_canvas(old_image, new_image)
    difference = ImageChops.difference(old_canvas, new_canvas)
    mask = _difference_mask(difference)
    difference_pixels = mask.histogram()[255]
    total_pixels = max(1, mask.width * mask.height)
    regions = _difference_regions(mask)

    old_text_hash = _sha256_text(old_text)
    new_text_hash = _sha256_text(new_text)
    old_visual_hash = _sha256_bytes(old_canvas.tobytes())
    new_visual_hash = _sha256_bytes(new_canvas.tobytes())
    text_identical = old_text == new_text
    fields_identical = old_fields == new_fields
    visual_identical = difference_pixels == 0
    page_identical = (
        old_page is not None
        and new_page is not None
        and text_identical
        and fields_identical
        and visual_identical
    )
    status = "IDENTICAL" if page_identical else "DIFFERENT"

    prefix = temp_root / f"page-{page_number:04d}"
    old_asset = prefix.with_name(f"{prefix.name}-old.png")
    new_asset = prefix.with_name(f"{prefix.name}-new.png")
    diff_asset = prefix.with_name(f"{prefix.name}-diff.png")
    zoom_asset = prefix.with_name(f"{prefix.name}-regions.png")
    old_canvas.save(old_asset, optimize=True)
    new_canvas.save(new_asset, optimize=True)
    highlighted = _highlight_differences(old_canvas, new_canvas, mask, regions)
    highlighted.save(diff_asset, optimize=True)
    _region_contact_sheet(highlighted, regions).save(zoom_asset, optimize=True)

    result = PdfPageComparison(
        page_number=page_number,
        status=status,
        old_present=old_page is not None,
        new_present=new_page is not None,
        text_identical=text_identical,
        visual_identical=visual_identical,
        fields_identical=fields_identical,
        old_text_sha256=old_text_hash,
        new_text_sha256=new_text_hash,
        old_visual_sha256=old_visual_hash,
        new_visual_sha256=new_visual_hash,
        difference_pixels=difference_pixels,
        total_pixels=total_pixels,
        difference_ratio=difference_pixels / total_pixels,
        difference_regions=[list(region) for region in regions],
    )
    return result, {
        "result": result,
        "old_image": old_asset,
        "new_image": new_asset,
        "diff_image": diff_asset,
        "zoom_image": zoom_asset,
        "text_diff": _text_diff(old_text, new_text),
    }


def _semantic_page(page: pymupdf.Page | None) -> tuple[str, str]:
    if page is None:
        return "", "[]"
    text = page.get_text("text", sort=True)
    widgets = []
    widget = page.first_widget
    while widget is not None:
        widgets.append({
            "name": widget.field_name or "",
            "type": widget.field_type_string or "",
            "value": str(widget.field_value or ""),
            "rect": _rect_values(widget.rect),
        })
        widget = widget.next
    annotations = []
    annotation = page.first_annot
    while annotation is not None:
        info = annotation.info or {}
        annotations.append({
            "type": annotation.type[1] if annotation.type else "",
            "content": str(info.get("content", "")),
            "title": str(info.get("title", "")),
            "subject": str(info.get("subject", "")),
            "rect": _rect_values(annotation.rect),
        })
        annotation = annotation.next
    payload = json.dumps(
        {"widgets": widgets, "annotations": annotations},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text, payload


def _rect_values(rect: pymupdf.Rect) -> list[float]:
    return [round(float(value), 4) for value in (rect.x0, rect.y0, rect.x1, rect.y1)]


def _render_page(page: pymupdf.Page | None) -> Image.Image | None:
    if page is None:
        return None
    scale = RENDER_DPI / 72
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False, annots=True)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _same_canvas(old_image: Image.Image | None, new_image: Image.Image | None) -> tuple[Image.Image, Image.Image]:
    width = max(old_image.width if old_image else 1, new_image.width if new_image else 1)
    height = max(old_image.height if old_image else 1, new_image.height if new_image else 1)

    def canvas(image: Image.Image | None) -> Image.Image:
        output = Image.new("RGB", (width, height), "white")
        if image is not None:
            output.paste(image, (0, 0))
        return output

    return canvas(old_image), canvas(new_image)


def _difference_mask(difference: Image.Image) -> Image.Image:
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return maximum.point(lambda value: 255 if value else 0, mode="L")


def _difference_regions(mask: Image.Image, tile_size: int = 24) -> list[tuple[int, int, int, int]]:
    active: set[tuple[int, int]] = set()
    tiles_x = (mask.width + tile_size - 1) // tile_size
    tiles_y = (mask.height + tile_size - 1) // tile_size
    for tile_y in range(tiles_y):
        for tile_x in range(tiles_x):
            box = (
                tile_x * tile_size,
                tile_y * tile_size,
                min(mask.width, (tile_x + 1) * tile_size),
                min(mask.height, (tile_y + 1) * tile_size),
            )
            if mask.crop(box).getbbox():
                active.add((tile_x, tile_y))

    regions: list[tuple[int, int, int, int]] = []
    while active:
        start = active.pop()
        stack = [start]
        component = [start]
        while stack:
            tile_x, tile_y = stack.pop()
            for neighbor in ((tile_x - 1, tile_y), (tile_x + 1, tile_y), (tile_x, tile_y - 1), (tile_x, tile_y + 1)):
                if neighbor in active:
                    active.remove(neighbor)
                    stack.append(neighbor)
                    component.append(neighbor)
        min_x = min(item[0] for item in component) * tile_size
        min_y = min(item[1] for item in component) * tile_size
        max_x = min(mask.width, (max(item[0] for item in component) + 1) * tile_size)
        max_y = min(mask.height, (max(item[1] for item in component) + 1) * tile_size)
        regions.append((min_x, min_y, max_x, max_y))
    return sorted(regions, key=lambda region: (region[1], region[0]))


def _highlight_differences(
    old_image: Image.Image,
    new_image: Image.Image,
    mask: Image.Image,
    regions: list[tuple[int, int, int, int]],
) -> Image.Image:
    base = Image.blend(old_image, new_image, 0.5)
    red_tint = Image.blend(base, Image.new("RGB", base.size, (239, 68, 68)), 0.68)
    output = Image.composite(red_tint, base, mask)
    draw = ImageDraw.Draw(output)
    line_width = max(3, round(RENDER_DPI / 50))
    for region in regions:
        draw.rectangle(region, outline=(185, 28, 28), width=line_width)
    return output


def _region_contact_sheet(image: Image.Image, regions: list[tuple[int, int, int, int]]) -> Image.Image:
    selected = regions[:4] or [(0, 0, image.width, image.height)]
    tile_width, tile_height = 700, 360
    columns = 2
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, region in enumerate(selected):
        crop_box = _expanded_crop(region, image.size)
        crop = image.crop(crop_box)
        crop.thumbnail((tile_width - 24, tile_height - 42), Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = column * tile_width + (tile_width - crop.width) // 2
        y = row * tile_height + 30 + (tile_height - 36 - crop.height) // 2
        sheet.paste(crop, (x, y))
        draw.text((column * tile_width + 12, row * tile_height + 9), f"Region {index + 1}", fill=(139, 47, 55))
        draw.rectangle(
            (column * tile_width + 4, row * tile_height + 4, (column + 1) * tile_width - 5, (row + 1) * tile_height - 5),
            outline=(214, 222, 232),
            width=2,
        )
    return sheet


def _expanded_crop(region: tuple[int, int, int, int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = region
    width, height = image_size
    padding_x = max(320, (x1 - x0) * 3)
    padding_y = max(90, (y1 - y0) * 2)
    return (
        max(0, x0 - padding_x),
        max(0, y0 - padding_y),
        min(width, x1 + padding_x),
        min(height, y1 + padding_y),
    )


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text_diff(old_text: str, new_text: str, limit: int = 28) -> list[str]:
    lines = list(difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile="Old",
        tofile="New",
        lineterm="",
        n=2,
    ))
    if len(lines) > limit:
        return [*lines[:limit], f"... {len(lines) - limit} more lines omitted ..."]
    return lines


def _write_report(
    result: PdfCompareResult,
    pages: list[PdfPageComparison],
    report_pages: list[dict[str, Any]],
    temp_root: Path,
) -> None:
    regular_font, bold_font = _register_report_fonts()
    page_size = landscape(A4)
    temp_output = temp_root / "compare-report.pdf"
    document = SimpleDocTemplate(
        str(temp_output),
        pagesize=page_size,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=13 * mm,
        bottomMargin=13 * mm,
        title="AutoCompare PDF Comparison Report",
        author="AutoCompare",
    )
    styles = _report_styles(regular_font, bold_font)
    story: list[Any] = []
    verdict_color = colors.HexColor("#16794A") if result.identical else colors.HexColor("#B4232D")
    story.extend([
        Paragraph("PDF Comparison Report", styles["title"]),
        Paragraph(
            f'<font color="{verdict_color.hexval()}"><b>{result.verdict}</b></font>',
            styles["verdict"],
        ),
        Spacer(1, 4 * mm),
    ])
    file_table = Table([
        [Paragraph("", styles["small"]), Paragraph("Old", styles["table_header"]), Paragraph("New", styles["table_header"])],
        [Paragraph("File", styles["table_header"]), Paragraph(html.escape(result.old_path.name), styles["body"]), Paragraph(html.escape(result.new_path.name), styles["body"])],
        [Paragraph("Pages", styles["table_header"]), str(result.old_page_count), str(result.new_page_count)],
        [Paragraph("SHA-256", styles["table_header"]), Paragraph(result.old_sha256, styles["hash"]), Paragraph(result.new_sha256, styles["hash"])],
    ], colWidths=[30 * mm, 112 * mm, 112 * mm])
    file_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2FB")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D6E4")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("FONTNAME", (0, 0), (-1, -1), regular_font),
    ]))
    story.extend([
        file_table,
        Spacer(1, 5 * mm),
        Paragraph(
            "Identity rule: page count, extracted text, rendered pixels at 200 DPI, form field values, and annotation values must all match. "
            "File SHA-256 proves byte-for-byte identity; content identity may still pass when only PDF metadata or object encoding differs.",
            styles["note"],
        ),
        Spacer(1, 5 * mm),
    ])

    summary_rows: list[list[Any]] = [["Page", "Status", "Text", "Visual", "Fields", "Diff pixels", "Regions"]]
    for page in pages:
        summary_rows.append([
            str(page.page_number),
            page.status,
            _yes_no(page.text_identical),
            _yes_no(page.visual_identical),
            _yes_no(page.fields_identical),
            f"{page.difference_pixels:,} ({page.difference_ratio:.6%})",
            str(len(page.difference_regions)),
        ])
    summary_table = LongTable(summary_rows, repeatRows=1, colWidths=[15 * mm, 28 * mm, 22 * mm, 22 * mm, 22 * mm, 55 * mm, 20 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244A73")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("FONTNAME", (0, 1), (-1, -1), regular_font),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D4DEE8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F9FC")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([Paragraph("Page summary", styles["heading"]), summary_table])

    for page_assets in report_pages:
        page = page_assets["result"]
        story.extend([PageBreak(), Paragraph(f"Page {page.page_number} - Differences", styles["heading"]), Spacer(1, 2 * mm)])
        image_width = 80 * mm
        image_height = 95 * mm
        panels = []
        for label, path in (("Old", page_assets["old_image"]), ("New", page_assets["new_image"]), ("Diff highlight", page_assets["diff_image"])):
            image = _report_image(path, image_width, image_height)
            panels.append([Paragraph(label, styles["panel_label"]), Spacer(1, 1 * mm), image])
        panel_table = Table([panels], colWidths=[86 * mm, 86 * mm, 86 * mm])
        panel_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.extend([
            panel_table,
            Spacer(1, 3 * mm),
            Paragraph(
                f"Text: {_yes_no(page.text_identical)} | Visual: {_yes_no(page.visual_identical)} | "
                f"Fields/annotations: {_yes_no(page.fields_identical)} | "
                f"Changed pixels: {page.difference_pixels:,} ({page.difference_ratio:.6%}) | "
                f"Regions: {len(page.difference_regions)}",
                styles["small"],
            ),
        ])
        story.extend([PageBreak(), Paragraph(f"Page {page.page_number} - Difference details", styles["heading"]), Spacer(1, 2 * mm)])
        if page.difference_regions:
            story.extend([
                Paragraph(
                    f"Zoomed context for the first {min(4, len(page.difference_regions))} of {len(page.difference_regions)} detected regions.",
                    styles["note"],
                ),
                Spacer(1, 2 * mm),
                _report_image(page_assets["zoom_image"], 250 * mm, 118 * mm),
            ])
        else:
            story.append(Paragraph("No pixel region changed; this page differs only in extracted semantic content.", styles["note"]))
        text_diff = page_assets["text_diff"]
        if text_diff:
            diff_text = "<br/>".join(html.escape(line) or "&nbsp;" for line in text_diff)
            story.extend([Spacer(1, 2 * mm), Paragraph("Extracted text diff", styles["subheading"]), Paragraph(diff_text, styles["diff"])])
        elif not page.visual_identical:
            story.extend([Spacer(1, 2 * mm), Paragraph("No extracted text change; the difference is visual/layout content.", styles["note"])])

    document.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    temp_output.replace(result.output_path)


def _report_image(path: Path, max_width: float, max_height: float) -> ReportImage:
    with Image.open(path) as source:
        width, height = source.size
    scale = min(max_width / max(1, width), max_height / max(1, height))
    return ReportImage(str(path), width=width * scale, height=height * scale)


def _register_report_fonts() -> tuple[str, str]:
    candidates = [
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for regular_path, bold_path in candidates:
        if regular_path.is_file() and bold_path.is_file():
            pdfmetrics.registerFont(TTFont("AutoCompare", str(regular_path)))
            pdfmetrics.registerFont(TTFont("AutoCompare-Bold", str(bold_path)))
            return "AutoCompare", "AutoCompare-Bold"
    return "Helvetica", "Helvetica-Bold"


def _report_styles(regular_font: str, bold_font: str) -> dict[str, ParagraphStyle]:
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("PdfTitle", parent=sample["Title"], fontName=bold_font, fontSize=22, leading=26, textColor=colors.HexColor("#183B5B"), alignment=TA_LEFT),
        "verdict": ParagraphStyle("PdfVerdict", parent=sample["Heading2"], fontName=bold_font, fontSize=14, leading=18, alignment=TA_LEFT),
        "heading": ParagraphStyle("PdfHeading", parent=sample["Heading2"], fontName=bold_font, fontSize=14, leading=18, textColor=colors.HexColor("#244A73")),
        "subheading": ParagraphStyle("PdfSubheading", parent=sample["Heading3"], fontName=bold_font, fontSize=9, leading=12, textColor=colors.HexColor("#334E68")),
        "body": ParagraphStyle("PdfBody", parent=sample["BodyText"], fontName=regular_font, fontSize=9, leading=12),
        "small": ParagraphStyle("PdfSmall", parent=sample["BodyText"], fontName=regular_font, fontSize=8, leading=10),
        "note": ParagraphStyle("PdfNote", parent=sample["BodyText"], fontName=regular_font, fontSize=8, leading=11, textColor=colors.HexColor("#52657A")),
        "hash": ParagraphStyle("PdfHash", parent=sample["Code"], fontName="Courier", fontSize=6.5, leading=8),
        "table_header": ParagraphStyle("PdfTableHeader", parent=sample["BodyText"], fontName=bold_font, fontSize=8, leading=10),
        "panel_label": ParagraphStyle("PdfPanelLabel", parent=sample["BodyText"], fontName=bold_font, fontSize=9, leading=12, alignment=TA_CENTER),
        "diff": ParagraphStyle("PdfDiff", parent=sample["Code"], fontName=regular_font, fontSize=6.5, leading=8, backColor=colors.HexColor("#F7F9FB"), borderColor=colors.HexColor("#D7E0E9"), borderWidth=0.5, borderPadding=5),
    }


def _page_footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#718096"))
    canvas.drawString(14 * mm, 8 * mm, "AutoCompare PDF evidence report")
    canvas.drawRightString(landscape(A4)[0] - 14 * mm, 8 * mm, f"Page {document.page}")
    canvas.restoreState()


def _yes_no(value: bool) -> str:
    return "MATCH" if value else "DIFF"


def _write_manifest(result: PdfCompareResult, pages: list[PdfPageComparison]) -> None:
    payload = {
        "schema": "autocompare.pdf-comparison.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": {
            "binary_hash": "SHA-256",
            "text": "PyMuPDF text extraction with sort=True; exact UTF-8 SHA-256",
            "visual": f"PyMuPDF RGB render at {RENDER_DPI} DPI; exact pixel comparison",
            "semantic_extras": "Exact form field and annotation value/position comparison",
        },
        "summary": _jsonable_dataclass(result),
        "pages": [asdict(page) for page in pages],
    }
    temporary = result.manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(result.manifest_path)


def _jsonable_dataclass(value: Any) -> dict[str, Any]:
    return {
        key: str(item) if isinstance(item, Path) else item
        for key, item in asdict(value).items()
    }
