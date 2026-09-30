"""Provider contracts consumed by the consultation service."""

from pathlib import Path
from typing import Callable, Protocol

from app.schemas import CanonicalTranscript, ConsultationData, ExtractionResult, MISResult, Transcript


class ProviderError(RuntimeError):
    """A safe, payload-free integration error."""


class SpeechToTextProvider(Protocol):
    async def transcribe(self, audio_path: str) -> Transcript: ...


class LLMProvider(Protocol):
    async def extract_consultation(
        self, source: CanonicalTranscript, *, template_fields: list[dict] | None = None,
        on_stage: Callable[[str, str, int], None] | None = None,
    ) -> ExtractionResult: ...


class MISProvider(Protocol):
    async def send_consultation(
        self, consultation: ConsultationData, *, consultation_id: str, patient_id: str
    ) -> MISResult: ...


class StorageProvider(Protocol):
    def save(self, key: str, data: bytes) -> str: ...

    def get(self, key: str) -> Path: ...

    def delete(self, key: str) -> None: ...
