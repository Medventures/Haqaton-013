"""Independent PDF rendering from approved structured clinical data."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from html import escape
from importlib.resources import as_file, files
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing

from app.schemas import ConsultationData
from .projection import project_sections, sanitize_text


FONT = "MedHubDejaVu"
FONT_BOLD = "MedHubDejaVu-Bold"
INK = colors.HexColor("#183449")
MUTED = colors.HexColor("#536779")


@lru_cache(maxsize=1)
def _register_fonts() -> None:
    assets = files("app.forms").joinpath("assets")
    for name, filename in ((FONT, "DejaVuSans.ttf"), (FONT_BOLD, "DejaVuSans-Bold.ttf")):
        with as_file(assets.joinpath(filename)) as path:
            pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)


def _markup(value: str) -> str:
    return escape(sanitize_text(value)).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")


def render_pdf(
    template_id: str,
    data: ConsultationData,
    *,
    patient_id: str,
    consultation_id: str,
    doctor_name: str,
    approved_at: datetime,
    verification_url: str | None = None,
) -> bytes:
    """Render the selected form directly from its approved JSON and catalog."""
    # Project before writing any bytes so invalid template fields fail as DOCX does.
    sections = project_sections(template_id, data)
    from . import get_template

    title = get_template(template_id)["name"]
    _register_fonts()
    approved_utc = approved_at.replace(tzinfo=timezone.utc) if approved_at.tzinfo is None else approved_at.astimezone(timezone.utc)
    approved_label = approved_utc.strftime("%d.%m.%Y %H:%M UTC")

    title_style = ParagraphStyle(
        "Title", fontName=FONT_BOLD, fontSize=15, leading=21,
        textColor=INK, spaceAfter=14,
    )
    meta_style = ParagraphStyle(
        "Metadata", fontName=FONT, fontSize=9, leading=14,
        textColor=MUTED, spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "Section", fontName=FONT_BOLD, fontSize=10.5, leading=15,
        textColor=INK, spaceBefore=14, spaceAfter=7, keepWithNext=True,
    )
    field_style = ParagraphStyle(
        "Field", fontName=FONT, fontSize=9, leading=14,
        textColor=INK, spaceAfter=8, alignment=TA_LEFT,
        splitLongWords=1,
    )

    story = [
        Paragraph(_markup(title), title_style),
        Paragraph(f"<b>ID пациента:</b> {_markup(patient_id)}", meta_style),
        Paragraph(f"<b>ID консультации:</b> {_markup(consultation_id)}", meta_style),
        Paragraph(f"<b>Утверждено:</b> {_markup(approved_label)}", meta_style),
        Paragraph(f"<b>Врач:</b> {_markup(doctor_name)}", meta_style),
        Spacer(1, 8),
    ]
    for section in sections:
        story.append(Paragraph(_markup(section.title), section_style))
        for field in section.fields:
            story.append(Paragraph(
                f"<b>{_markup(field.label)}:</b> {_markup(field.value)}", field_style,
            ))
    story.append(Spacer(1, 15))
    story.append(Paragraph("Подпись врача: не проставлена", field_style))
    if verification_url:
        qr = QrCodeWidget(verification_url)
        x0, y0, x1, y1 = qr.getBounds()
        drawing = Drawing(88, 88, transform=[88/(x1-x0), 0, 0, 88/(y1-y0), 0, 0])
        drawing.add(qr)
        story.extend([Spacer(1, 12), drawing,
            Paragraph('Проверка документа MedHub · не является ЭЦП', meta_style),
            Paragraph(f'<link href="{escape(verification_url, quote=True)}">{_markup(verification_url)}</link>', meta_style)])

    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=48, rightMargin=48,
        topMargin=70, bottomMargin=58,
        title=title, author="MedHub",
    )

    def page_furniture(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#D9E2E8"))
        canvas.line(48, height - 50, width - 48, height - 50)
        canvas.setFont(FONT_BOLD, 9)
        canvas.setFillColor(INK)
        # Same stethoscope geometry and colors as public/favicon.svg, rendered as vectors.
        canvas.saveState()
        canvas.translate(48, height - 45)
        canvas.scale(.38, .38)
        canvas.setFillColor(colors.HexColor("#087e83"))
        canvas.roundRect(0, 0, 64, 64, 17, fill=1, stroke=0)
        canvas.translate(0, 64)
        canvas.scale(1, -1)
        canvas.setStrokeColor(colors.white)
        canvas.setLineWidth(4)
        canvas.setLineCap(1)
        path = canvas.beginPath()
        path.moveTo(18, 17); path.lineTo(18, 31)
        path.curveTo(18, 39, 24, 45, 32, 45)
        path.curveTo(40, 45, 46, 39, 46, 31); path.lineTo(46, 17)
        path.moveTo(13, 17); path.lineTo(23, 17)
        path.moveTo(41, 17); path.lineTo(51, 17)
        path.moveTo(32, 45); path.lineTo(32, 50)
        path.curveTo(32, 54, 35, 57, 39, 57)
        path.curveTo(43, 57, 46, 54, 46, 50)
        canvas.drawPath(path)
        canvas.setFillColor(colors.white)
        canvas.circle(46, 47, 4, fill=1, stroke=0)
        canvas.restoreState()
        canvas.drawString(79, height - 37, "MedHub")
        canvas.setFont(FONT, 8)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 48, height - 37, sanitize_text(consultation_id))
        canvas.line(48, 43, width - 48, 43)
        canvas.drawString(48, 28, f"ID пациента: {sanitize_text(patient_id)}")
        canvas.drawRightString(width - 48, 28, f"Стр. {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=page_furniture, onLaterPages=page_furniture)
    return output.getvalue()
