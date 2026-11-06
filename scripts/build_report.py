#!/usr/bin/env python3
"""Render the editable four-page report.md to report.pdf."""

from pathlib import Path
from html import escape
import re
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak

ROOT = Path(__file__).resolve().parents[1]


def main():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Body",
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            spaceAfter=9,
            alignment=TA_LEFT,
        )
    )
    story = []
    pages = (ROOT / "report.md").read_text().split("<!-- PAGE -->")
    for index, page in enumerate(pages):
        if index:
            story.append(PageBreak())
        for paragraph in re.split(r"\n\s*\n", page.strip()):
            text = paragraph.strip()
            if not text:
                continue
            if text.startswith("# "):
                style = styles["Title"]
                text = text[2:]
            elif text.startswith("## "):
                style = styles["Heading2"]
                text = text[3:]
            elif text.startswith("### "):
                style = styles["Heading3"]
                text = text[4:]
            else:
                style = styles["Body"]
            text = escape(text).replace("\n", " ")
            text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', text)
            text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
            story.append(Paragraph(text, style))

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(42, 24, "CS6855 | Group 8 | Contribution statement pending confirmation")
        canvas.drawRightString(A4[0] - 42, 24, str(doc.page))

    SimpleDocTemplate(
        str(ROOT / "report.pdf"),
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=40,
        bottomMargin=45,
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    from pypdf import PdfReader

    count = len(PdfReader(ROOT / "report.pdf").pages)
    if count > 4:
        raise RuntimeError(f"Report exceeds 4 pages: {count}")
    print(f"Wrote report.pdf ({count} pages)")


if __name__ == "__main__":
    main()
