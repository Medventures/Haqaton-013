from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest

from app.forms import get_template, list_templates, render_docx, validate_template_fields
from app.forms.projection import project_sections
from app.schemas import ConsultationData, Medication, TemplateFieldValue, VitalSigns


EXPECTED = {
    "therapist": "Осмотр терапевта.docx",
    "therapist_initial": "Первичный осмотр врача терапевта.docx",
    "cardiologist": "Осмотр кардиолога (первичный).docx",
    "pediatrician": "Осмотр педиатра.docx",
    "proctologist": "Осмотр проктолога.docx",
    "surgeon": "Осмотр хирурга (первичный).docx",
}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def document_text(document: bytes) -> str:
    with ZipFile(BytesIO(document)) as archive:
        assert archive.testzip() is None
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    return "\n".join("".join((run.text or "") for run in paragraph.iter(W + "t")) for paragraph in root.iter(W + "p"))


def export(template_id: str, data: ConsultationData | None = None) -> bytes:
    return render_docx(
        template_id,
        data or ConsultationData(),
        patient_id="TEST-001",
        consultation_id="CONS-001",
        doctor_name="Доктор Тестовый",
        approved_at=datetime(2026, 9, 30, 8, 30, tzinfo=timezone.utc),
    )


def test_all_original_templates_have_complete_source_mapped_catalog():
    catalog = list_templates()
    assert {item["id"] for item in catalog} == set(EXPECTED)
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    for item in catalog:
        assert (template_dir / EXPECTED[item["id"]]).is_file()
        assert item["name"]
        fields = item["fields"]
        assert len(fields) >= 15
        assert len({field["key"] for field in fields}) == len(fields)
        assert all(field["label"] and field["prompt"] and field["section"] for field in fields)
        assert all(isinstance(field["paragraph_index"], int) for field in fields)


@pytest.mark.parametrize("template_id", EXPECTED)
def test_blank_export_is_valid_and_never_asserts_printed_findings(template_id: str):
    text = document_text(export(template_id))
    assert get_template(template_id)["name"].casefold() in text.casefold()
    assert "Не указано" not in text
    assert "без патологии" not in text.lower()
    assert "отрицает" not in text.lower()
    assert "Подпись врача: не проставлена" in text
    assert "CONS-001" in text


@pytest.mark.parametrize("template_id", EXPECTED)
def test_entered_specialty_and_core_values_survive_xml_export(template_id: str):
    field = next(field for field in get_template(template_id)["fields"] if "clinical_field" not in field)
    data = ConsultationData(
        complaints=["Боль & <тест>"],
        template_fields=[TemplateFieldValue(key=field["key"], value="Уточнение & <спец> Ω")],
    )
    text = document_text(export(template_id, data))
    assert "Боль & <тест>" in text
    assert "Уточнение & <спец> Ω" in text


@pytest.mark.parametrize("template_id", EXPECTED)
def test_every_entered_specialty_field_is_written(template_id: str):
    fields = [field for field in get_template(template_id)["fields"] if "clinical_field" not in field]
    data = ConsultationData(template_fields=[
        TemplateFieldValue(key=field["key"], value=f"Значение-{position}-Ω")
        for position, field in enumerate(fields)
    ])
    text = document_text(export(template_id, data))
    assert all(f"Значение-{position}-Ω" in text for position in range(len(fields)))


@pytest.mark.parametrize("template_id", EXPECTED)
def test_unconfirmed_source_alternatives_are_absent(template_id: str):
    text = document_text(export(template_id)).casefold()
    forbidden = ("без патологии", "отрицает", "в норме", "хрипов нет", "не увеличена", "отрицательный", "правильной")
    assert not [phrase for phrase in forbidden if phrase in text]


@pytest.mark.parametrize("template_id", EXPECTED)
def test_every_common_clinical_value_survives_export(template_id: str):
    data = ConsultationData(
        complaints=["ЖАЛОБА-Ω"], anamnesis_morbi="АНАМНЕЗ-БОЛЕЗНИ-Ω",
        anamnesis_vitae="АНАМНЕЗ-ЖИЗНИ-Ω", allergies=["АЛЛЕРГИЯ-Ω"],
        medications=[Medication(name="ПРЕПАРАТ-ДО-Ω")],
        vital_signs=VitalSigns(
            temperature="ТЕМП-Ω", blood_pressure="АД-Ω", heart_rate="ЧСС-Ω",
            respiratory_rate="ЧДД-Ω", oxygen_saturation="SPO2-Ω",
        ),
        objective_status="ОБЪЕКТИВНО-Ω", diagnosis="ДИАГНОЗ-Ω", diagnosis_code="I10",
        recommendations=["РЕКОМЕНДАЦИЯ-Ω"],
        prescribed_medications=[Medication(name="ПРЕПАРАТ-ПОСЛЕ-Ω")],
        additional_notes="ПРИМЕЧАНИЕ-Ω",
    )
    text = document_text(export(template_id, data))
    for value in (
        "ЖАЛОБА-Ω", "АНАМНЕЗ-БОЛЕЗНИ-Ω", "АНАМНЕЗ-ЖИЗНИ-Ω", "АЛЛЕРГИЯ-Ω",
        "ПРЕПАРАТ-ДО-Ω", "ТЕМП-Ω", "АД-Ω", "ЧСС-Ω", "ЧДД-Ω", "SPO2-Ω",
        "ОБЪЕКТИВНО-Ω", "ДИАГНОЗ-Ω", "Код МКБ-10: I10", "РЕКОМЕНДАЦИЯ-Ω",
        "ПРЕПАРАТ-ПОСЛЕ-Ω", "ПРИМЕЧАНИЕ-Ω",
    ):
        assert value in text, (template_id, value)


