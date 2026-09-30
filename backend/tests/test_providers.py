import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.grounding import mask_segments
from app.providers.demo import DEMO_TRANSCRIPT, DemoLLMProvider
from app.providers.mis import MockMISProvider
from app.providers.llm import OpenAIProvider
from app.providers.storage import LocalStorage
from app.providers.stt import WhisperSTTProvider
from app.schemas import ConsultationData, EvidenceClaim, ExtractionResult, StoredTranscriptSegment


def run(coro):
    return asyncio.run(coro)


def source(text: str, *, revision: int = 1):
    return mask_segments([StoredTranscriptSegment(id="seg-000001", start=0, end=34, text=text)], revision=revision)


def test_demo_provider_accepts_only_fixture_and_extracts_spoken_information():
    result = run(DemoLLMProvider().extract_consultation(source(DEMO_TRANSCRIPT.raw_text)))
    data = result.data
    assert data.medications[0].name.lower() == "парацетамол"
    assert data.medications[0].dosage == "500 мг"
    assert data.diagnosis is not None
    assert data.prescribed_medications == []
    with pytest.raises(Exception, match="Демо"):
        run(DemoLLMProvider().extract_consultation(source("Пациент говорит, что болит голова")))


def test_demo_evidence_only_uses_fixture_source():
    fixture = source(DEMO_TRANSCRIPT.raw_text, revision=4)
    result = run(DemoLLMProvider().extract_consultation(fixture))
    assert result.evidence
    assert all(link.segment_id == "seg-000001" for link in result.evidence)
    assert all(link.quote in fixture.segments[0].text for link in result.evidence)
    assert all(not hasattr(link, "start") and not hasattr(link, "transcript_revision") for link in result.evidence)
    with pytest.raises(Exception, match="Демо"):
        run(DemoLLMProvider().extract_consultation(mask_segments([
            StoredTranscriptSegment(id="seg-000001", start=0, end=1, text=DEMO_TRANSCRIPT.raw_text)
        ], revision=4)))


def test_openai_sends_only_masked_text_without_identifiers_or_mapping():
    calls = []
    expected = ExtractionResult(data=ConsultationData(complaints=["сухой кашель"]))

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=expected)

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    provider = OpenAIProvider(api_key="synthetic-key", model="gpt-4.1-mini", client=client)
    result = run(provider.extract_consultation(source("Иванов Иван Иванович, ИИН 010203500123. Сухой кашель.")))

    assert result.data.complaints == ["сухой кашель"]
    assert len(calls) == 1
    sent = str(calls[0])
    assert "010203500123" not in sent
    assert "Иванов" not in sent
    assert "synthetic-key" not in sent
    assert "[PERSON_1]" in sent and "[IIN_1]" in sent
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is ExtractionResult


def test_openai_retries_invalid_output_once_then_raises_safe_error():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed={"unexpected_clinical_field": "private value"})

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    with pytest.raises(Exception) as exc:
        run(provider.extract_consultation(source("Синтетический кашель.")))
    assert len(calls) == 2
    assert "private value" not in str(exc.value)


def test_openai_accepts_second_valid_structured_response():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(output_parsed=None)
        return SimpleNamespace(output_parsed=ExtractionResult(data=ConsultationData(complaints=["сухой кашель"])))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    data = run(provider.extract_consultation(source("Сухой кашель.")))
    assert len(calls) == 2
    assert data.data.complaints == ["сухой кашель"]


def test_openai_transport_error_is_safe_and_not_retried():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("secret audio and api key")

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    with pytest.raises(Exception) as exc:
        run(provider.extract_consultation(source("Синтетический кашель.")))
    assert len(calls) == 1
    assert "secret audio" not in str(exc.value)


def test_openai_discards_unknown_specialty_key_and_receives_selected_form():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        key = "not_in_template"
        return SimpleNamespace(output_parsed=ExtractionResult(data=ConsultationData.model_validate({
            "template_fields": [{"key": key, "value": "Болезненность в области осмотра"}]
        })))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    data = run(provider.extract_consultation(
        source("Меня зовут Иван Петров. При осмотре болезненность."),
        template_fields=[{"key": "local_status", "label": "Status localis", "prompt": "Локальный осмотр", "section": "Осмотр"}],
    ))
    assert len(calls) == 1
    assert data.data.template_fields == []
    assert "Status localis" in calls[0]["instructions"]
    assert "Иван Петров" not in calls[0]["input"]


def test_bad_citation_is_dropped_without_discarding_draft():
    calls = []
    events = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=ExtractionResult(
            data=ConsultationData(complaints=["кашель"]),
            evidence=[EvidenceClaim(field_path="complaints/0", segment_id="seg-000001", quote="выдуманная цитата")],
        ))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = run(provider.extract_consultation(source("ИИН 010203500123. Кашель."), on_stage=lambda *event: events.append(event)))
    assert len(calls) == 1
    assert result.data.complaints == ["кашель"]
    assert result.evidence == []
    assert "010203500123" not in str(calls)
    assert calls[0]["store"] is False
    assert events == [
        ("llm_extraction", "running", 1), ("llm_extraction", "done", 1),
        ("output_validation", "running", 1), ("output_validation", "done", 1),
    ]


