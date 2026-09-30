#!/usr/bin/env python3
"""Run P0 acceptance against disposable SQLite, local providers, and Nginx.

Build the frontend first with Node 22: npm run build. No configured database,
dotenv file, real recording, API key, or running MedHub process is used.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import closing, contextmanager
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import wave
import zipfile

import httpx
import uvicorn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.grounding import assert_canonical_source, mask_segments, validate_evidence  # noqa: E402
from app.providers.base import ProviderError  # noqa: E402
from app.schemas import (  # noqa: E402
    ConsultationData, EvidenceClaim, ExtractionResult, StoredTranscriptSegment,
    TemplateFieldValue, Transcript, TranscriptSegment, VitalSigns,
)


ORIGINAL_SEGMENTS = (
    "Пациент: Меня зовут Айгуль Садыкова, ИИН 900101300456. Есть сухой кашель.",
    "Врач: Кашель длится три дня, температура 38 градусов.",
)
CORRECTED_SECOND = "Врач: Кашель длится четыре дня, температура 38 градусов."
LONG_RU_KZ = ("Синтетическая запись: бақылау және повторный осмотр через неделю. " * 55).strip()
TEMPLATE_IDS = ("therapist", "therapist_initial", "cardiologist", "pediatrician", "proctologist", "surgeon")
BROWSER_SCRIPTS = ("browser_smoke.py", "recorder_smoke.py")
CONFIG_ENV_KEYS = frozenset({
    "APP_MODE", "DATABASE_URL", "DATABASE_URL_FILE", "JWT_SECRET", "JWT_SECRET_FILE",
    "DOCTOR_USERNAME", "DOCTOR_PASSWORD_HASH", "DOCTOR_PASSWORD_HASH_FILE",
    "OPENAI_API_KEY", "OPENAI_API_KEY_FILE", "OPENAI_MODEL", "LLM_PROVIDER",
    "WHISPER_MODEL", "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "AUDIO_STORAGE_DIR",
    "AUDIO_RETENTION_DAYS", "CORS_ORIGINS", "MAX_UPLOAD_MB",
})


@contextmanager
def isolated_settings_environment():
    configured = {key: os.environ.pop(key) for key in CONFIG_ENV_KEYS if key in os.environ}
    try:
        yield
    finally:
        os.environ.update(configured)


def synthetic_wav() -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80000)
    return buffer.getvalue()


def declared_source(revision: int):
    if revision not in (1, 2):
        raise ValueError("Only declared synthetic revisions are supported")
    second = ORIGINAL_SEGMENTS[1] if revision == 1 else CORRECTED_SECOND
    return mask_segments([
        StoredTranscriptSegment(id="seg-000001", start=0.0, end=4.0, text=ORIGINAL_SEGMENTS[0]),
        StoredTranscriptSegment(id="seg-000002", start=4.0, end=9.0, text=second),
    ], revision=revision)


class SyntheticSTT:
    async def transcribe(self, audio_path: str) -> Transcript:
        if Path(audio_path).read_bytes() != synthetic_wav():
            raise ProviderError("Only the declared synthetic audio is supported")
        await asyncio.sleep(0.8)
        return Transcript(language="ru", duration=9.0, stt_model="p0-synthetic", segments=[
            TranscriptSegment(start=0.0, end=4.0, text=ORIGINAL_SEGMENTS[0]),
            TranscriptSegment(start=4.0, end=9.0, text=ORIGINAL_SEGMENTS[1]),
        ])


class SyntheticLLM:
    async def extract_consultation(self, source, *, template_fields=None, on_stage=None) -> ExtractionResult:
        assert_canonical_source(source)
        if source != declared_source(source.revision):
            raise ProviderError("Only declared synthetic corrections are supported")
        if on_stage:
            on_stage("llm_extraction", "running", 1)
        await asyncio.sleep(0.6)
        specialty = next((field["key"] for field in (template_fields or []) if not field.get("clinical_field")), None)
        days = "три" if source.revision == 1 else "четыре"
        data = ConsultationData(
            complaints=["сухой кашель"], anamnesis_morbi=f"Кашель длится {days} дня.",
            vital_signs=VitalSigns(temperature="38 градусов"),
            diagnosis="Синтетическое заключение: бронхит",
            recommendations=["Повторный осмотр через неделю"],
            additional_notes=LONG_RU_KZ,
            template_fields=[TemplateFieldValue(key=specialty, value=LONG_RU_KZ)] if specialty else [],
        )
        result = ExtractionResult(data=data, evidence=[
            EvidenceClaim(field_path="complaints/0", segment_id="seg-000001", quote="сухой кашель"),
            EvidenceClaim(field_path="anamnesis_morbi", segment_id="seg-000002", quote=f"Кашель длится {days} дня"),
            EvidenceClaim(field_path="vital_signs/temperature", segment_id="seg-000002", quote="температура 38 градусов"),
        ])
        if on_stage:
            on_stage("llm_extraction", "done", 1)
            on_stage("output_validation", "running", 1)
        validate_evidence(result, source)
        if on_stage:
            on_stage("output_validation", "done", 1)
        return result


def free_port() -> int:
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def nginx_config(output: Path, *, api_port: int, web_port: int, dist: Path) -> Path:
    (output / "nginx-body").mkdir(mode=0o700, exist_ok=True)
    server = (ROOT / "deploy/nginx.conf").read_text(encoding="utf-8")
    server = server.replace("listen 80;", f"listen 127.0.0.1:{web_port};")
    server = server.replace("root /usr/share/nginx/html;", f"root {dist};")
    server = server.replace("proxy_pass http://api:8000;", f"proxy_pass http://127.0.0.1:{api_port};")
    config = output / "nginx-acceptance.conf"
    config.write_text(
        f"worker_processes 1; pid {output / 'nginx.pid'}; error_log {output / 'nginx-error.log'}; "
        f"events {{ worker_connections 128; }} http {{ access_log off; client_body_temp_path {output / 'nginx-body'}; include /etc/nginx/mime.types; "
        f"default_type application/octet-stream; {server} }}", encoding="utf-8",
    )
    return config


async def wait_health(client: httpx.AsyncClient, *, server: uvicorn.Server) -> None:
    for _ in range(100):
        if server.started:
            try:
                response = await client.get("/api/v1/health")
                if response.status_code == 200:
                    return
            except httpx.TransportError:
                pass
        await asyncio.sleep(0.05)
    raise RuntimeError("Disposable API did not become ready")


def expect_response(response: httpx.Response, status: int) -> dict:
    if response.status_code != status:
        raise AssertionError(f"Unexpected synthetic API status {response.status_code} at {response.request.url.path}")
    return response.json()


async def api_acceptance(base_url: str, session_factory, output: Path) -> dict:
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        login = expect_response(await client.post("/api/v1/auth/login", json={"username": "doctor", "password": "demo-doctor"}), 200)
        client.headers["Authorization"] = f"Bearer {login['access_token']}"
        templates = expect_response(await client.get("/api/v1/templates"), 200)
        assert {item["id"] for item in templates} == set(TEMPLATE_IDS)
        checks: list[str] = []
        public_id = ""
        public_pdf = ""
        for template_id in TEMPLATE_IDS:
            created = expect_response(await client.post("/api/v1/consultations", json={
                "external_patient_id": f"SYNTHETIC-P0-{template_id.upper()}", "template_id": template_id,
            }), 201)
            path = f"/api/v1/consultations/{created['id']}"
            upload = await client.post(path + "/audio", files={"file": ("synthetic.wav", synthetic_wav(), "audio/wav")})
            expect_response(upload, 200)
            in_flight = asyncio.create_task(client.post(path + "/transcribe"))
            await asyncio.sleep(0.2)
            running = expect_response(await client.get(path), 200)
            assert running["status"] == "PROCESSING", running["status"]
            transcript = expect_response(await in_flight, 200)
            assert transcript["revision"] == 1 and len(transcript["segments"]) == 2
            assert "900101300456" not in transcript["masked_text"]
            assert transcript["segments"][1]["start"] == 4.0
            draft = expect_response(await client.post(path + "/generate"), 200)
            assert draft["source_transcript_revision"] == 1 and draft["evidence"]
            if template_id == "therapist":
                corrected = expect_response(await client.patch(path + "/transcript", json={
                    "expected_revision": 1, "changes": [{"segment_id": "seg-000002", "text": CORRECTED_SECOND}],
                }), 200)
                assert corrected["revision"] == 2
                assert (await client.get(path + "/document")).status_code in (404, 409)
                assert (await client.patch(path + "/transcript", json={
                    "expected_revision": 1, "changes": [{"segment_id": "seg-000002", "text": CORRECTED_SECOND}],
                })).status_code == 409
                draft = expect_response(await client.post(path + "/generate"), 200)
                assert draft["source_transcript_revision"] == 2
                checks.append("correction-conflict-regeneration")
            saved = expect_response(await client.patch(path + "/document", json={
                "version": draft["version"], "data": draft["data"],
            }), 200)
            approved = expect_response(await client.post(path + "/approve", json={"version": saved["version"]}), 200)
            assert approved["status"] == "APPROVED"
            pdf = await client.get(path + "/document.pdf")
            docx = await client.get(path + "/document.docx")
            assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
            assert docx.status_code == 200 and zipfile.is_zipfile(BytesIO(docx.content))
            with zipfile.ZipFile(BytesIO(docx.content)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8")
                assert "Синтетическое заключение" in xml
            if template_id == "therapist":
                info = subprocess.run(["pdfinfo", "-"], input=pdf.content, capture_output=True, check=True)
                pages = next(int(line.split(b":", 1)[1]) for line in info.stdout.splitlines() if line.startswith(b"Pages:"))
                assert pages >= 2, pages
                checks.append("multipage-ru-kz-pdf")
                from hashlib import sha256
                from sqlalchemy import select
                from app.models import ExportArtifact
                digest = sha256(pdf.content).hexdigest()
                with session_factory() as session:
                    artifact = session.scalar(select(ExportArtifact).where(ExportArtifact.sha256 == digest))
                    assert artifact is not None
                    public_id = artifact.public_id
                public_pdf = str(output / "synthetic-therapist.pdf")
                Path(public_pdf).write_bytes(pdf.content)
                async with httpx.AsyncClient(base_url=base_url, timeout=10) as anonymous:
                    record = expect_response(await anonymous.get(f"/api/v1/verification/{public_id}"), 200)
                assert set(record) == {"issuer", "issued_at", "status", "sha256"}
                assert record["issuer"] == "MedHub" and record["status"] == "valid" and record["sha256"] == digest
                assert "SYNTHETIC-P0" not in json.dumps(record)
                checks.append("anonymous-public-verification-safe-hash")
            checks.append(f"{template_id}-pdf-docx")
        return {"forms": len(TEMPLATE_IDS), "checks": checks, "public_id": public_id, "public_pdf": public_pdf}


async def run(args: argparse.Namespace) -> dict:
    dist = Path(args.dist).resolve()
    if not (dist / "index.html").is_file() or (not args.skip_browser and not list((dist / "assets").glob("*.mjs"))):
        raise RuntimeError("Build the integrated frontend first; browser acceptance needs the local PDF.js worker")
    output = Path(args.output).resolve() if args.output else Path(tempfile.mkdtemp(prefix="medhub-p0-acceptance-"))
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not str(output).startswith("/tmp/"):
        raise ValueError("Synthetic acceptance output must be below /tmp")
    with isolated_settings_environment():
        from app.main import create_app

    api_port, web_port = free_port(), free_port()
    settings = Settings(
        app_mode="demo", database_url=f"sqlite:///{output / 'synthetic.sqlite'}",
        jwt_secret="synthetic-only-secret-with-32-characters", llm_provider="demo",
        audio_storage_dir=output / "synthetic-audio", public_base_url=f"http://127.0.0.1:{web_port}",
    )
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="error", access_log=False))
    server.install_signal_handlers = lambda: None
    api_task = asyncio.create_task(server.serve())
    nginx = None
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{api_port}", timeout=2) as probe:
            await wait_health(probe, server=server)
        app.state.stt = SyntheticSTT()
        app.state.llm = SyntheticLLM()
        config = nginx_config(output, api_port=api_port, web_port=web_port, dist=dist)
        syntax = await asyncio.create_subprocess_exec("nginx", "-t", "-c", str(config), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, error = await syntax.communicate()
        if syntax.returncode != 0:
            raise RuntimeError(f"Disposable Nginx config invalid: {error.decode(errors='replace').strip()}")
        nginx = await asyncio.create_subprocess_exec("nginx", "-c", str(config), "-g", "daemon off;", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        result = await api_acceptance(f"http://127.0.0.1:{web_port}", app.state.session_factory, output)
        if not args.skip_browser:
            env = {key: value for key, value in os.environ.items() if key not in CONFIG_ENV_KEYS}
            env.update({"MEDHUB_BASE_URL": f"http://127.0.0.1:{web_port}", "MEDHUB_USERNAME": "doctor", "MEDHUB_PASSWORD": "demo-doctor", "MEDHUB_QA_OUTPUT": str(output), "MEDHUB_PUBLIC_ID": result["public_id"], "MEDHUB_PUBLIC_PDF": result["public_pdf"]})
            for script in BROWSER_SCRIPTS:
                browser = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / "scripts" / script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
                stdout, stderr = await browser.communicate()
                if browser.returncode != 0:
                    raise RuntimeError(f"Synthetic {script} acceptance failed: {stderr.decode(errors='replace')[-1200:]}")
                result["recorder" if script == "recorder_smoke.py" else "browser"] = json.loads(stdout.decode().splitlines()[-1])
        result.pop("public_id")
        result.pop("public_pdf")
        return {"status": "passed", "output": str(output), **result}
    finally:
        if nginx and nginx.returncode is None:
            nginx.terminate()
            await nginx.wait()
        server.should_exit = True
        await api_task


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", default=str(ROOT / "dist"))
    parser.add_argument("--output", help="Synthetic artifact directory under /tmp")
    parser.add_argument("--skip-browser", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
