"""The acceptance providers must never accept arbitrary clinical inputs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "p0_smoke.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("p0_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_full_acceptance_runs_both_browser_and_recorder_smokes():
    harness = load_harness()
    assert harness.BROWSER_SCRIPTS == ("browser_smoke.py", "recorder_smoke.py")


def test_app_import_does_not_inherit_configured_db_or_keys(monkeypatch):
    harness = load_harness()
    monkeypatch.setenv("DATABASE_URL_FILE", "/nonexistent/user-database-secret")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", "/nonexistent/user-openai-secret")
    monkeypatch.setenv("APP_MODE", "live")
    with harness.isolated_settings_environment():
        assert "DATABASE_URL_FILE" not in __import__("os").environ
        assert "OPENAI_API_KEY_FILE" not in __import__("os").environ
        assert "APP_MODE" not in __import__("os").environ
    assert __import__("os").environ["DATABASE_URL_FILE"] == "/nonexistent/user-database-secret"


@pytest.mark.asyncio
async def test_synthetic_stt_accepts_only_the_declared_audio(tmp_path):
    harness = load_harness()
    provider = harness.SyntheticSTT()
    path = tmp_path / "fixture.wav"
    path.write_bytes(harness.synthetic_wav())
    transcript = await provider.transcribe(str(path))
    assert len(transcript.segments) == 2
    assert transcript.segments[1].start > transcript.segments[0].start
    path.write_bytes(b"RIFF-not-the-declared-synthetic-audio")
    with pytest.raises(Exception):
        await provider.transcribe(str(path))


@pytest.mark.asyncio
async def test_synthetic_llm_accepts_only_declared_revisions_and_yields_grounded_evidence():
    harness = load_harness()
    provider = harness.SyntheticLLM()
    catalog = [{"key": "specialty_one", "clinical_field": None}]
    for revision in (1, 2):
        source = harness.declared_source(revision)
        result = await provider.extract_consultation(source, template_fields=catalog)
        assert result.data.template_fields[0].key == "specialty_one"
        assert len(result.data.additional_notes or "") > 2000
        assert result.evidence
        assert all(any(claim.quote in segment.text for segment in source.segments) for claim in result.evidence)
        assert "900101300456" not in source.text
    altered = harness.declared_source(1).model_copy(update={"text": "arbitrary clinical text"})
    with pytest.raises(Exception):
        await provider.extract_consultation(altered, template_fields=catalog)
