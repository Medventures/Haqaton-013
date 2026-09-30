"""Shared clinical contracts. Unknown fields are rejected at every boundary."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ConsultationStatus(StrEnum):
    CREATED = "CREATED"
    RECORDING = "RECORDING"
    PROCESSING = "PROCESSING"
    TRANSCRIBED = "TRANSCRIBED"
    AI_GENERATED = "AI_GENERATED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    SENT_TO_MIS = "SENT_TO_MIS"
    FAILED = "FAILED"


class Medication(StrictModel):
    name: ShortText
    dosage: ShortText | None = None
    frequency: ShortText | None = None
    duration: ShortText | None = None


class VitalSigns(StrictModel):
    temperature: ShortText | None = None
    blood_pressure: ShortText | None = None
    heart_rate: ShortText | None = None
    respiratory_rate: ShortText | None = None
    oxygen_saturation: ShortText | None = None


class TemplateFieldValue(StrictModel):
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    value: LongText | None = None


class ConsultationData(StrictModel):
    complaints: list[ShortText] = Field(default_factory=list, max_length=100)
    anamnesis_morbi: LongText | None = None
    anamnesis_vitae: LongText | None = None
    allergies: list[ShortText] = Field(default_factory=list, max_length=100)
    medications: list[Medication] = Field(default_factory=list, max_length=100)
    vital_signs: VitalSigns | None = None
    objective_status: LongText | None = None
    diagnosis: LongText | None = None
    diagnosis_code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=3, max_length=16, pattern=r"^[A-Z0-9.]+$")] | None = None
    recommendations: list[ShortText] = Field(default_factory=list, max_length=100)
    prescribed_medications: list[Medication] = Field(default_factory=list, max_length=100)
    additional_notes: LongText | None = None
    template_fields: list[TemplateFieldValue] = Field(default_factory=list, max_length=200)


class TranscriptSegment(StrictModel):
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(max_length=20000)
    speaker: ShortText | None = None

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end < self.start:
            raise ValueError("Segment end must not precede its start")
        return self


class StoredTranscriptSegment(TranscriptSegment):
    id: str = Field(min_length=1, max_length=64)


class TranscriptTextChange(StrictModel):
    segment_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=20000)


class TranscriptPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    changes: list[TranscriptTextChange] = Field(min_length=1, max_length=50000)

    @model_validator(mode="after")
    def valid_changes(self) -> Self:
        ids = [change.segment_id for change in self.changes]
        if len(ids) != len(set(ids)):
            raise ValueError("Segment IDs must be unique")
        if sum(len(change.text) for change in self.changes) > 500000:
            raise ValueError("Changed text is too long")
        return self


class Transcript(StrictModel):
    language: str = Field(min_length=2, max_length=12)
    duration: float = Field(ge=0, allow_inf_nan=False)
    segments: list[TranscriptSegment] = Field(default_factory=list, max_length=50000)
    stt_model: ShortText = "unknown"

    @property
    def raw_text(self) -> str:
        return " ".join(segment.text.strip() for segment in self.segments).strip()


class PIIEntity(StrictModel):
    type: str = Field(min_length=1, max_length=50)
    placeholder: str = Field(min_length=1, max_length=100)


class CanonicalTranscript(StrictModel):
    revision: int = Field(ge=1)
    segments: list[StoredTranscriptSegment] = Field(max_length=50000)
    text: str = Field(max_length=500000)
    entities: list[PIIEntity] = Field(default_factory=list)


class EvidenceClaim(StrictModel):
    field_path: str = Field(min_length=1, max_length=200)
    segment_id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=2000)

    @field_validator("quote")
    @classmethod
    def nonblank_quote(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Quote must contain non-whitespace text")
        return value


class EvidenceLink(EvidenceClaim):
    transcript_revision: int = Field(ge=1)
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_times(self) -> Self:
        if self.end < self.start:
            raise ValueError("Evidence end must not precede its start")
        return self


class ExtractionResult(StrictModel):
    data: ConsultationData
    evidence: list[EvidenceClaim] = Field(default_factory=list, max_length=1000)


class ProcessingStage(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    attempt: int = Field(ge=1)
    status: str = Field(pattern=r"^(pending|running|done|error)$")
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_code: Literal[
        "UPLOAD_FAILED", "STT_FAILED", "NORMALIZATION_FAILED", "MASKING_FAILED",
        "LLM_FAILED", "VALIDATION_FAILED", "INTERRUPTED",
    ] | None = None

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def pending_has_no_timing(self) -> Self:
        if self.status == "pending" and any(
            value is not None for value in (self.started_at, self.finished_at, self.duration_ms)
        ):
            raise ValueError("Pending stages cannot have measured timing")
        return self


class ProcessingRun(StrictModel):
    id: str = Field(min_length=1, max_length=36)
    operation: str = Field(pattern=r"^(upload|transcribe|generate)$")
    status: str = Field(pattern=r"^(running|done|error)$")
    started_at: datetime
    finished_at: datetime | None = None
    stages: list[ProcessingStage] = Field(default_factory=list)

    @field_validator("started_at", "finished_at")
    @classmethod
    def utc_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


class MaskedTranscript(StrictModel):
    text: str = Field(max_length=500000)
    entities: list[PIIEntity] = Field(default_factory=list)


class MISResult(StrictModel):
    success: bool
    document_id: str = Field(min_length=1, max_length=200)
    provider: str = "mock"
