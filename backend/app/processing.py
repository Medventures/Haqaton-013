"""Measured operational stages; never store provider input or exception text."""
from __future__ import annotations

from copy import deepcopy
from time import monotonic_ns

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Consultation, ProcessingRunRow, now_utc
from .schemas import ProcessingStage


STAGES = {"upload": ("upload",), "transcribe": ("stt", "normalization", "pii_masking"),
          "generate": ("llm_extraction", "output_validation")}
ERRORS = {"upload": "UPLOAD_FAILED", "stt": "STT_FAILED", "normalization": "NORMALIZATION_FAILED",
          "pii_masking": "MASKING_FAILED", "llm_extraction": "LLM_FAILED", "output_validation": "VALIDATION_FAILED"}
SAFE_CODES = {*ERRORS.values(), "INTERRUPTED"}


class ProcessingTracker:
    def __init__(self, session_factory, consultation_id: str, operation: str):
        if operation not in STAGES:
            raise ValueError("Unknown operation")
        self.session_factory = session_factory
        self.consultation_id = consultation_id
        self.operation = operation
        self.run_id: str | None = None
        self._started: dict[tuple[str, int], int] = {}
        self._attempts: dict[str, int] = {}
        self._active: str | None = None

    def start(self) -> str:
        if self.run_id is not None:
            raise ValueError("Run already started")
        with self.session_factory() as session:
            row = ProcessingRunRow(consultation_id=self.consultation_id, operation=self.operation, status="running",
                stages=[ProcessingStage(key=key, attempt=1, status="pending").model_dump(mode="json") for key in STAGES[self.operation]])
            session.add(row)
            session.commit()
            self.run_id = row.id
        return self.run_id

    def latest_attempt(self, key: str) -> int:
        return self._attempts.get(key, 1)

    def failure_code(self, fallback: str) -> str:
        return ERRORS.get(self._active, fallback)

    def stage(self, key: str, state: str, attempt: int = 1) -> None:
        if key not in STAGES[self.operation] or state not in {"running", "done", "error"} or attempt < 1:
            raise ValueError("Invalid processing stage")
        if self.run_id is None:
            raise ValueError("Run not started")
        with self.session_factory() as session:
            row = session.get(ProcessingRunRow, self.run_id)
            if row.status != "running":
                raise ValueError("Run is terminal")
            stages = deepcopy(row.stages)
            stage = next((s for s in stages if s["key"] == key and s["attempt"] == attempt), None)
            if stage is None:
                if state != "running":
                    raise ValueError("Stage was not started")
                stage = ProcessingStage(key=key, attempt=attempt, status="pending").model_dump(mode="json")
                stages.append(stage)
            if stage["status"] == state:
                return
            timestamp = now_utc().isoformat()
            if state == "running":
                if stage["status"] != "pending":
                    raise ValueError("Stage is terminal")
                self._started[key, attempt] = monotonic_ns()
                self._attempts[key] = attempt
                self._active = key
                stage.update(status=state, started_at=timestamp)
            else:
                if stage["status"] != "running":
                    raise ValueError("Stage was not started")
                elapsed = max(0, (monotonic_ns() - self._started[key, attempt]) // 1_000_000)
                stage.update(status=state, finished_at=timestamp, duration_ms=elapsed,
                             error_code=ERRORS[key] if state == "error" else None)
                if state == "error":
                    self._active = key
            row.stages = stages
            session.commit()

    def _terminal(self, session: Session, state: str, error_code: str | None = None) -> None:
        if self.run_id is None:
            return
        row = session.get(ProcessingRunRow, self.run_id)
        stages = deepcopy(row.stages)
        at = now_utc()
        if state == "error":
            for stage in stages:
                if stage["status"] == "running":
                    start = self._started.get((stage["key"], stage["attempt"]))
                    stage.update(status="error", error_code=error_code, finished_at=at.isoformat(),
                                 duration_ms=max(0, (monotonic_ns() - start) // 1_000_000) if start is not None else None)
        row.stages = stages
        row.status = state
        row.finished_at = at

    def finish(self, *, session: Session | None = None) -> None:
        """Optional caller session makes terminal telemetry and clinical save atomic."""
        if session is not None:
            self._terminal(session, "done")
            return
        with self.session_factory() as owned:
            self._terminal(owned, "done")
            owned.commit()

    def fail(self, error_code: str, *, session: Session | None = None) -> None:
        if error_code not in SAFE_CODES:
            raise ValueError("Unknown processing error code")
        if session is not None:
            self._terminal(session, "error", error_code)
            return
        with self.session_factory() as owned:
            self._terminal(owned, "error", error_code)
            owned.commit()


def recover_interrupted_runs(session: Session) -> int:
    rows = session.scalars(select(ProcessingRunRow).where(ProcessingRunRow.status == "running")).all()
    at = now_utc()
    for row in rows:
        stages = deepcopy(row.stages)
        for stage in stages:
            if stage["status"] == "running":
                stage.update(status="error", error_code="INTERRUPTED", finished_at=at.isoformat(), duration_ms=None)
        row.stages = stages
        row.status = "error"
        row.finished_at = at
        consultation = session.get(Consultation, row.consultation_id)
        if consultation.status == "PROCESSING":
            consultation.status = "FAILED"
            consultation.error_message = "Обработка прервана. Повторите действие."
            consultation.updated_at = at
    return len(rows)
