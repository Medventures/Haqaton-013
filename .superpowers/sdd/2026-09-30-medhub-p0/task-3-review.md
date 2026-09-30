# Task3 review package

Unified source snapshot diff. Binary fonts documented by SHA256 below; test evidence in report.

## backend/app/forms/projection.py
```diff
--- before/backend/app/forms/projection.py
+++ after/backend/app/forms/projection.py
@@ -0,0 +1,121 @@
+"""Common clinical values and source-backed sections for document renderers."""
+
+from __future__ import annotations
+
+from dataclasses import dataclass
+from typing import Any
+
+from app.schemas import ConsultationData
+
+
+EMPTY = "Не указано"
+
+
+@dataclass(frozen=True)
+class DocumentField:
+    key: str
+    label: str
+    value: str
+
+
+@dataclass(frozen=True)
+class DocumentSection:
+    title: str
+    fields: list[DocumentField]
+
+
+def format_medications(items: list[Any]) -> str:
+    return "; ".join(
+        ", ".join(filter(None, (item.name, item.dosage, item.frequency, item.duration)))
+        for item in items
+    )
+
+
+def core_value(data: ConsultationData, path: str) -> str:
+    if path == "vital_signs":
+        if data.vital_signs is None:
+            return EMPTY
+        names = {"temperature": "Температура", "blood_pressure": "АД", "heart_rate": "ЧСС",
+                 "respiratory_rate": "ЧДД", "oxygen_saturation": "SpO₂"}
+        parts = [f"{label}: {value}" for name, label in names.items()
+                 if (value := getattr(data.vital_signs, name))]
+        return "; ".join(parts) or EMPTY
+    if path.startswith("vital_signs."):
+        value = getattr(data.vital_signs, path.partition(".")[2]) if data.vital_signs else None
+        return value or EMPTY
+    value = getattr(data, path)
+    if isinstance(value, list):
+        if value and hasattr(value[0], "name"):
+            return format_medications(value) or EMPTY
+        return "; ".join(value) or EMPTY
+    return value or EMPTY
+
+
+def sanitize_text(value: str) -> str:
+    """Replace characters forbidden in XML 1.0 / ReportLab paragraph markup."""
+    return "".join(
+        char if char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF
+        or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
+        else "�" for char in value
+    )
+
+
+_RESIDUAL_FIELDS = (
+    ("complaints", "Жалобы"),
+    ("anamnesis_morbi", "Анамнез заболевания"),
+    ("anamnesis_vitae", "Анамнез жизни"),
+    ("allergies", "Аллергоанамнез"),
+    ("medications", "Принимаемые препараты"),
+    ("objective_status", "Объективный статус"),
+    ("diagnosis", "Предварительный диагноз"),
+    ("recommendations", "План ведения и рекомендации"),
+    ("prescribed_medications", "Назначенные препараты"),
+    ("additional_notes", "Дополнительные сведения"),
+)
+_VITAL_FIELDS = (
+    ("temperature", "Температура"),
+    ("blood_pressure", "АД"),
+    ("heart_rate", "ЧСС"),
+    ("respiratory_rate", "ЧДД"),
+    ("oxygen_saturation", "SpO₂"),
+)
+
+
+def project_sections(template_id: str, data: ConsultationData) -> list[DocumentSection]:
+    """Project every selected-form slot and any populated core value without a slot."""
+    # Late import avoids a cycle: the DOCX catalog imports shared value formatting.
+    from app.forms import get_template, validate_template_fields
+
+    validate_template_fields(template_id, data)
+    catalog = get_template(template_id)
+    entries = {entry.key: entry.value for entry in data.template_fields}
+    grouped: dict[str, list[DocumentField]] = {}
+    mapped: set[str] = set()
+    for field in sorted(catalog["fields"], key=lambda item: item["paragraph_index"]):
+        clinical_path = field.get("clinical_field")
+        if clinical_path:
+            mapped.add(clinical_path)
+        value = core_value(data, clinical_path) if clinical_path else (entries.get(field["key"]) or EMPTY)
+        section = grouped.setdefault(field["section"], [])
+        section.append(DocumentField(field["key"], field["label"], value))
+        if clinical_path == "diagnosis" and data.diagnosis_code:
+            section.append(DocumentField("diagnosis_code", "Код МКБ-10", data.diagnosis_code))
+
+    residual: list[DocumentField] = []
+    for path, label in _RESIDUAL_FIELDS:
+        if path not in mapped:
+            value = core_value(data, path)
+            if value != EMPTY:
+                residual.append(DocumentField(path, label, value))
+    if data.vital_signs is not None and "vital_signs" not in mapped:
+        for name, label in _VITAL_FIELDS:
+            path = f"vital_signs.{name}"
+            if path not in mapped:
+                value = core_value(data, path)
+                if value != EMPTY:
+                    residual.append(DocumentField(path, label, value))
+    if data.diagnosis_code and "diagnosis" not in mapped:
+        residual.append(DocumentField("diagnosis_code", "Код МКБ-10", data.diagnosis_code))
+    if residual:
+        grouped["Дополнительные клинические данные"] = residual
+    return [DocumentSection(title, fields) for title, fields in grouped.items()]

```