def test_selected_template_rejects_unknown_duplicate_and_core_keys():
    catalog = get_template("surgeon")["fields"]
    specialty_key = next(field["key"] for field in catalog if "clinical_field" not in field)
    core_key = next(field["key"] for field in catalog if "clinical_field" in field)
    for keys in (["elsewhere"], [specialty_key, specialty_key], [core_key]):
        data = ConsultationData(template_fields=[TemplateFieldValue(key=key, value="x") for key in keys])
        with pytest.raises(ValueError):
            validate_template_fields("surgeon", data)
    with pytest.raises(KeyError):
        get_template("../../patient")


def test_specialty_catalog_covers_child_history_and_surgical_local_status():
    pediatric = " ".join(field["prompt"] for field in get_template("pediatrician")["fields"])
    surgeon = " ".join(field["prompt"] for field in get_template("surgeon")["fields"])
    proctologist = " ".join(field["prompt"] for field in get_template("proctologist")["fields"])
    assert "бер" in pediatric and "родов" in pediatric and "Вакцинации" in pediatric
    assert "Status localis" in surgeon and "Проводимые манипуляции" in surgeon
    assert "Перианальная область" in proctologist and "Тонус сфинктера" in proctologist


def test_disallowed_xml_control_is_replaced_without_losing_clinical_text():
    data = ConsultationData(complaints=["до\u0001после"])
    text = document_text(export("therapist", data))
    assert "до�после" in text


def test_source_alternatives_never_become_export_labels():
    expected = {
        ("surgeon", "p_014"): "Глотание",
        ("therapist_initial", "p_030"): "Оценка тяжести состояния и причины",
        ("therapist_initial", "p_046"): "Молочные железы и соски",
        ("therapist", "p_013"): "Телосложение",
        ("therapist", "p_014"): "Питание и ИМТ",
        ("therapist", "p_009"): "Жилищно-бытовые условия и питание",
        ("therapist", "p_023"): "Периферические лимфатические узлы",
        ("therapist", "p_016"): "Окраска кожи",
    }
    for (template_id, key), label in expected.items():
        fields = get_template(template_id)["fields"]
        assert next(field for field in fields if field["key"] == key)["label"] == label


def test_normal_entered_finding_is_not_prefixed_by_abnormal_assertion():
    data = ConsultationData(template_fields=[
        TemplateFieldValue(key="p_014", value="Свободное, без жалоб"),
    ])
    text = document_text(export("surgeon", data))
    assert "Глотание: Свободное, без жалоб" in text
    assert "Глотание нарушено" not in text


def test_approval_time_is_readable_utc_without_microseconds():
    document = render_docx(
        "therapist", ConsultationData(), patient_id="P", consultation_id="C",
        doctor_name="Врач", approved_at=datetime(2026, 9, 30, 8, 30, 44, 123456, tzinfo=timezone.utc),
    )
    text = document_text(document)
    assert "30.09.2026 08:30 UTC" in text
    assert "123456" not in text


def test_shared_projection_keeps_docx_values_and_source_package_structure():
    data = ConsultationData(
        complaints=["Боль в груди"], diagnosis="Уточнённый диагноз",
        diagnosis_code="I10",
        medications=[Medication(name="Лекарство", dosage="5 мг", frequency="2 раза",
                                duration="7 дней")],
        additional_notes="Дополнительная запись",
    )
    projected = "\n".join(
        field.value for section in project_sections("cardiologist", data)
        for field in section.fields
    )
    document = export("cardiologist", data)
    text = document_text(document)
    for value in ("Боль в груди", "Уточнённый диагноз", "I10", "Лекарство",
                  "5 мг", "2 раза", "7 дней", "Дополнительная запись"):
        assert value in projected
        assert value in text
    source = Path(__file__).resolve().parents[2] / "templates" / EXPECTED["cardiologist"]
    with ZipFile(source) as original, ZipFile(BytesIO(document)) as filled:
        assert set(original.namelist()) == set(filled.namelist())
    assert "Подпись врача: не проставлена" in text
