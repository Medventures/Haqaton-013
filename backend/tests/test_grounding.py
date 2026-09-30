import pytest

from app.grounding import assert_canonical_source, mask_segments, normalize_segments, validate_evidence
from app.schemas import (
    CanonicalTranscript, ConsultationData, EvidenceClaim, ExtractionResult,
    Medication, StoredTranscriptSegment, TemplateFieldValue, VitalSigns,
)


def segment(identifier: str, text: str, start: float = 0, end: float = 1) -> StoredTranscriptSegment:
    return StoredTranscriptSegment(id=identifier, start=start, end=end, text=text)


def test_cross_segment_pii_is_absent_from_provider_input():
    original = [
        segment("seg-000001", "ФИО: Иванов", 1, 2),
        segment("seg-000002", "Иван Иванович. ИИН 010203", 2, 3),
        segment("seg-000003", "500123. Телефон +7 701", 3, 4),
        segment("seg-000004", "123 45 67. Адрес: ул. Абая", 4, 5),
        segment("seg-000005", "10. Кашель три дня.", 5, 6),
    ]
    source = mask_segments(original, revision=3)
    serialized = "\n".join(item.model_dump_json() for item in source.segments)
    for secret in ("Иванов", "Иванович", "010203", "500123", "+7 701", "123 45 67", "Абая", "10."):
        assert secret not in serialized
        assert secret not in source.text
    assert "Кашель три дня" in source.text
    assert [(item.id, item.start, item.end) for item in source.segments] == [
        (item.id, item.start, item.end) for item in original
    ]
    assert source.text == "\n".join(item.text for item in source.segments)


def test_projection_handles_empty_and_unicode_segments():
    original = [
        segment("s1", "  ФИО: Әлиев  "),
        segment("s2", "  Ержан.  "),
        segment("s3", "   "),
        segment("s4", "Қызуы 38°С; жүрек соғысы 80."),
    ]
    normalized = normalize_segments(original)
    source = mask_segments(normalized, revision=1)
    assert len(source.segments) == 4
    assert [item.id for item in source.segments] == ["s1", "s2", "s3", "s4"]
    assert source.segments[2].text == ""
    assert "Әлиев" not in source.text and "Ержан" not in source.text
    assert "Қызуы 38°С; жүрек соғысы 80." in source.segments[3].text
    assert source.text == "\n".join(item.text for item in source.segments)


def test_projected_whitespace_remains_valid_evidence_source():
    source = mask_segments([
        segment("s1", "ИИН 010203", 2, 3),
        segment("s2", "500123 кашель три дня.", 3, 4),
    ], revision=6)
    assert source.segments[0].text == "ИИН [IIN_1]"
    assert source.segments[1].text == " кашель три дня."
    assert source.text == "ИИН [IIN_1]\n кашель три дня."
    assert_canonical_source(source)
    links = validate_evidence(ExtractionResult(
        data=ConsultationData(complaints=["кашель"]),
        evidence=[EvidenceClaim(field_path="complaints/0", segment_id="s2", quote=" кашель")],
    ), source)
    assert links[0].quote == " кашель"
    assert (links[0].start, links[0].end, links[0].transcript_revision) == (3, 4, 6)


def evidence_fixture() -> tuple[ExtractionResult, CanonicalTranscript]:
    result = ExtractionResult(data=ConsultationData(
        complaints=["сухой кашель"], anamnesis_morbi="три дня",
        medications=[Medication(name="Парацетамол", dosage="500 мг")],
        vital_signs=VitalSigns(temperature="38°С"),
        template_fields=[TemplateFieldValue(key="p_014", value="болезненность")],
        diagnosis_code="J20.9",
    ))
    source = CanonicalTranscript(
        revision=7,
        segments=[segment("s1", "Сухой кашель, три дня. Парацетамол 500 мг. Температура 38°С. Болезненность.", 12, 19)],
        text="Сухой кашель, три дня. Парацетамол 500 мг. Температура 38°С. Болезненность.",
    )
    return result, source


@pytest.mark.parametrize(("path", "quote"), [
    ("anamnesis_morbi", "три дня"),
    ("complaints/0", "Сухой кашель"),
    ("medications/0/name", "Парацетамол"),
    ("medications/0/dosage", "500 мг"),
    ("vital_signs/temperature", "38°С"),
    ("template_fields/p_014", "Болезненность"),
])
def test_evidence_accepts_only_populated_source_paths(path, quote):
    result, source = evidence_fixture()
    result.evidence = [EvidenceClaim(field_path=path, segment_id="s1", quote=quote)]
    links = validate_evidence(result, source)
    assert len(links) == 1
    assert links[0].start == source.segments[0].start
    assert links[0].end == source.segments[0].end
    assert links[0].transcript_revision == source.revision


@pytest.mark.parametrize("path", [
    "unknown", "complaints", "complaints/1", "complaints/-1", "complaints/0/name",
    "allergies/0", "medications/0/frequency", "medications/1/name",
    "vital_signs/heart_rate", "template_fields/missing", "diagnosis_code",
])
def test_evidence_rejects_unknown_or_empty_paths(path):
    result, source = evidence_fixture()
    result.evidence = [EvidenceClaim(field_path=path, segment_id="s1", quote="Сухой кашель")]
    with pytest.raises(ValueError):
        validate_evidence(result, source)


def test_evidence_rejects_duplicate_specialty_keys():
    result, source = evidence_fixture()
    result.data.template_fields.append(TemplateFieldValue(key="p_014", value="другое"))
    with pytest.raises(ValueError):
        validate_evidence(result, source)


@pytest.mark.parametrize(("segment_id", "quote"), [("missing", "Сухой кашель"), ("s1", "несуществующая цитата")])
def test_evidence_rejects_fabricated_ids_and_absent_quotes(segment_id, quote):
    result, source = evidence_fixture()
    result.evidence = [EvidenceClaim(field_path="complaints/0", segment_id=segment_id, quote=quote)]
    with pytest.raises(ValueError):
        validate_evidence(result, source)


def test_evidence_rejects_model_supplied_times_and_revisions():
    with pytest.raises(Exception):
        ExtractionResult.model_validate({
            "data": {},
            "evidence": [{"field_path": "complaints/0", "segment_id": "s1", "quote": "x", "start": 0, "transcript_revision": 99}],
        })


def test_empty_evidence_is_valid():
    result, source = evidence_fixture()
    assert validate_evidence(result, source) == []