## backend/app/forms/pdf.py
```diff
--- before/backend/app/forms/pdf.py
+++ after/backend/app/forms/pdf.py
@@ -0,0 +1,120 @@
+"""Independent PDF rendering from approved structured clinical data."""
+
+from __future__ import annotations
+
+from datetime import datetime, timezone
+from functools import lru_cache
+from html import escape
+from importlib.resources import as_file, files
+from io import BytesIO
+
+from reportlab.lib import colors
+from reportlab.lib.enums import TA_LEFT
+from reportlab.lib.pagesizes import A4
+from reportlab.lib.styles import ParagraphStyle
+from reportlab.pdfbase import pdfmetrics
+from reportlab.pdfbase.ttfonts import TTFont
+from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
+
+from app.schemas import ConsultationData
+from .projection import project_sections, sanitize_text
+
+
+FONT = "MedHubDejaVu"
+FONT_BOLD = "MedHubDejaVu-Bold"
+INK = colors.HexColor("#183449")
+MUTED = colors.HexColor("#536779")
+
+
+@lru_cache(maxsize=1)
+def _register_fonts() -> None:
+    assets = files("app.forms").joinpath("assets")
+    for name, filename in ((FONT, "DejaVuSans.ttf"), (FONT_BOLD, "DejaVuSans-Bold.ttf")):
+        with as_file(assets.joinpath(filename)) as path:
+            pdfmetrics.registerFont(TTFont(name, str(path)))
+    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD)
+
+
+def _markup(value: str) -> str:
+    return escape(sanitize_text(value)).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
+
+
+def render_pdf(
+    template_id: str,
+    data: ConsultationData,
+    *,
+    patient_id: str,
+    consultation_id: str,
+    doctor_name: str,
+    approved_at: datetime,
+) -> bytes:
+    """Render the selected form directly from its approved JSON and catalog."""
+    # Project before writing any bytes so invalid template fields fail as DOCX does.
+    sections = project_sections(template_id, data)
+    from . import get_template
+
+    title = get_template(template_id)["name"]
+    _register_fonts()
+    approved_utc = approved_at.replace(tzinfo=timezone.utc) if approved_at.tzinfo is None else approved_at.astimezone(timezone.utc)
+    approved_label = approved_utc.strftime("%d.%m.%Y %H:%M UTC")
+
+    title_style = ParagraphStyle(
+        "Title", fontName=FONT_BOLD, fontSize=15, leading=21,
+        textColor=INK, spaceAfter=14,
+    )
+    meta_style = ParagraphStyle(
+        "Metadata", fontName=FONT, fontSize=9, leading=14,
+        textColor=MUTED, spaceAfter=4,
+    )
+    section_style = ParagraphStyle(
+        "Section", fontName=FONT_BOLD, fontSize=10.5, leading=15,
+        textColor=INK, spaceBefore=14, spaceAfter=7, keepWithNext=True,
+    )
+    field_style = ParagraphStyle(
+        "Field", fontName=FONT, fontSize=9, leading=14,
+        textColor=INK, spaceAfter=8, alignment=TA_LEFT,
+        splitLongWords=1,
+    )
+
+    story = [
+        Paragraph(_markup(title), title_style),
+        Paragraph(f"<b>ID пациента:</b> {_markup(patient_id)}", meta_style),
+        Paragraph(f"<b>ID консультации:</b> {_markup(consultation_id)}", meta_style),
+        Paragraph(f"<b>Утверждено:</b> {_markup(approved_label)}", meta_style),
+        Paragraph(f"<b>Врач:</b> {_markup(doctor_name)}", meta_style),
+        Spacer(1, 8),
+    ]
+    for section in sections:
+        story.append(Paragraph(_markup(section.title), section_style))
+        for field in section.fields:
+            story.append(Paragraph(
+                f"<b>{_markup(field.label)}:</b> {_markup(field.value)}", field_style,
+            ))
+    story.append(Spacer(1, 15))
+    story.append(Paragraph("Подпись врача: не проставлена", field_style))
+
+    output = BytesIO()
+    document = SimpleDocTemplate(
+        output, pagesize=A4, leftMargin=48, rightMargin=48,
+        topMargin=70, bottomMargin=58,
+        title=title, author="MedHub",
+    )
+
+    def page_furniture(canvas, doc):
+        canvas.saveState()
+        width, height = A4
+        canvas.setStrokeColor(colors.HexColor("#D9E2E8"))
+        canvas.line(48, height - 50, width - 48, height - 50)
+        canvas.setFont(FONT_BOLD, 9)
+        canvas.setFillColor(INK)
+        canvas.drawString(48, height - 37, "MedHub")
+        canvas.setFont(FONT, 8)
+        canvas.setFillColor(MUTED)
+        canvas.drawRightString(width - 48, height - 37, sanitize_text(consultation_id))
+        canvas.line(48, 43, width - 48, 43)
+        canvas.drawString(48, 28, f"ID пациента: {sanitize_text(patient_id)}")
+        canvas.drawRightString(width - 48, 28, f"Стр. {doc.page}")
+        canvas.restoreState()
+
+    document.build(story, onFirstPage=page_furniture, onLaterPages=page_furniture)
+    return output.getvalue()

```

