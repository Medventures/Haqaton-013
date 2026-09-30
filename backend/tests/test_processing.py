from concurrent.futures import ThreadPoolExecutor
from threading import Event

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Consultation, ProcessingRunRow
from app.schemas import ConsultationData, ExtractionResult, Transcript, TranscriptSegment
from test_transcript_revisions import client, sqlite_client, consultation, login, prepared


WAV = b"RIFF" + (0).to_bytes(4, "little") + b"WAVEfmt "


def upload(client, prefix, headers):
    return client.post(prefix + "/audio", headers=headers, files={"file": ("synthetic.wav", WAV, "audio/wav")})


def test_stage_updates_visible_before_request_finishes(client):
    headers = login(client)
    cid = consultation(client, headers)["id"]
    prefix = f"/api/v1/consultations/{cid}"
    assert upload(client, prefix, headers).status_code == 200
    entered, release = Event(), Event()
    class BlockingSTT:
        async def transcribe(self, _path):
            entered.set()
            assert release.wait(10)
            return Transcript(language="ru", duration=2, segments=[TranscriptSegment(start=0, end=2, text="Синтетический кашель")])
    client.app.state.stt = BlockingSTT()
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(TestClient(client.app).post, prefix + "/transcribe", headers=headers)
        try:
            assert entered.wait(10)
            summary = client.get(prefix, headers=headers).json()
            assert summary["status"] == "PROCESSING"
            runs = {run["operation"]: run for run in summary["processing_runs"]}
            assert runs["upload"]["status"] == "done"
            assert runs["upload"]["stages"][0]["duration_ms"] >= 0
            active = runs["transcribe"]
            assert active["status"] == "running"
            assert active["stages"][0]["status"] == "running"
            assert active["stages"][0]["started_at"] is not None
            for future in active["stages"][1:]:
                assert future["status"] == "pending"
                assert future["duration_ms"] is future["started_at"] is future["finished_at"] is None
            assert "percent" not in str(summary).lower()
        finally:
            release.set()
        assert pending.result(timeout=15).status_code == 200
    stages = client.get(prefix, headers=headers).json()["processing_runs"][-1]["stages"]
    assert [s["key"] for s in stages] == ["stt", "normalization", "pii_masking"]
    assert all(s["status"] == "done" and s["duration_ms"] >= 0 for s in stages)


def test_failed_retry_and_restart_preserve_actual_timings(client, caplog):
    headers, cid, prefix, _, _ = prepared(client)
    entered, release = Event(), Event()
    class RetryingLLM:
        async def extract_consultation(self, source, *, template_fields=None, on_stage=None):
            on_stage("llm_extraction", "running", 1)
            on_stage("llm_extraction", "done", 1)
            on_stage("output_validation", "running", 1)
            on_stage("output_validation", "error", 1)
            on_stage("llm_extraction", "running", 2)
            entered.set()
            assert release.wait(10)
            raise ValueError("SYNTHETIC_PRIVATE_TEXT")
    client.app.state.llm = RetryingLLM()
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(TestClient(client.app).post, prefix + "/generate", headers=headers)
        try:
            assert entered.wait(10)
            run = client.get(prefix, headers=headers).json()["processing_runs"][-1]
            assert [(s["key"], s["attempt"], s["status"]) for s in run["stages"]] == [
                ("llm_extraction", 1, "done"), ("output_validation", 1, "error"), ("llm_extraction", 2, "running")]
            completed_ms = run["stages"][0]["duration_ms"]
        finally:
            release.set()
        response = pending.result(timeout=15)
        assert response.status_code == 502
        assert "SYNTHETIC_PRIVATE_TEXT" not in response.text
    run = client.get(prefix, headers=headers).json()["processing_runs"][-1]
    assert run["status"] == "error"
    assert run["stages"][0]["duration_ms"] == completed_ms
    assert run["stages"][-1]["error_code"] == "LLM_FAILED"
    assert "SYNTHETIC_PRIVATE_TEXT" not in str(run)
    assert "SYNTHETIC_PRIVATE_TEXT" not in caplog.text

    from app.processing import ProcessingTracker, recover_interrupted_runs
    tracker = ProcessingTracker(client.app.state.session_factory, cid, "transcribe")
    tracker.start()
    tracker.stage("stt", "running")
    tracker.stage("stt", "done")
    tracker.stage("normalization", "running")
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "PROCESSING"
        session.commit()
        assert recover_interrupted_runs(session) == 1
        session.commit()
    with client.app.state.session_factory() as session:
        recovered = session.get(ProcessingRunRow, tracker.run_id)
        assert recovered.status == "error"
        assert recovered.stages[0]["status"] == "done"
        assert recovered.stages[0]["duration_ms"] >= 0
        assert recovered.stages[1]["error_code"] == "INTERRUPTED"
        assert recovered.stages[1]["duration_ms"] is None
        assert recovered.stages[2]["status"] == "pending"
        assert session.get(Consultation, cid).status == "FAILED"


