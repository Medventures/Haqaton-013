"""Behavioral checks for the independent approved JSON to PDF export."""

from datetime import datetime, timezone
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.forms import get_template, render_pdf
from app.forms.projection import project_sections
from app.schemas import ConsultationData, Medication, TemplateFieldValue, VitalSigns


TEMPLATES = (
    "therapist", "therapist_initial", "cardiologist", "pediatrician",
    "proctologist", "surgeon",
)
APPROVED = datetime(2026, 9, 30, 8, 30, 44, 123456, tzinfo=timezone.utc)


def pdf_pages(document: bytes) -> list[str]:
    assert document.startswith(b"%PDF-")
    return [page.extract_text() for page in PdfReader(BytesIO(document)).pages]


def export(template_id: str, data: ConsultationData) -> bytes:
    return render_pdf(
        template_id, data, patient_id="PAT-001", consultation_id="CONS-001",
        doctor_name="Дәрігер Тест", approved_at=APPROVED,
    )


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_all_six_forms_preserve_every_populated_value(template_id: str):
    """Dropping any core property or specialty entry must fail in both outputs."""
    specialty = [
        field for field in get_template(template_id)["fields"]
        if "clinical_field" not in field
    ]
    sentinels = [
        "ЖАЛОБА-Ω", "АНАМНЕЗ-БОЛЕЗНИ-Ω", "АНАМНЕЗ-ЖИЗНИ-Ω",
        "АЛЛЕРГИЯ-Ω", "ПРЕПАРАТ-ДО-Ω", "ДОЗА-ДО-Ω", "ЧАСТОТА-ДО-Ω",
        "ДЛИТЕЛЬНОСТЬ-ДО-Ω", "ТЕМП-Ω", "АД-Ω", "ЧСС-Ω", "ЧДД-Ω",
        "SPO2-Ω", "ОБЪЕКТИВНО-Ω", "ДИАГНОЗ-Ω", "I10",
        "РЕКОМЕНДАЦИЯ-Ω", "ПРЕПАРАТ-ПОСЛЕ-Ω", "ДОЗА-ПОСЛЕ-Ω",
        "ЧАСТОТА-ПОСЛЕ-Ω", "ДЛИТЕЛЬНОСТЬ-ПОСЛЕ-Ω", "ПРИМЕЧАНИЕ-Ω",
    ]
    specialty_values = [f"СПЕЦ-{index:03d}-Ω" for index in range(len(specialty))]
    data = ConsultationData(
        complaints=["ЖАЛОБА-Ω"], anamnesis_morbi="АНАМНЕЗ-БОЛЕЗНИ-Ω",
        anamnesis_vitae="АНАМНЕЗ-ЖИЗНИ-Ω", allergies=["АЛЛЕРГИЯ-Ω"],
        medications=[Medication(name="ПРЕПАРАТ-ДО-Ω", dosage="ДОЗА-ДО-Ω",
                                frequency="ЧАСТОТА-ДО-Ω", duration="ДЛИТЕЛЬНОСТЬ-ДО-Ω")],
        vital_signs=VitalSigns(
            temperature="ТЕМП-Ω", blood_pressure="АД-Ω", heart_rate="ЧСС-Ω",
            respiratory_rate="ЧДД-Ω", oxygen_saturation="SPO2-Ω",
        ),
        objective_status="ОБЪЕКТИВНО-Ω", diagnosis="ДИАГНОЗ-Ω",
        diagnosis_code="I10", recommendations=["РЕКОМЕНДАЦИЯ-Ω"],
        prescribed_medications=[Medication(
            name="ПРЕПАРАТ-ПОСЛЕ-Ω", dosage="ДОЗА-ПОСЛЕ-Ω",
            frequency="ЧАСТОТА-ПОСЛЕ-Ω", duration="ДЛИТЕЛЬНОСТЬ-ПОСЛЕ-Ω",
        )],
        additional_notes="ПРИМЕЧАНИЕ-Ω",
        template_fields=[
            TemplateFieldValue(key=field["key"], value=value)
            for field, value in zip(specialty, specialty_values, strict=True)
        ],
    )
    sections = project_sections(template_id, data)
    projected = "\n".join(field.value for section in sections for field in section.fields)
    extracted_text = "\n".join(pdf_pages(export(template_id, data)))
    for value in (*sentinels, *specialty_values):
        assert value in projected, (template_id, "projection", value)
        assert value in extracted_text, (template_id, "pdf", value)


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_blank_pdf_omits_empty_clinical_sections_without_printed_findings(template_id: str):
    sections = project_sections(template_id, ConsultationData())
    assert sections == []
    text = "\n".join(pdf_pages(export(template_id, ConsultationData()))).casefold()
    assert "не указано" not in text
    assert "подпись врача: не проставлена" in text
    for finding in ("без патологии", "хрипов нет", "отрицает", "не увеличена"):
        assert finding not in text


def test_pdf_unicode_markup_and_pagination():
    """Unicode, markup-like text, controls, and long notes survive wrapping."""
    kazakh = "Ә Ғ Қ Ң Ө Ұ Ү Һ І"
    long_note = ("Ұзақ мәтін және клиникалық жазба. " * 240) + "СОҢҒЫ-МАРКЕР-Ω"
    data = ConsultationData(
        complaints=[f"{kazakh} <>&"],
        additional_notes=long_note,
        template_fields=[TemplateFieldValue(key="p_005", value="Басы\x01соңы <>&")],
    )
    pages = pdf_pages(export("therapist", data))
    extracted_text = "\n".join(pages)
    assert len(pages) > 1
    assert kazakh in extracted_text
    assert "<>&" in extracted_text
    assert "Басы�соңы <>&" in extracted_text
    assert "СОҢҒЫ-МАРКЕР-Ω" in extracted_text
    assert all("MedHub" in page and "CONS-001" in page for page in pages)
    assert "30.09.2026 08:30 UTC" in extracted_text
    assert "Дәрігер Тест" in extracted_text
    assert "Подпись врача: не проставлена" in extracted_text
    assert "123456" not in extracted_text