## backend/app/forms/__init__.py
```diff
--- before/backend/app/forms/__init__.py
+++ after/backend/app/forms/__init__.py
@@ -7,23 +7,23 @@
 from datetime import datetime, timezone
 from io import BytesIO
 from pathlib import Path
 from typing import Any
 from xml.etree import ElementTree as ET
 from zipfile import ZipFile
 
 from app.schemas import ConsultationData
+from .projection import EMPTY, core_value as _core_value, sanitize_text
 
 
 W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 W = f"{{{W_NS}}}"
 ET.register_namespace("w", W_NS)
 ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")
-EMPTY = "Не указано"
 
 
 @dataclass(frozen=True)
 class SourceSpec:
     name: str
     filename: str
     sections: tuple[tuple[int, str], ...]
     core: dict[int, str]
@@ -338,46 +338,19 @@
     permitted = {field["key"] for field in template["fields"] if "clinical_field" not in field}
     seen: set[str] = set()
     for entry in data.template_fields:
         if entry.key not in permitted or entry.key in seen:
             raise ValueError("Invalid or duplicate template field key")
         seen.add(entry.key)
 
 
-def _format_medications(items: list[Any]) -> str:
-    return "; ".join(", ".join(filter(None, (item.name, item.dosage, item.frequency, item.duration))) for item in items)
-
-
-def _core_value(data: ConsultationData, path: str) -> str:
-    if path == "vital_signs":
-        if data.vital_signs is None:
-            return EMPTY
-        names = {"temperature": "Температура", "blood_pressure": "АД", "heart_rate": "ЧСС",
-                 "respiratory_rate": "ЧДД", "oxygen_saturation": "SpO₂"}
-        parts = [f"{label}: {value}" for name, label in names.items() if (value := getattr(data.vital_signs, name))]
-        return "; ".join(parts) or EMPTY
-    if path.startswith("vital_signs."):
-        value = getattr(data.vital_signs, path.partition(".")[2]) if data.vital_signs else None
-        return value or EMPTY
-    value = getattr(data, path)
-    if isinstance(value, list):
-        if value and hasattr(value[0], "name"):
-            return _format_medications(value) or EMPTY
-        return "; ".join(value) or EMPTY
-    return value or EMPTY
-
-
 def _replace_paragraph(paragraph: ET.Element, value: str) -> None:
     # XML 1.0 cannot contain most C0 controls, even inside escaped text.
-    value = "".join(
-        char if char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF
-        or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
-        else "�" for char in value
-    )
+    value = sanitize_text(value)
     first_run = paragraph.find(W + "r")
     style = first_run.find(W + "rPr") if first_run is not None else None
     for child in list(paragraph):
         if child.tag != W + "pPr":
             paragraph.remove(child)
     run = ET.SubElement(paragraph, W + "r")
     if style is not None:
         run.append(ET.fromstring(ET.tostring(style)))
@@ -475,8 +448,11 @@
             _replace_paragraph(extra, "; ".join(residual))
             body.insert(list(body).index(header) + 1, extra)
         xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
         output = BytesIO()
         with ZipFile(output, "w") as target:
             for member in source.infolist():
                 target.writestr(member, xml if member.filename == "word/document.xml" else source.read(member.filename))
     return output.getvalue()
+
+
+from .pdf import render_pdf  # noqa: E402  -- public renderer, imported after catalog setup

```