def test_successful_generation_finishes_telemetry_in_clinical_transaction(client, monkeypatch):
    from app.processing import ProcessingTracker
    original_finish = ProcessingTracker.finish
    def finish_only_in_clinical_transaction(self, *, session=None):
        assert session is not None, "No independent telemetry cleanup after clinical commit"
        return original_finish(self, session=session)
    monkeypatch.setattr(ProcessingTracker, "finish", finish_only_in_clinical_transaction)
    headers, cid, prefix, _, _ = prepared(client)
    response = client.post(prefix + "/generate", headers=headers)
    assert response.status_code == 200
    summary = client.get(prefix, headers=headers).json()
    assert summary["status"] == "AI_GENERATED"
    run = summary["processing_runs"][-1]
    assert run["status"] == "done"
    assert [s["status"] for s in run["stages"]] == ["done", "done"]


def test_tracker_does_not_commit_unrelated_clinical_changes(client):
    from app.processing import ProcessingTracker
    headers, cid, _, _, _ = prepared(client)
    factory = client.app.state.session_factory
    with factory() as clinical:
        consultation = clinical.get(Consultation, cid)
        consultation.external_patient_id = "UNCOMMITTED_SENTINEL"
        tracker = ProcessingTracker(factory, cid, "generate")
        tracker.start()
        tracker.stage("llm_extraction", "running")
        with factory() as observer:
            assert observer.get(Consultation, cid).external_patient_id != "UNCOMMITTED_SENTINEL"
        clinical.rollback()


def test_startup_recovers_running_runs_without_changing_approved_or_completed(client):
    from app.main import create_app
    from app.processing import ProcessingTracker
    headers, cid, prefix, _, _ = prepared(client)
    tracker = ProcessingTracker(client.app.state.session_factory, cid, "transcribe")
    tracker.start()
    tracker.stage("stt", "running")
    tracker.stage("stt", "done")
    tracker.stage("normalization", "running")
    other = consultation(client, headers)["id"]
    done = ProcessingTracker(client.app.state.session_factory, other, "generate")
    done.start()
    done.stage("llm_extraction", "running")
    done.stage("llm_extraction", "done")
    done.stage("output_validation", "running")
    done.stage("output_validation", "done")
    done.finish()
    with client.app.state.session_factory() as session:
        session.get(Consultation, cid).status = "PROCESSING"
        session.get(Consultation, other).status = "APPROVED"
        session.commit()
        finished = session.get(ProcessingRunRow, done.run_id).stages
    # Use existing disposable schema; PG fixture started in live mode intentionally.
    from dataclasses import replace
    settings = replace(client.app.state.settings)
    if settings.database_url.startswith("postgresql"):
        settings.app_mode = "live"
    with TestClient(create_app(settings)):
        pass
    with client.app.state.session_factory() as session:
        assert session.get(ProcessingRunRow, tracker.run_id).status == "error"
        assert session.get(Consultation, cid).status == "FAILED"
        assert session.get(Consultation, other).status == "APPROVED"
        assert session.get(ProcessingRunRow, done.run_id).stages == finished


def test_summaries_return_only_latest_run_per_operation(client):
    headers, cid, prefix, _, _ = prepared(client)
    for _ in range(2):
        assert client.post(prefix + "/generate", headers=headers).status_code == 200
    summary = client.get(prefix, headers=headers).json()
    assert len(summary["processing_runs"]) == 1
    with client.app.state.session_factory() as session:
        runs = session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.consultation_id == cid).order_by(ProcessingRunRow.started_at)).all()
        assert len(runs) == 2
        assert summary["processing_runs"][0]["id"] == runs[-1].id
