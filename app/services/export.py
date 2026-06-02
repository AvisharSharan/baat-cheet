from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def markdown_to_pdf(markdown_text: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
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
            story.append(Spacer(1, 8))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(_escape(line[3:]), styles["Heading2"]))
        else:
            story.append(Paragraph(_escape(line), styles["BodyText"]))
        story.append(Spacer(1, 4))
        index += 1

    doc.build(story)
    return buffer.getvalue()


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _is_table_line(lines[index].strip()) and _is_separator_row(lines[index + 1].strip())


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
    data = [[Paragraph(_escape(cell), styles["BodyText"]) for cell in row] for row in normalized_rows]

    table = Table(data, colWidths=_column_widths(normalized_rows[0]), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f1ed")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#16201c")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#a7b5ad")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7faf8")]),
            ]
        )
    )
    return table


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _column_widths(header: list[str]) -> list[float]:
    available_width = A4[0] - 96
    normalized = [cell.lower() for cell in header]
    if normalized == ["action item", "owner", "due date", "source / context"]:
        weights = [2.6, 1.0, 1.0, 2.0]
    elif len(header) == 3 and normalized[:3] == ["action item", "owner", "due date"]:
        weights = [2.6, 1.0, 1.0]
    else:
        weights = [1.0] * len(header)
    total = sum(weights)
    return [available_width * weight / total for weight in weights]


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