## backend/pyproject.toml
```diff
--- before/backend/pyproject.toml
+++ after/backend/pyproject.toml
@@ -14,18 +14,22 @@
   "psycopg[binary]>=3.2,<4",
   "PyJWT>=2.9,<3",
   "pwdlib[argon2]>=0.2,<1",
   "python-multipart>=0.0.9,<1",
   "faster-whisper>=1.1,<2",
   # PyAV 19 removed metadata_errors, still used by faster-whisper's decoder.
   "av>=18,<19",
   "openai>=1.60,<3",
+  "reportlab>=5.0.1,<6",
 ]
 
 [project.optional-dependencies]
-dev = ["pytest>=8,<10", "pytest-asyncio>=0.24,<2", "httpx>=0.27,<1"]
+dev = ["pytest>=8,<10", "pytest-asyncio>=0.24,<2", "httpx>=0.27,<1", "pypdf>=6.19,<7"]
 
 [tool.setuptools.packages.find]
 include = ["app*"]
 
+[tool.setuptools.package-data]
+"app.forms" = ["assets/*.ttf", "assets/*.txt"]
+
 [tool.pytest.ini_options]
 testpaths = ["tests"]

```

## backend/tests/test_pdf.py
```diff
--- before/backend/tests/test_pdf.py
+++ after/backend/tests/test_pdf.py
@@ -0,0 +1,110 @@
+"""Behavioral checks for the independent approved JSON to PDF export."""
+
+from datetime import datetime, timezone
+from io import BytesIO
+
+import pytest
+from pypdf import PdfReader
+
+from app.forms import get_template, render_pdf
+from app.forms.projection import project_sections
+from app.schemas import ConsultationData, Medication, TemplateFieldValue, VitalSigns
+
+
+TEMPLATES = (
+    "therapist", "therapist_initial", "cardiologist", "pediatrician",
+    "proctologist", "surgeon",
+)
+APPROVED = datetime(2026, 9, 30, 8, 30, 44, 123456, tzinfo=timezone.utc)
+
+
+def pdf_pages(document: bytes) -> list[str]:
+    assert document.startswith(b"%PDF-")
+    return [page.extract_text() for page in PdfReader(BytesIO(document)).pages]
+
+
+def export(template_id: str, data: ConsultationData) -> bytes:
+    return render_pdf(
+        template_id, data, patient_id="PAT-001", consultation_id="CONS-001",
+        doctor_name="Дәрігер Тест", approved_at=APPROVED,
+    )
+
+
+@pytest.mark.parametrize("template_id", TEMPLATES)
+def test_all_six_forms_preserve_every_populated_value(template_id: str):
+    """Dropping any core property or specialty entry must fail in both outputs."""
+    specialty = [
+        field for field in get_template(template_id)["fields"]
+        if "clinical_field" not in field
+    ]
+    sentinels = [
+        "ЖАЛОБА-Ω", "АНАМНЕЗ-БОЛЕЗНИ-Ω", "АНАМНЕЗ-ЖИЗНИ-Ω",
+        "АЛЛЕРГИЯ-Ω", "ПРЕПАРАТ-ДО-Ω", "ДОЗА-ДО-Ω", "ЧАСТОТА-ДО-Ω",
+        "ДЛИТЕЛЬНОСТЬ-ДО-Ω", "ТЕМП-Ω", "АД-Ω", "ЧСС-Ω", "ЧДД-Ω",
+        "SPO2-Ω", "ОБЪЕКТИВНО-Ω", "ДИАГНОЗ-Ω", "I10",
+        "РЕКОМЕНДАЦИЯ-Ω", "ПРЕПАРАТ-ПОСЛЕ-Ω", "ДОЗА-ПОСЛЕ-Ω",
+        "ЧАСТОТА-ПОСЛЕ-Ω", "ДЛИТЕЛЬНОСТЬ-ПОСЛЕ-Ω", "ПРИМЕЧАНИЕ-Ω",
+    ]
+    specialty_values = [f"СПЕЦ-{index:03d}-Ω" for index in range(len(specialty))]
+    data = ConsultationData(
+        complaints=["ЖАЛОБА-Ω"], anamnesis_morbi="АНАМНЕЗ-БОЛЕЗНИ-Ω",
+        anamnesis_vitae="АНАМНЕЗ-ЖИЗНИ-Ω", allergies=["АЛЛЕРГИЯ-Ω"],
+        medications=[Medication(name="ПРЕПАРАТ-ДО-Ω", dosage="ДОЗА-ДО-Ω",
+                                frequency="ЧАСТОТА-ДО-Ω", duration="ДЛИТЕЛЬНОСТЬ-ДО-Ω")],
+        vital_signs=VitalSigns(
+            temperature="ТЕМП-Ω", blood_pressure="АД-Ω", heart_rate="ЧСС-Ω",
+            respiratory_rate="ЧДД-Ω", oxygen_saturation="SPO2-Ω",
+        ),
+        objective_status="ОБЪЕКТИВНО-Ω", diagnosis="ДИАГНОЗ-Ω",
+        diagnosis_code="I10", recommendations=["РЕКОМЕНДАЦИЯ-Ω"],
+        prescribed_medications=[Medication(
+            name="ПРЕПАРАТ-ПОСЛЕ-Ω", dosage="ДОЗА-ПОСЛЕ-Ω",
+            frequency="ЧАСТОТА-ПОСЛЕ-Ω", duration="ДЛИТЕЛЬНОСТЬ-ПОСЛЕ-Ω",
+        )],
+        additional_notes="ПРИМЕЧАНИЕ-Ω",
+        template_fields=[
+            TemplateFieldValue(key=field["key"], value=value)
+            for field, value in zip(specialty, specialty_values, strict=True)
+        ],
+    )
+    sections = project_sections(template_id, data)
+    projected = "\n".join(field.value for section in sections for field in section.fields)
+    extracted_text = "\n".join(pdf_pages(export(template_id, data)))
+    for value in (*sentinels, *specialty_values):
+        assert value in projected, (template_id, "projection", value)
+        assert value in extracted_text, (template_id, "pdf", value)
+
+
+@pytest.mark.parametrize("template_id", TEMPLATES)
+def test_blank_pdf_uses_explicit_unknowns_without_printed_findings(template_id: str):
+    sections = project_sections(template_id, ConsultationData())
+    assert sections
+    assert all(field.value == "Не указано" for section in sections for field in section.fields)
+    text = "\n".join(pdf_pages(export(template_id, ConsultationData()))).casefold()
+    assert "не указано" in text
+    assert "подпись врача: не проставлена" in text
+    for finding in ("без патологии", "хрипов нет", "отрицает", "не увеличена"):
+        assert finding not in text
+
+
+def test_pdf_unicode_markup_and_pagination():
+    """Unicode, markup-like text, controls, and long notes survive wrapping."""
+    kazakh = "Ә Ғ Қ Ң Ө Ұ Ү Һ І"
+    long_note = ("Ұзақ мәтін және клиникалық жазба. " * 240) + "СОҢҒЫ-МАРКЕР-Ω"
+    data = ConsultationData(
+        complaints=[f"{kazakh} <>&"],
+        additional_notes=long_note,
+        template_fields=[TemplateFieldValue(key="p_005", value="Басы\x01соңы <>&")],
+    )
+    pages = pdf_pages(export("therapist", data))
+    extracted_text = "\n".join(pages)
+    assert len(pages) > 1
+    assert kazakh in extracted_text
+    assert "<>&" in extracted_text
+    assert "Басы�соңы <>&" in extracted_text
+    assert "СОҢҒЫ-МАРКЕР-Ω" in extracted_text
+    assert all("MedHub" in page and "CONS-001" in page for page in pages)
+    assert "30.09.2026 08:30 UTC" in extracted_text
+    assert "Дәрігер Тест" in extracted_text
+    assert "Подпись врача: не проставлена" in extracted_text
+    assert "123456" not in extracted_text

```

