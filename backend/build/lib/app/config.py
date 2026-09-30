from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def secret(name: str) -> str | None:
    file_path = os.getenv(f"{name}_FILE")
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()
    return os.getenv(name)


@dataclass(slots=True)
class Settings:
    app_mode: str = "demo"
    database_url: str = "sqlite:///./storage/medhub.db"
    jwt_secret: str = "demo-only-secret-change-for-production"
    doctor_username: str = "doctor"
    doctor_password_hash: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    llm_provider: str = "auto"
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    audio_storage_dir: Path = Path("storage/audio")
    audio_retention_days: int = 7
    cors_origins: list[str] = field(default_factory=list)
    max_upload_mb: int = 50

    @classmethod
    def from_env(cls) -> Settings:
        origins = json.loads(os.getenv("CORS_ORIGINS", "[]"))
        defaults = cls()
        return cls(
            app_mode=os.getenv("APP_MODE", "demo"),
            database_url=secret("DATABASE_URL") or defaults.database_url,
            jwt_secret=secret("JWT_SECRET") or defaults.jwt_secret,
            doctor_username=os.getenv("DOCTOR_USERNAME", "doctor"),
            doctor_password_hash=secret("DOCTOR_PASSWORD_HASH"),
            openai_api_key=secret("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            llm_provider=os.getenv("LLM_PROVIDER", "auto"),
            whisper_model=os.getenv("WHISPER_MODEL", "small"),
            whisper_device=os.getenv("WHISPER_DEVICE", "cpu"),
            whisper_compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            audio_storage_dir=Path(os.getenv("AUDIO_STORAGE_DIR", "storage/audio")),
            audio_retention_days=int(os.getenv("AUDIO_RETENTION_DAYS", "7")),
            cors_origins=origins,
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "50")),
        )

    @property
    def effective_llm_provider(self) -> str:
        if self.llm_provider == "auto":
            return "demo" if self.app_mode == "demo" else "openai"
        return self.llm_provider

    def validate(self) -> None:
        if self.app_mode not in {"demo", "live"}:
            raise ValueError("APP_MODE must be demo or live")
        if self.llm_provider not in {"auto", "demo", "openai"}:
            raise ValueError("LLM_PROVIDER must be auto, demo or openai")
        if self.app_mode == "live" and self.effective_llm_provider != "openai":
            raise ValueError("Live mode requires OpenAI LLM_PROVIDER")
        if self.effective_llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OpenAI provider requires OPENAI_API_KEY")
        if self.max_upload_mb <= 0 or self.max_upload_mb > 1024:
            raise ValueError("MAX_UPLOAD_MB is outside the supported range")
        if self.audio_retention_days <= 0:
            raise ValueError("AUDIO_RETENTION_DAYS must be positive")
        if not isinstance(self.cors_origins, list) or not all(isinstance(x, str) for x in self.cors_origins):
            raise ValueError("CORS_ORIGINS must be a JSON list of strings")
        if self.app_mode == "live":
            if len(self.jwt_secret) < 32 or self.jwt_secret == "demo-only-secret-change-for-production":
                raise ValueError("Live mode requires a strong JWT_SECRET")
            if not self.doctor_password_hash:
                raise ValueError("Live mode requires DOCTOR_PASSWORD_HASH")
            if any(origin == "*" for origin in self.cors_origins):
                raise ValueError("Wildcard CORS is unsafe in live mode")
