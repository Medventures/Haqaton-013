"""Local faster-whisper transcription; model download/load occurs on first real audio."""

import asyncio
import threading
from pathlib import Path

from app.providers.base import ProviderError
from app.schemas import Transcript, TranscriptSegment


class WhisperSTTProvider:
    def __init__(self, model: str = "small", device: str = "cpu", compute_type: str = "int8"):
        self.model_name = model
        self.device = device
        self.compute_type = compute_type
        self._model = None
        self._load_lock = threading.Lock()

    async def transcribe(self, audio_path: str) -> Transcript:
        if not Path(audio_path).is_file():
            raise ProviderError("Аудиозапись недоступна для распознавания.")
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_path)
        except Exception:
            raise ProviderError("Не удалось распознать аудиозапись.") from None

    def _transcribe_sync(self, audio_path: str) -> Transcript:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._model = WhisperModel(
                        self.model_name, device=self.device, compute_type=self.compute_type
                    )
        segments_iter, info = self._model.transcribe(audio_path, vad_filter=True)
        segments = [
            TranscriptSegment(start=float(segment.start), end=float(segment.end), text=segment.text.strip(), speaker=None)
            for segment in segments_iter
        ]
        return Transcript(
            language=info.language or "unknown",
            duration=float(info.duration or 0),
            stt_model=self.model_name,
            segments=segments,
        )