## backend/tests/test_forms.py
```diff
--- before/backend/tests/test_forms.py
+++ after/backend/tests/test_forms.py
@@ -2,16 +2,17 @@
 from io import BytesIO
 from pathlib import Path
 from xml.etree import ElementTree
 from zipfile import ZipFile
 
 import pytest
 
 from app.forms import get_template, list_templates, render_docx, validate_template_fields
+from app.forms.projection import project_sections
 from app.schemas import ConsultationData, Medication, TemplateFieldValue, VitalSigns
 
 
 EXPECTED = {
     "therapist": "Осмотр терапевта.docx",
     "therapist_initial": "Первичный осмотр врача терапевта.docx",
     "cardiologist": "Осмотр кардиолога (первичный).docx",
     "pediatrician": "Осмотр педиатра.docx",
@@ -174,8 +175,32 @@
 def test_approval_time_is_readable_utc_without_microseconds():
     document = render_docx(
         "therapist", ConsultationData(), patient_id="P", consultation_id="C",
         doctor_name="Врач", approved_at=datetime(2026, 9, 30, 8, 30, 44, 123456, tzinfo=timezone.utc),
     )
     text = document_text(document)
     assert "30.09.2026 08:30 UTC" in text
     assert "123456" not in text
+
+
+def test_shared_projection_keeps_docx_values_and_source_package_structure():
+    data = ConsultationData(
+        complaints=["Боль в груди"], diagnosis="Уточнённый диагноз",
+        diagnosis_code="I10",
+        medications=[Medication(name="Лекарство", dosage="5 мг", frequency="2 раза",
+                                duration="7 дней")],
+        additional_notes="Дополнительная запись",
+    )
+    projected = "\n".join(
+        field.value for section in project_sections("cardiologist", data)
+        for field in section.fields
+    )
+    document = export("cardiologist", data)
+    text = document_text(document)
+    for value in ("Боль в груди", "Уточнённый диагноз", "I10", "Лекарство",
+                  "5 мг", "2 раза", "7 дней", "Дополнительная запись"):
+        assert value in projected
+        assert value in text
+    source = Path(__file__).resolve().parents[2] / "templates" / EXPECTED["cardiologist"]
+    with ZipFile(source) as original, ZipFile(BytesIO(document)) as filled:
+        assert set(original.namelist()) == set(filled.namelist())
+    assert "Подпись врача: не проставлена" in text

```

