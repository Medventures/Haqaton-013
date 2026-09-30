"""Common clinical values and source-backed sections for document renderers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas import ConsultationData


EMPTY = "Не указано"


@dataclass(frozen=True)
class DocumentField:
    key: str
    label: str
    value: str


@dataclass(frozen=True)
class DocumentSection:
    title: str
    fields: list[DocumentField]


def format_medications(items: list[Any]) -> str:
    return "; ".join(
        ", ".join(filter(None, (item.name, item.dosage, item.frequency, item.duration)))
        for item in items
    )


def core_value(data: ConsultationData, path: str) -> str:
    if path == "vital_signs":
        if data.vital_signs is None:
            return EMPTY
        names = {"temperature": "Температура", "blood_pressure": "АД", "heart_rate": "ЧСС",
                 "respiratory_rate": "ЧДД", "oxygen_saturation": "SpO₂"}
        parts = [f"{label}: {value}" for name, label in names.items()
                 if (value := getattr(data.vital_signs, name))]
        return "; ".join(parts) or EMPTY
    if path.startswith("vital_signs."):
        value = getattr(data.vital_signs, path.partition(".")[2]) if data.vital_signs else None
        return value or EMPTY
    value = getattr(data, path)
    if isinstance(value, list):
        if value and hasattr(value[0], "name"):
            return format_medications(value) or EMPTY
        return "; ".join(value) or EMPTY
    return value or EMPTY


def sanitize_text(value: str) -> str:
    """Replace characters forbidden in XML 1.0 / ReportLab paragraph markup."""
    return "".join(
        char if char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF
        else "�" for char in value
    )


_RESIDUAL_FIELDS = (
    ("complaints", "Жалобы"),
    ("anamnesis_morbi", "Анамнез заболевания"),
    ("anamnesis_vitae", "Анамнез жизни"),
    ("allergies", "Аллергоанамнез"),
    ("medications", "Принимаемые препараты"),
    ("objective_status", "Объективный статус"),
    ("diagnosis", "Предварительный диагноз"),
    ("recommendations", "План ведения и рекомендации"),
    ("prescribed_medications", "Назначенные препараты"),
    ("additional_notes", "Дополнительные сведения"),
)
_VITAL_FIELDS = (
    ("temperature", "Температура"),
    ("blood_pressure", "АД"),
    ("heart_rate", "ЧСС"),
    ("respiratory_rate", "ЧДД"),
    ("oxygen_saturation", "SpO₂"),
)


def project_sections(template_id: str, data: ConsultationData) -> list[DocumentSection]:
    """Project every selected-form slot and any populated core value without a slot."""
    # Late import avoids a cycle: the DOCX catalog imports shared value formatting.
    from app.forms import get_template, validate_template_fields

    validate_template_fields(template_id, data)
    catalog = get_template(template_id)
    entries = {entry.key: entry.value for entry in data.template_fields}
    grouped: dict[str, list[DocumentField]] = {}
    mapped: set[str] = set()
    for field in sorted(catalog["fields"], key=lambda item: item["paragraph_index"]):
        clinical_path = field.get("clinical_field")
        if clinical_path:
            mapped.add(clinical_path)
        value = core_value(data, clinical_path) if clinical_path else (entries.get(field["key"]) or EMPTY)
        section = grouped.setdefault(field["section"], [])
        section.append(DocumentField(field["key"], field["label"], value))
        if clinical_path == "diagnosis" and data.diagnosis_code:
            section.append(DocumentField("diagnosis_code", "Код МКБ-10", data.diagnosis_code))

    residual: list[DocumentField] = []
    for path, label in _RESIDUAL_FIELDS:
        if path not in mapped:
            value = core_value(data, path)
            if value != EMPTY:
                residual.append(DocumentField(path, label, value))
    if data.vital_signs is not None and "vital_signs" not in mapped:
        for name, label in _VITAL_FIELDS:
            path = f"vital_signs.{name}"
            if path not in mapped:
                value = core_value(data, path)
                if value != EMPTY:
                    residual.append(DocumentField(path, label, value))
    if data.diagnosis_code and "diagnosis" not in mapped:
        residual.append(DocumentField("diagnosis_code", "Код МКБ-10", data.diagnosis_code))
    if residual:
        grouped["Дополнительные клинические данные"] = residual
    return [DocumentSection(title, fields) for title, fields in grouped.items()]