def test_unknown_template_keys_and_model_diagnosis_code_are_discarded():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=ExtractionResult(
            data=ConsultationData(diagnosis_code="J20.9", template_fields=[
                {"key": "not_a_form_field", "value": "synthetic value"},
            ]),
        ))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = run(provider.extract_consultation(
        source("synthetic cough."),
        template_fields=[{"key": "valid_field", "label": "Synthetic", "prompt": "Synthetic", "section": "Synthetic"}],
    ))
    assert len(calls) == 1
    assert result.data.diagnosis_code is None
    assert result.data.template_fields == []


def test_openai_rejects_accidentally_unmasked_source_before_transport():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    unmasked = source("Кашель.")
    unmasked.segments[0].text = "ИИН 010203500123. Кашель."
    unmasked.text = unmasked.segments[0].text
    with pytest.raises(Exception):
        run(provider.extract_consultation(unmasked))
    assert calls == []


def test_openai_drops_evidence_not_found_in_transmitted_snapshot():
    original = source("Кашель три дня.")
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        original.segments[0].text = "Кашель три дня. Выдуманный фрагмент."
        original.text = original.segments[0].text
        return SimpleNamespace(output_parsed=ExtractionResult(
            data=ConsultationData(complaints=["кашель"]),
            evidence=[EvidenceClaim(
                field_path="complaints/0", segment_id="seg-000001", quote="Выдуманный фрагмент"
            )],
        ))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = run(provider.extract_consultation(original))
    assert len(calls) == 1
    assert "Выдуманный фрагмент" not in calls[0]["input"]
    assert result.data.complaints == ["кашель"]
    assert result.evidence == []


def test_openai_accepts_cross_segment_masked_source_with_literal_quote_spacing():
    calls = []
    masked = mask_segments([
        StoredTranscriptSegment(id="s1", start=2, end=3, text="ИИН 010203"),
        StoredTranscriptSegment(id="s2", start=3, end=4, text="500123 кашель три дня."),
    ], revision=6)

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=ExtractionResult(
            data=ConsultationData(complaints=["кашель"]),
            evidence=[EvidenceClaim(field_path="complaints/0", segment_id="s2", quote=" кашель")],
        ))

    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = run(provider.extract_consultation(masked))
    assert len(calls) == 1
    assert result.evidence[0].quote == " кашель"
    sent = json.loads(calls[0]["input"])
    assert sent["segments"][1] == {"id": "s2", "start": 3.0, "end": 4.0, "text": " кашель три дня."}
    assert "500123" not in calls[0]["input"]


def test_local_storage_rejects_traversal_and_symlink(tmp_path: Path):
    store = LocalStorage(tmp_path / "audio")
    assert store.save("consultation.webm", b"synthetic audio") == "consultation.webm"
    assert store.get("consultation.webm").read_bytes() == b"synthetic audio"
    for key in ("../outside", "/tmp/outside", "nested/../outside", "nested\\outside"):
        with pytest.raises(ValueError):
            store.save(key, b"x")
    outside = tmp_path / "outside"
    outside.write_bytes(b"preserve")
    (tmp_path / "audio" / "link.webm").symlink_to(outside)
    with pytest.raises(ValueError):
        store.get("link.webm")
    store.delete("consultation.webm")
    assert not (tmp_path / "audio" / "consultation.webm").exists()
    assert outside.read_bytes() == b"preserve"


def test_mock_mis_is_idempotent_for_consultation_id():
    provider = MockMISProvider()
    data = ConsultationData(complaints=["сухой кашель"])
    first = run(provider.send_consultation(data, consultation_id="synthetic-id", patient_id="synthetic-patient"))
    second = run(provider.send_consultation(data, consultation_id="synthetic-id", patient_id="synthetic-patient"))
    assert first.success is True
    assert first.document_id == second.document_id


def test_whisper_stays_lazy_until_real_audio_and_reports_safe_failure(tmp_path: Path):
    provider = WhisperSTTProvider()
    assert provider._model is None
    with pytest.raises(Exception) as exc:
        run(provider.transcribe(str(tmp_path / "absent.webm")))
    assert "absent.webm" not in str(exc.value)
    assert provider._model is None


def test_whisper_maps_real_audio_model_segments_without_demo_fallback(tmp_path: Path):
    uploaded = tmp_path / "uploaded.webm"
    uploaded.write_bytes(b"synthetic test bytes")
    calls = []

    class FakeWhisper:
        def transcribe(self, path, *, vad_filter):
            calls.append((path, vad_filter))
            return iter([SimpleNamespace(start=0.0, end=1.5, text="  Только загруженное аудио  ")]), SimpleNamespace(language="ru", duration=1.5)

    provider = WhisperSTTProvider()
    provider._model = FakeWhisper()
    transcript = provider._transcribe_sync(str(uploaded))
    assert transcript.raw_text == "Только загруженное аудио"
    assert transcript.duration == 1.5
    assert len(calls) == 1
    assert calls[0] == (str(uploaded), True)