## backend/app/forms/assets/LICENSE-DejaVu.txt
```diff
--- before/backend/app/forms/assets/LICENSE-DejaVu.txt
+++ after/backend/app/forms/assets/LICENSE-DejaVu.txt
@@ -0,0 +1,78 @@
+Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
+Upstream-Name: DejaVu fonts
+Upstream-Author: Stepan Roh <src@users.sourceforge.net> (original author),
+                  see /usr/share/doc/fonts-dejavu-core/AUTHORS for full list
+Source: https://dejavu-fonts.github.io/
+
+Files: *
+Copyright: Copyright (c) 2003 by Bitstream, Inc. All Rights Reserved. 
+ Bitstream Vera is a trademark of Bitstream, Inc.
+ DejaVu changes are in public domain.
+License: bitstream-vera
+ Permission is hereby granted, free of charge, to any person obtaining a copy
+ of the fonts accompanying this license ("Fonts") and associated
+ documentation files (the "Font Software"), to reproduce and distribute the
+ Font Software, including without limitation the rights to use, copy, merge,
+ publish, distribute, and/or sell copies of the Font Software, and to permit
+ persons to whom the Font Software is furnished to do so, subject to the
+ following conditions:
+ .
+ The above copyright and trademark notices and this permission notice shall
+ be included in all copies of one or more of the Font Software typefaces.
+ .
+ The Font Software may be modified, altered, or added to, and in particular
+ the designs of glyphs or characters in the Fonts may be modified and
+ additional glyphs or characters may be added to the Fonts, only if the fonts
+ are renamed to names not containing either the words "Bitstream" or the word
+ "Vera".
+ .
+ This License becomes null and void to the extent applicable to Fonts or Font
+ Software that has been modified and is distributed under the "Bitstream
+ Vera" names.
+ .
+ The Font Software may be sold as part of a larger software package but no
+ copy of one or more of the Font Software typefaces may be sold by itself.
+ .
+ THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
+ OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF MERCHANTABILITY,
+ FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF COPYRIGHT, PATENT,
+ TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL BITSTREAM OR THE GNOME
+ FOUNDATION BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, INCLUDING
+ ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL DAMAGES,
+ WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF
+ THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM OTHER DEALINGS IN THE
+ FONT SOFTWARE.
+ .
+ Except as contained in this notice, the names of Gnome, the Gnome
+ Foundation, and Bitstream Inc., shall not be used in advertising or
+ otherwise to promote the sale, use or other dealings in this Font Software
+ without prior written authorization from the Gnome Foundation or Bitstream
+ Inc., respectively. For further information, contact: fonts at gnome dot
+ org.
+
+Files: debian/*
+Copyright: (C) 2005-2006 Peter Cernak <pce@users.sourceforge.net> 
+           (C) 2006-2011 Davide Viti <zinosat@tiscali.it>
+           (C) 2011-2013 Christian Perrier <bubulle@debian.org>
+           (C) 2013 Fabian Greffrath <fabian+debian@greffrath.com>
+License: GPL-2+
+ This program is free software; you can redistribute it
+ and/or modify it under the terms of the GNU General Public
+ License as published by the Free Software Foundation; either
+ version 2 of the License, or (at your option) any later
+ version.
+ .
+ This program is distributed in the hope that it will be
+ useful, but WITHOUT ANY WARRANTY; without even the implied
+ warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
+ PURPOSE.  See the GNU General Public License for more
+ details.
+ .
+ You should have received a copy of the GNU General Public
+ License along with this package; if not, write to the Free
+ Software Foundation, Inc., 51 Franklin St, Fifth Floor,
+ Boston, MA  02110-1301 USA
+ .
+ On Debian systems, the full text of the GNU General Public
+ License version 2 can be found in the file
+ /usr/share/common-licenses/GPL-2'.

```

## Binary asset hashes
```
ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280  backend/app/forms/assets/DejaVuSans.ttf
5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895  backend/app/forms/assets/DejaVuSans-Bold.ttf
ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280  /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
5c1247acef7f2b8522a31742c76d6adcb5569bacc0be7ceaa4dc39dd252ce895  /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf

```

