from __future__ import annotations

from io import BytesIO
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 60
MARGIN_TOP = 70
MARGIN_BOTTOM = 60

BRAND_BLUE = colors.HexColor("#005BFF")
INK = colors.HexColor("#121212")
MUTED = colors.HexColor("#737373")
LINE = colors.HexColor("#d9dce1")
PAPER = colors.HexColor("#ffffff")
SECTION_TINT = colors.HexColor("#f0f4ff")
TABLE_HEADER = colors.HexColor("#e6f0ff")
TABLE_ALT_ROW = colors.HexColor("#f8fafe")


def markdown_to_pdf(markdown_text: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=MARGIN_X,
        leftMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="Minutes of Meeting",
        author="Minutes of Meeting Tool",
    )
    styles = _pdf_styles()
    story = []
    lines = markdown_text.splitlines()
    index = 0

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 8))
            index += 1
            continue
        if _is_table_start(lines, index):
            table_lines = []
            while index < len(lines) and _is_table_line(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            story.append(_build_table(table_lines, styles))
            story.append(Spacer(1, 10))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_inline_markdown(line[2:]), styles["MomTitle"]))
            story.append(Spacer(1, 12))
        elif line.startswith("## "):
            story.append(Spacer(1, 8))
            story.append(Paragraph(_inline_markdown(line[3:]), styles["MomHeading2"]))
        elif line.startswith("- "):
            story.append(Paragraph(_inline_markdown(line[2:]), styles["MomBullet"], bulletText="•"))
        else:
            story.append(Paragraph(_inline_markdown(line), styles["MomBody"]))
        story.append(Spacer(1, 5))
        index += 1

    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buffer.getvalue()


def _pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="MomTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=30,
            textColor=INK,
            alignment=0,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MomHeading2",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=17,
            textColor=BRAND_BLUE,
            backColor=SECTION_TINT,
            borderPadding=(5, 8, 5, 8),
            spaceBefore=8,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MomBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.4,
            leading=15.2,
            textColor=INK,
            spaceAfter=1,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MomBullet",
            parent=styles["MomBody"],
            leftIndent=16,
            firstLineIndent=0,
            bulletIndent=4,
            bulletFontName="Helvetica-Bold",
            bulletFontSize=9,
            bulletColor=BRAND_BLUE,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MomTableCell",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.4,
            textColor=INK,
        )
    )
    styles.add(
        ParagraphStyle(
            name="MomTableHeader",
            parent=styles["MomTableCell"],
            fontName="Helvetica-Bold",
            textColor=INK,
        )
    )
    return styles


def _draw_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, stroke=0, fill=1)

    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN_X, PAGE_HEIGHT - 34, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 34)
    canvas.line(MARGIN_X, 32, PAGE_WIDTH - MARGIN_X, 32)

    canvas.setFillColor(BRAND_BLUE)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(MARGIN_X, PAGE_HEIGHT - 25, "MINUTES OF MEETING")

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(PAGE_WIDTH - MARGIN_X, 20, f"Page {doc.page}")
    canvas.restoreState()


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    first = lines[index].strip()
    second = lines[index + 1].strip()
    return _is_table_line(first) and _is_separator_row(second)


def _is_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _is_separator_row(line: str) -> bool:
    if not _is_table_line(line):
        return False
    cells = _parse_table_row(line)
    return bool(cells) and all(cell.replace("-", "").replace(":", "").strip() == "" and "-" in cell for cell in cells)


def _build_table(table_lines: list[str], styles) -> Table:
    rows = [_parse_table_row(line) for line in table_lines]
    rows = [row for row in rows if row and not _is_separator_row("|" + "|".join(row) + "|")]
    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]

    data = []
    for row_index, row in enumerate(normalized_rows):
        style = styles["MomTableHeader"] if row_index == 0 and "MomTableHeader" in styles else styles["BodyText"]
        if row_index > 0 and "MomTableCell" in styles:
            style = styles["MomTableCell"]
        data.append([Paragraph(_inline_markdown(cell), style) for cell in row])

    table = Table(data, colWidths=_column_widths(normalized_rows[0]), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER),
                ("TEXTCOLOR", (0, 0), (-1, 0), INK),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, BRAND_BLUE),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, LINE),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TABLE_ALT_ROW]),
            ]
        )
    )
    return table


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _column_widths(header: list[str]) -> list[float]:
    available_width = PAGE_WIDTH - (MARGIN_X * 2)
    normalized = [cell.lower() for cell in header]
    if normalized == ["action item", "owner", "due date", "source / context"]:
        weights = [2.8, 0.9, 0.9, 2.0]
    elif len(header) == 3 and normalized[:3] == ["action item", "owner", "due date"]:
        weights = [2.6, 1.0, 1.0]
    else:
        weights = [1.0] * len(header)
    total = sum(weights)
    return [available_width * weight / total for weight in weights]


def _inline_markdown(text: str) -> str:
    escaped = _escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    return escaped


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )