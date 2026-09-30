import pytest
from pydantic import ValidationError

from app.schemas import ConsultationData, Medication, TranscriptSegment


def test_document_rejects_unexpected_clinical_fields():
    with pytest.raises(ValidationError):
        ConsultationData.model_validate({"invented_treatment": "anything"})


def test_draft_defaults_do_not_invent_medical_information():
    draft = ConsultationData()
    assert draft.diagnosis is None
    assert draft.medications == []
    assert draft.prescribed_medications == []
    assert draft.vital_signs is None


def test_medication_requires_nonblank_name():
    with pytest.raises(ValidationError):
        Medication(name=" ")


def test_segment_rejects_reversed_time():
    with pytest.raises(ValidationError):
        TranscriptSegment(start=5, end=2, text="Синтетический пример")


def test_specialty_values_are_retained_without_inventing_defaults():
    data = ConsultationData.model_validate({"template_fields": [
        {"key": "status_localis", "value": "Уточнение врача"},
        {"key": "growth", "value": None},
    ]})
    assert data.model_dump()["template_fields"][0]["value"] == "Уточнение врача"
    assert data.model_dump()["template_fields"][1]["value"] is None


def test_evidence_rejects_model_owned_times_and_blank_quote():
    from app.schemas import EvidenceClaim, ExtractionResult

    data = {"field_path": "complaints/0", "segment_id": "seg-000001", "quote": "  боль  "}
    assert EvidenceClaim.model_validate(data).quote == "  боль  "
    for extra in ({"start": 0.0}, {"end": 1.0}, {"transcript_revision": 1}):
        with pytest.raises(ValidationError):
            EvidenceClaim.model_validate({**data, **extra})
    with pytest.raises(ValidationError):
        EvidenceClaim.model_validate({**data, "quote": " \t\n "})
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate({"data": {}, "evidence": [{**data, "start": 0.0}]})
    assert ExtractionResult.model_validate({"data": {}, "evidence": [data]}).evidence[0].quote == "  боль  "


def test_transcript_patch_bounds():
    from app.schemas import TranscriptPatch

    valid = {"expected_revision": 1, "changes": [{"segment_id": "seg-000001", "text": "  исправлено  "}]}
    assert TranscriptPatch.model_validate(valid).changes[0].text == "  исправлено  "
    for invalid in (
        {**valid, "expected_revision": -1},
        {**valid, "expected_revision": 0},
        {**valid, "changes": [{"segment_id": "seg-000001", "text": "x" * 20001}]},
        {**valid, "changes": [{"segment_id": "seg-000001", "text": "a"}, {"segment_id": "seg-000001", "text": "b"}]},
        {**valid, "changes": [{"segment_id": "seg-000001", "text": "a", "start": 0.0}]},
    ):
        with pytest.raises(ValidationError):
            TranscriptPatch.model_validate(invalid)


def test_processing_stage_rejects_invented_duration_and_run_status():
    from app.schemas import ProcessingRun, ProcessingStage

    stage = {"key": "stt", "attempt": 1, "status": "pending"}
    assert ProcessingStage.model_validate(stage).duration_ms is None
    for change in ({"attempt": 0}, {"duration_ms": -1}, {"status": "unknown"}):
        with pytest.raises(ValidationError):
            ProcessingStage.model_validate({**stage, **change})
    with pytest.raises(ValidationError):
        ProcessingRun.model_validate({"id": "run-1", "operation": "unknown", "status": "running", "started_at": "2026-01-01T00:00:00Z", "stages": []})


def test_processing_stage_accepts_safe_codes_and_rejects_free_text():
    from app.schemas import ProcessingStage

    for code in ("UPLOAD_FAILED", "STT_FAILED", "NORMALIZATION_FAILED", "MASKING_FAILED", "LLM_FAILED", "VALIDATION_FAILED", "INTERRUPTED"):
        assert ProcessingStage(key="stt", attempt=1, status="error", error_code=code).error_code == code
    with pytest.raises(ValidationError):
        ProcessingStage(key="stt", attempt=1, status="error", error_code="Patient name: Иван Иванов")


def test_pending_processing_stage_has_no_measured_timing():
    from app.schemas import ProcessingStage

    base = {"key": "stt", "attempt": 1, "status": "pending"}
    assert ProcessingStage.model_validate(base).duration_ms is None
    for timing in (
        {"started_at": "2026-01-01T00:00:00Z"},
        {"finished_at": "2026-01-01T00:00:00Z"},
        {"duration_ms": 12},
    ):
        with pytest.raises(ValidationError):
            ProcessingStage.model_validate({**base, **timing})
