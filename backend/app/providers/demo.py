"""Clearly labelled synthetic fixture; never a fallback for uploaded audio."""

from typing import Callable

from app.grounding import assert_canonical_source, mask_segments, validate_evidence
from app.providers.base import ProviderError
from app.schemas import (
    CanonicalTranscript, ConsultationData, EvidenceClaim, ExtractionResult,
    Medication, StoredTranscriptSegment, Transcript, TranscriptSegment, VitalSigns,
)


_DEMO_TEXT = (
    "Врач: Что вас беспокоит? "
    "Пациент: Сухой кашель, слабость и температура до 38 градусов. "
    "Симптомы появились три дня назад. Принимал парацетамол 500 мг. "
    "Врач: Предварительный диагноз — острый бронхит."
)

DEMO_TRANSCRIPT = Transcript(
    language="ru",
    duration=34.0,
    stt_model="synthetic-demo",
    segments=[TranscriptSegment(start=0.0, end=34.0, text=_DEMO_TEXT, speaker=None)],
)


class DemoLLMProvider:
    async def extract_consultation(
        self, source: CanonicalTranscript, *, template_fields: list[dict] | None = None,
        on_stage: Callable[[str, str, int], None] | None = None,
    ) -> ExtractionResult:
        try:
            assert_canonical_source(source)
        except (TypeError, ValueError):
            raise ProviderError("Демо-извлечение поддерживает только синтетический пример.")
        fixture = mask_segments([
            StoredTranscriptSegment(id="seg-000001", start=0, end=34, text=DEMO_TRANSCRIPT.raw_text)
        ], revision=source.revision)
        if len(source.segments) != 1 or source.segments[0] != fixture.segments[0] or source.text != fixture.text:
            raise ProviderError("Демо-извлечение поддерживает только синтетический пример.")
        if on_stage:
            on_stage("llm_extraction", "running", 1)
        data = ConsultationData(
            complaints=["сухой кашель", "слабость", "температура до 38 градусов"],
            anamnesis_morbi="Симптомы появились три дня назад.",
            medications=[Medication(name="Парацетамол", dosage="500 мг")],
            vital_signs=VitalSigns(temperature="до 38 градусов"),
            diagnosis="Предварительный диагноз: острый бронхит",
        )
        result = ExtractionResult(data=data, evidence=[
            EvidenceClaim(field_path="complaints/0", segment_id="seg-000001", quote="Сухой кашель"),
            EvidenceClaim(field_path="complaints/1", segment_id="seg-000001", quote="слабость"),
            EvidenceClaim(field_path="complaints/2", segment_id="seg-000001", quote="температура до 38 градусов"),
            EvidenceClaim(field_path="anamnesis_morbi", segment_id="seg-000001", quote="Симптомы появились три дня назад"),
            EvidenceClaim(field_path="medications/0/name", segment_id="seg-000001", quote="парацетамол"),
            EvidenceClaim(field_path="medications/0/dosage", segment_id="seg-000001", quote="500 мг"),
            EvidenceClaim(field_path="vital_signs/temperature", segment_id="seg-000001", quote="температура до 38 градусов"),
            EvidenceClaim(field_path="diagnosis", segment_id="seg-000001", quote="Предварительный диагноз — острый бронхит"),
        ])
        if on_stage:
            on_stage("llm_extraction", "done", 1)
            on_stage("output_validation", "running", 1)
        validate_evidence(result, source)
        if on_stage:
            on_stage("output_validation", "done", 1)
        return result
