from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def markdown_to_pdf(markdown_text: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=48)
    styles = getSampleStyleSheet()
    story = []

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 8))
            continue
        if line.startswith("# "):
            story.append(Paragraph(_escape(line[2:]), styles["Title"]))
        elif line.startswith("## "):
            story.append(Paragraph(_escape(line[3:]), styles["Heading2"]))
        else:
            story.append(Paragraph(_escape(_strip_markdown_table_pipe(line)), styles["BodyText"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()


def _strip_markdown_table_pipe(line: str) -> str:
    if line.startswith("|") and line.endswith("|"):
        return " | ".join(part.strip() for part in line.strip("|").split("|"))
    return line


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
