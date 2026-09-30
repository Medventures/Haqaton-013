"""Catalog and conservative rendering of the six bundled clinical forms."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app.schemas import ConsultationData
from .projection import EMPTY, core_value as _core_value, sanitize_text


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
ET.register_namespace("w", W_NS)
ET.register_namespace("mc", "http://schemas.openxmlformats.org/markup-compatibility/2006")


@dataclass(frozen=True)
class SourceSpec:
    name: str
    filename: str
    sections: tuple[tuple[int, str], ...]
    core: dict[int, str]
    exam_plan: int
    management_plan: int
    regimen: int
    follow_up: int
    diagnosis: int
    extra_specialty: dict[int, str]
    labels: dict[int, str]


SPECS: dict[str, SourceSpec] = {
    "therapist": SourceSpec(
        "Осмотр терапевта", "Осмотр терапевта.docx",
        ((3, "Жалобы и анамнез"), (10, "Status praesens"), (42, "Предварительный диагноз"),
         (44, "План обследования"), (50, "План ведения")),
        {3: "complaints", 4: "anamnesis_morbi", 5: "anamnesis_vitae", 6: "allergies",
         11: "objective_status", 31: "vital_signs.respiratory_rate", 33: "vital_signs",
         43: "diagnosis"},
        45, 52, 51, 56, 43,
        {5: "Инфекционные заболевания и наследственность", 6: "Гинекологический анамнез и перенесенные заболевания"},
        {24: "Мышечная система", 29: "Аускультация легких", 34: "Аускультация сердца"},
    ),
    "therapist_initial": SourceSpec(
        "Первичный осмотр врача терапевта", "Первичный осмотр врача терапевта.docx",
        ((3, "Жалобы"), (7, "Anamnesis morbi"), (12, "Anamnesis vitae"),
         (28, "Status praesens, status nervosus"), (41, "Кожные покровы"),
         (48, "Мышечная и костно-суставная система"), (52, "Дыхательная система"),
         (58, "Сердечно-сосудистая система"), (64, "Желудочно-кишечный тракт"),
         (72, "Мочевыделительная система"), (78, "Status localis"),
         (83, "Предварительный диагноз"), (88, "План обследования и лечения")),
        {3: "complaints", 7: "anamnesis_morbi", 13: "allergies", 15: "medications",
         18: "anamnesis_vitae", 29: "objective_status", 42: "vital_signs.temperature",
         53: "vital_signs.respiratory_rate", 59: "vital_signs", 85: "diagnosis"},
        89, 90, 91, 96, 85,
        {18: "Перенесенные инфекции и туберкулез", 42: "Видимые слизистые",
         53: "Тип дыхания", 59: "Пульс и ритм"},
        {79: "Status localis", 89: "План обследования", 90: "План лечения"},
    ),
    "cardiologist": SourceSpec(
        "Осмотр кардиолога (первичный)", "Осмотр кардиолога (первичный).docx",
        ((3, "Жалобы и анамнез"), (11, "Status praesens"), (32, "Предварительный диагноз"),
         (35, "План обследования"), (41, "План ведения")),
        {3: "complaints", 4: "anamnesis_morbi", 5: "anamnesis_vitae", 7: "allergies",
         11: "objective_status", 22: "vital_signs.temperature", 27: "vital_signs.heart_rate",
         28: "vital_signs.blood_pressure", 33: "diagnosis"},
        36, 43, 42, 48, 33,
        {5: "Инфекции и вирусный гепатит", 22: "Периферические лимфоузлы",
         27: "Ритм и тоны сердца", 28: "Пульс и дефицит пульса"},
        {29: "Сердечные шумы", 31: "Печень"},
    ),
    "pediatrician": SourceSpec(
        "Осмотр педиатра", "Осмотр педиатра.docx",
        ((3, "Жалобы и анамнез"), (16, "Status praesens"), (49, "Предварительный диагноз"),
         (52, "План обследования"), (58, "План ведения")),
        {3: "complaints", 4: "anamnesis_morbi", 5: "anamnesis_vitae", 10: "allergies",
         17: "objective_status", 27: "vital_signs.temperature", 37: "vital_signs.respiratory_rate",
         39: "vital_signs", 50: "diagnosis"},
        53, 60, 59, 65, 50,
        {5: "Беременность и роды", 27: "Периферические лимфоузлы"},
        {6: "Срок рождения и антропометрия", 7: "Вскармливание, вакцинация и развитие",
         8: "Перенесенные болезни и операции", 9: "Гемотрансфузии",
         13: "Эпидемиологический анамнез", 28: "Мышцы и антропометрия",
         30: "Форма головы и швы", 31: "Роднички и окружности"},
    ),
    "proctologist": SourceSpec(
        "Осмотр проктолога", "Осмотр проктолога.docx",
        ((3, "Жалобы и анамнез"), (8, "Status praesens"), (15, "Status localis"),
         (21, "Предварительный диагноз"), (24, "План обследования и ведения")),
        {3: "complaints", 4: "anamnesis_morbi", 5: "anamnesis_vitae", 6: "allergies",
         8: "objective_status", 21: "diagnosis"},
        25, 25, 25, 26, 21,
        {5: "Инфекции и наследственность", 6: "Перенесенные заболевания"},
        {12: "Отеки, лимфоузлы, язык и живот", 13: "Живот, печень, селезенка и стул",
         14: "Прямая кишка", 16: "Перианальная область",
         17: "Наружные геморроидальные узлы, тонус сфинктера и прямая кишка",
         18: "Слизистая и содержимое прямой кишки", 19: "Объем осмотра",
         20: "Проводимые манипуляции"},
    ),
    "surgeon": SourceSpec(
        "Осмотр хирурга (первичный)", "Осмотр хирурга (первичный).docx",
        ((2, "Жалобы и анамнез"), (6, "Status praesens"), (29, "Status localis"),
         (32, "Предварительный диагноз"), (35, "План обследования"),
         (41, "План ведения")),
        {2: "complaints", 3: "anamnesis_morbi", 4: "anamnesis_vitae", 5: "allergies",
         6: "objective_status", 11: "vital_signs.temperature", 33: "diagnosis"},
        36, 43, 42, 48, 33,
        {4: "Туберкулез и вирусный гепатит", 5: "Перенесенные заболевания, операции и травмы",
         11: "Периферические лимфоузлы"},
        {12: "Костно-суставная и сосудистая система", 18: "Живот и пальпация",
         27: "Прямая кишка", 28: "Дополнительные данные", 29: "Status localis",
         31: "Проводимые манипуляции"},
    ),
}


def _template_dir() -> Path:
    return Path(os.environ.get("TEMPLATES_DIR") or Path(__file__).resolve().parents[3] / "templates")


def _source_path(template_id: str) -> Path:
    return _template_dir() / SPECS[template_id].filename


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(W + "t"))


def _source_paragraphs(template_id: str) -> list[str]:
    with ZipFile(_source_path(template_id)) as source:
        root = ET.fromstring(source.read("word/document.xml"))
    return [_paragraph_text(paragraph) for paragraph in root.iter(W + "p")]


def _section(spec: SourceSpec, index: int) -> str:
    return next((name for start, name in reversed(spec.sections) if index >= start), spec.name)


def _is_heading(index: int, text: str, spec: SourceSpec) -> bool:
    if index == 0 or index in (start for start, _ in spec.sections):
        # Headings with clinical text in the same paragraph are handled below.
        return index not in spec.core and index not in spec.labels and index != spec.diagnosis
    return text.strip() in {"Status praesens:", "Status localis:", "ПРЕДВАРИТЕЛЬНЫЙ ДИАГНОЗ:",
                            "ПЛАН ОБСЛЕДОВАНИЯ:", "ПЛАН ВЕДЕНИЯ:"}


def _is_placeholder(text: str) -> bool:
    return not text.strip(" _\u00a0\t\r\n0123456789).")


CORE_LABELS = {
    "complaints": "Жалобы", "anamnesis_morbi": "Анамнез заболевания",
    "anamnesis_vitae": "Анамнез жизни", "allergies": "Аллергоанамнез",
    "medications": "Принимаемые препараты", "objective_status": "Объективный статус",
    "diagnosis": "Предварительный диагноз", "recommendations": "План ведения и рекомендации",
    "vital_signs": "Показатели", "vital_signs.temperature": "Температура",
    "vital_signs.blood_pressure": "АД", "vital_signs.heart_rate": "ЧСС",
    "vital_signs.respiratory_rate": "ЧДД",
}


# Reviewed against every clinical paragraph in the six source documents.
# These labels name the finding being requested; the original printed
# alternatives remain only in `prompt`, never in an approved DOCX label.
SPECIALTY_LABELS: dict[str, dict[int, str]] = {
    "therapist": {
        5: "Инфекционные заболевания и наследственность",
        6: "Гинекологический анамнез и перенесенные заболевания",
        7: "Операции и травмы", 8: "Вредные привычки",
        9: "Жилищно-бытовые условия и питание", 12: "Сознание",
        13: "Телосложение", 14: "Питание и ИМТ",
        15: "Кожные покровы и высыпания", 16: "Окраска кожи",
        17: "Цианоз", 18: "Влажность кожи", 19: "Видимые слизистые",
        20: "Особенности слизистых", 21: "Подкожная жировая клетчатка",
        22: "Отеки", 23: "Периферические лимфатические узлы",
        24: "Мышечная система", 25: "Костно-суставная система",
        26: "Дыхание через нос и рот", 27: "Форма грудной клетки",
        28: "Перкуссия легких", 29: "Аускультация легких",
        30: "Хрипы", 32: "Границы сердца", 34: "Тоны и шумы сердца",
        35: "Язык", 36: "Живот", 37: "Печень", 38: "Селезенка",
        39: "Стул", 40: "Симптом поколачивания", 41: "Мочеиспускание",
    },
    "therapist_initial": {
        14: "Наследственность", 18: "Перенесенные инфекции",
        19: "Инфекционные заболевания", 20: "Контакт с инфекционными больными",
        21: "Экстрагенитальные заболевания", 23: "Диспансерное наблюдение",
        25: "Госпитализации и операции", 27: "Гемотрансфузии и реакции",
        30: "Оценка тяжести состояния и причины", 31: "Сознание", 32: "Речь",
        33: "Слух", 34: "Зрение", 35: "Активность", 36: "Конституция",
        37: "Эмоциональный статус", 38: "Сон", 39: "Аппетит",
        40: "Длительность изменения аппетита", 42: "Видимые слизистые",
        43: "Зев", 44: "Кожа, тургор и влажность", 45: "Молочные железы",
        46: "Молочные железы и соски", 47: "Лимфатические узлы",
        49: "Костно-суставная система", 50: "Мышечная система",
        51: "Другие данные мышечной и костно-суставной системы",
        53: "Тип дыхания", 54: "Участие вспомогательной мускулатуры",
        55: "Кашель и мокрота", 56: "Аускультация легких",
        57: "Другие данные дыхательной системы", 59: "Пульс и ритм",
        60: "Отеки", 61: "Тоны сердца", 62: "Шумы сердца",
        63: "Другие данные сердечно-сосудистой системы",
        65: "Язык", 66: "Пищеварительные симптомы", 67: "Живот",
        68: "Печень", 69: "Болезненность печени при пальпации",
        70: "Стул", 71: "Другие данные пищеварительной системы",
        73: "Мочеиспускание", 74: "Недержание мочи",
        75: "Симптом поколачивания", 76: "Пальпация органов мочевыделения",
        77: "Другие данные мочевыделительной системы",
        79: "Status localis", 84: "Основание предварительного диагноза",
    },
    "cardiologist": {
        5: "Инфекционные заболевания", 6: "Наследственность",
        8: "Перенесенные заболевания", 9: "Внезапная смерть в семье",
        10: "Вредные привычки", 12: "Сознание и телосложение",
        13: "Питание и ИМТ", 14: "Кожные покровы и высыпания",
        15: "Окраска кожи", 16: "Цианоз", 17: "Влажность кожи",
        18: "Видимые слизистые", 19: "Особенности слизистых",
        20: "Подкожная жировая клетчатка", 21: "Отеки",
        22: "Периферические лимфатические узлы", 23: "Дыхание в легких",
        24: "Хрипы", 25: "Область сердца", 26: "Тоны сердца",
        27: "Ритм сердца", 28: "Пульс и дефицит пульса",
        29: "Сердечные шумы", 31: "Печень",
    },
    "pediatrician": {
        5: "Беременность и роды", 6: "Срок рождения и антропометрия",
        7: "Вскармливание, вакцинация и развитие",
        8: "Перенесенные заболевания и операции", 9: "Гемотрансфузии",
        11: "Жилищно-бытовые условия и питание", 12: "Наследственность",
        13: "Эпидемиологический анамнез", 14: "Место и время контакта",
        15: "Вредные привычки", 18: "Сознание",
        19: "Кожные покровы и высыпания", 20: "Окраска кожи",
        21: "Цианоз", 22: "Влажность кожи", 23: "Видимые слизистые",
        24: "Особенности слизистых", 25: "Подкожная жировая клетчатка",
        26: "Отеки", 27: "Периферические лимфатические узлы",
        28: "Мышцы и антропометрия", 29: "Костно-суставная система",
        30: "Форма головы и швы", 31: "Роднички и окружности",
        32: "Дыхание через нос и рот", 33: "Форма грудной клетки",
        34: "Перкуссия легких", 35: "Аускультация легких",
        36: "Хрипы", 38: "Границы сердца", 40: "Тоны и шумы сердца",
        41: "Язык", 42: "Живот", 43: "Печень", 44: "Селезенка",
        45: "Стул", 46: "Симптом поколачивания", 47: "Мочеиспускание",
    },
    "proctologist": {
        5: "Инфекции и наследственность", 6: "Перенесенные заболевания",
        7: "Операции и травмы", 9: "Сознание",
        10: "Кожа, высыпания, окраска и влажность",
        11: "Видимые слизистые", 12: "Отеки, лимфоузлы, язык и живот",
        13: "Живот, печень, селезенка и стул", 14: "Прямая кишка",
        16: "Перианальная область",
        17: "Наружные геморроидальные узлы, тонус сфинктера и прямая кишка",
        18: "Слизистая и содержимое прямой кишки", 19: "Объем осмотра",
        20: "Проводимые манипуляции",
    },
    "surgeon": {
        4: "Туберкулез и вирусный гепатит",
        5: "Перенесенные заболевания, операции и травмы",
        7: "Кожные покровы и высыпания", 8: "Окраска кожи",
        9: "Влажность кожи", 10: "Отеки",
        11: "Периферические лимфатические узлы",
        12: "Костно-суставная и сосудистая система", 13: "Язык",
        14: "Глотание", 15: "Форма живота", 16: "Грыжевые выпячивания",
        18: "Живот и пальпация", 20: "Свободная жидкость в брюшной полости",
        21: "Перистальтика кишечника", 22: "Печень",
        23: "Консистенция и край печени", 24: "Желчный пузырь",
        25: "Селезенка", 26: "Стул", 27: "Прямая кишка",
        28: "Дополнительные данные", 29: "Status localis",
        31: "Проводимые манипуляции",
    },
}


def _catalog(template_id: str) -> dict[str, Any]:
    spec = SPECS[template_id]
    paragraphs = _source_paragraphs(template_id)
    fields: list[dict[str, Any]] = []
    omit = {spec.follow_up}
    for index, text in enumerate(paragraphs):
        stripped = text.strip()
        if not stripped or index in omit or _is_heading(index, text, spec):
            continue
        if index == 1 and spec.name == "Первичный осмотр врача терапевта":
            continue
        if index in (1, 2) and stripped.startswith(("Дата_", "Обратилась:")):
            continue
        if index in (spec.exam_plan, spec.management_plan, spec.regimen):
            # Their structured entries below replace the printed list/alternatives.
            continue
        if _is_placeholder(text) and index != spec.diagnosis and index not in spec.labels:
            continue
        core_name = spec.core.get(index)
        if core_name:
            fields.append({"key": f"core_{index:03d}", "label": CORE_LABELS[core_name],
                           "prompt": f"ПРЕДВАРИТЕЛЬНЫЙ ДИАГНОЗ: {stripped}" if index == spec.diagnosis else stripped,
                           "section": _section(spec, index),
                           "paragraph_index": index, "clinical_field": core_name})
            if index not in spec.extra_specialty:
                continue
        try:
            label = SPECIALTY_LABELS[template_id][index]
        except KeyError as exc:
            raise RuntimeError(f"Unreviewed source paragraph {template_id}:{index}") from exc
        fields.append({"key": f"p_{index:03d}", "label": label,
                       "prompt": stripped, "section": _section(spec, index), "paragraph_index": index})
    for key, label, index, prompt in (
        ("exam_plan", "План обследования", spec.exam_plan, "ПЛАН ОБСЛЕДОВАНИЯ: пункты 1–5"),
        ("management_plan", "План ведения и лечения", spec.management_plan, "ПЛАН ВЕДЕНИЯ: пункты 1–5"),
        ("regimen_diet", "Режим и диета / стол", spec.regimen, "РЕЖИМ____ СТОЛ №____"),
        ("follow_up", "Явка к врачу", spec.follow_up, "Явка к врачу_____________"),
    ):
        field = {"key": key, "label": label, "prompt": prompt,
                 "section": _section(spec, index), "paragraph_index": index}
        if key == "management_plan":
            field["clinical_field"] = "recommendations"
        fields.append(field)
    return {"id": template_id, "name": spec.name, "fields": fields}


def list_templates() -> list[dict[str, Any]]:
    """Return the source-backed public catalog in stable specialty order."""
    return [_catalog(template_id) for template_id in SPECS]


def get_template(template_id: str) -> dict[str, Any]:
    """Return one catalog entry; IDs are from the fixed whitelist only."""
    if template_id not in SPECS:
        raise KeyError(template_id)
    return _catalog(template_id)


def validate_template_fields(template_id: str, data: ConsultationData) -> None:
    """Reject keys outside the selected form and duplicated common fields."""
    template = get_template(template_id)
    permitted = {field["key"] for field in template["fields"] if "clinical_field" not in field}
    seen: set[str] = set()
    for entry in data.template_fields:
        if entry.key not in permitted or entry.key in seen:
            raise ValueError("Invalid or duplicate template field key")
        seen.add(entry.key)


def _replace_paragraph(paragraph: ET.Element, value: str) -> None:
    # XML 1.0 cannot contain most C0 controls, even inside escaped text.
    value = sanitize_text(value)
    first_run = paragraph.find(W + "r")
    style = first_run.find(W + "rPr") if first_run is not None else None
    for child in list(paragraph):
        if child.tag != W + "pPr":
            paragraph.remove(child)
    run = ET.SubElement(paragraph, W + "r")
    if style is not None:
        run.append(ET.fromstring(ET.tostring(style)))
    chunks = value.split("\n")
    for position, chunk in enumerate(chunks):
        if position:
            ET.SubElement(run, W + "br")
        node = ET.SubElement(run, W + "t")
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        node.text = chunk


def render_docx(
    template_id: str,
    data: ConsultationData,
    *,
    patient_id: str,
    consultation_id: str,
    doctor_name: str,
    approved_at: datetime,
) -> bytes:
    """Fill an unchanged bundled OOXML source, preserving its layout and styles."""
    validate_template_fields(template_id, data)
    spec = SPECS[template_id]
    fields = get_template(template_id)["fields"]
    by_paragraph: dict[int, list[dict[str, Any]]] = {}
    for field in fields:
        by_paragraph.setdefault(field["paragraph_index"], []).append(field)
    entries = {entry.key: entry.value for entry in data.template_fields}
    approved_utc = approved_at.replace(tzinfo=timezone.utc) if approved_at.tzinfo is None else approved_at.astimezone(timezone.utc)
    approved_label = approved_utc.strftime("%d.%m.%Y %H:%M UTC")
    source_path = _source_path(template_id)
    with ZipFile(source_path) as source:
        root = ET.fromstring(source.read("word/document.xml"))
        # mc:Ignorable references these prefixes even when the element tree
        # contains no actual w14/wp14 tags; keep them declared for Word.
        root.set("xmlns:w14", "http://schemas.microsoft.com/office/word/2010/wordml")
        root.set("xmlns:wp14", "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing")
        paragraphs = list(root.iter(W + "p"))
        plan_ranges: set[int] = set()
        for start, end in ((spec.exam_plan, spec.management_plan), (spec.management_plan, spec.follow_up)):
            plan_ranges.update(i for i in range(start + 1, end) if i not in by_paragraph)
        for index, paragraph in enumerate(paragraphs):
            original = _paragraph_text(paragraph)
            if index == 0 or (index == 1 and template_id == "therapist_initial"):
                continue
            if index == spec.follow_up:
                follow_up = entries.get("follow_up") or EMPTY
                _replace_paragraph(paragraph, f"Явка к врачу: {follow_up}. Врач: {doctor_name}. Подпись врача: не проставлена")
                continue
            if original.strip().startswith(("Дата_", "Обратилась:")):
                _replace_paragraph(paragraph, f"Дата утверждения: {approved_label}")
                continue
            if index in plan_ranges:
                _replace_paragraph(paragraph, "")
                continue
            if index in by_paragraph:
                parts = []
                for field in by_paragraph[index]:
                    value = _core_value(data, field["clinical_field"]) if "clinical_field" in field else (entries.get(field["key"]) or EMPTY)
                    parts.append(f"{field['label']}: {value}")
                    if field.get("clinical_field") == "diagnosis" and data.diagnosis_code:
                        parts.append(f"Код МКБ-10: {data.diagnosis_code}")
                _replace_paragraph(paragraph, "; ".join(parts))
            elif _is_placeholder(original):
                _replace_paragraph(paragraph, "")
        # A clear administrative header is inserted after the source title.
        body = root.find(W + "body")
        assert body is not None
        title = next(iter(body.iter(W + "p")))
        header = ET.Element(W + "p")
        _replace_paragraph(header, f"ID пациента: {patient_id}; ID консультации: {consultation_id}; Утверждено: {approved_label}")
        body.insert(list(body).index(title) + 1, header)
        # Core data with no printed slot is retained without inventing a finding.
        mapped = {field["clinical_field"] for field in fields if "clinical_field" in field}
        residual = []
        for path, label in (("anamnesis_vitae", "Анамнез жизни"), ("allergies", "Аллергия"),
                            ("medications", "Принимаемые препараты"),
                            ("objective_status", "Объективный статус"),
                            ("prescribed_medications", "Назначенные препараты"),
                            ("additional_notes", "Дополнительные сведения")):
            if path not in mapped:
                value = _core_value(data, path)
                if value != EMPTY:
                    residual.append(f"{label}: {value}")
        if data.vital_signs is not None and "vital_signs" not in mapped:
            names = {"temperature": "Температура", "blood_pressure": "АД", "heart_rate": "ЧСС",
                     "respiratory_rate": "ЧДД", "oxygen_saturation": "SpO₂"}
            for name, label in names.items():
                value = getattr(data.vital_signs, name)
                if value and f"vital_signs.{name}" not in mapped:
                    residual.append(f"{label}: {value}")
        if residual:
            extra = ET.Element(W + "p")
            _replace_paragraph(extra, "; ".join(residual))
            body.insert(list(body).index(header) + 1, extra)
        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        output = BytesIO()
        with ZipFile(output, "w") as target:
            for member in source.infolist():
                target.writestr(member, xml if member.filename == "word/document.xml" else source.read(member.filename))
    return output.getvalue()


from .pdf import render_pdf  # noqa: E402  -- public renderer, imported after catalog setup
