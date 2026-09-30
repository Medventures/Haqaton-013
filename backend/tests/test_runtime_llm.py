from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.llm import OpenAIProvider
from app.schemas import ConsultationData, ExtractionResult


def test_explicit_openai_selection_from_environment(monkeypatch):
    monkeypatch.setenv("APP_MODE", "demo")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-key")
    settings = Settings.from_env()
    settings.validate()
    assert settings.effective_llm_provider == "openai"


def test_openai_requires_key_even_with_demo_login():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(app_mode="demo", llm_provider="openai").validate()


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        Settings(llm_provider="typo").validate()


def test_live_does_not_allow_demo_llm():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        Settings(app_mode="live", llm_provider="demo").validate()


@pytest.mark.parametrize("provider,expected", [("auto", "demo"), ("openai", "openai")])
def test_demo_login_and_actual_document_provider_are_independent(tmp_path: Path, monkeypatch, provider, expected):
    # Only the external operation is replaced; startup, selection, auth,
    # document persistence and response metadata all execute normally.
    async def extract(self, transcript, *, template_fields=None, on_stage=None):
        return ExtractionResult(data=ConsultationData(complaints=["synthetic OpenAI response"]))

    monkeypatch.setattr(OpenAIProvider, "extract_consultation", extract)
    settings = Settings(
        app_mode="demo", llm_provider=provider, openai_api_key="synthetic-key",
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        audio_storage_dir=tmp_path / "audio",
    )
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health").json()
        assert health["mode"] == "demo"
        assert health["llm_provider"] == expected
        assert health["llm_model"] == ("gpt-4.1-mini" if expected == "openai" else "demo")
        auth = client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"})
        assert auth.status_code == 200
        headers = {"Authorization": "Bearer " + auth.json()["access_token"]}
        created = client.post("/api/v1/consultations", headers=headers, json={"external_patient_id": "SYN-LLM-MODE"})
        prefix = "/api/v1/consultations/" + created.json()["id"]
        assert client.post(prefix + "/demo", headers=headers).status_code == 200
        response = client.post(prefix + "/generate", headers=headers)
        assert response.status_code == 200
        document = response.json()
        assert document["llm_provider"] == expected
        assert document["llm_model"] == health["llm_model"]
        assert ("synthetic OpenAI response" in document["data"]["complaints"]) == (expected == "openai")
