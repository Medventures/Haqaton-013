# Backend implementation report

Implemented the FastAPI `/api/v1` service, JWT login with doctor/admin roles, consultation ownership, finite audio uploads with MIME and file-header checks, local transcription orchestration, PII masking before LLM extraction, review/version approval, audit history, and durable mock MIS export. The six consultation domain tables plus users use SQLAlchemy, with portable Alembic migrations (JSON on SQLite, JSONB on PostgreSQL). Demo startup now runs Alembic on its configured database, so new local databases are versioned from creation.

Demo mode seeds only the explicit `doctor` / `demo-doctor` account and uses a synthetic transcript endpoint. Uploaded audio always goes through the STT provider. Live mode requires a strong JWT secret, doctor password hash, OpenAI key, and non-wildcard CORS. Secrets can be supplied with `*_FILE`. At live startup, any stored account still using the public demo password is revoked, even if its username differs from the configured live doctor.

State mutations use database guards, and document edits use a conditional version update. AI snapshots remain separate from the editable working copy; approval freezes the reviewed copy. A mock MIS reservation prevents duplicate exports. Single-instance startup marks interrupted `PROCESSING` consultations `FAILED` and releases unfinished mock MIS reservations for approved consultations. A periodic task and `python -m app.maintenance cleanup-audio` remove only expired registered audio outside active processing.

The six user-supplied DOCX forms are available through an authenticated catalog. Consultation creation fixes a template ID, and generation passes its field metadata to the extraction provider. PATCH rejects unknown or duplicate specialty keys. Only an approved or sent consultation can download a DOCX rendered from its approved snapshot; the approving user's name is frozen at approval. The supplied ICD CSV is searchable through an authenticated bounded endpoint. A diagnosis code is accepted only on physician edit if present in that catalog, then retained in audit, approval, DOCX and the MIS provider input. AI generation cannot assign a code.

Verification (2026-09-30):

- `.venv/bin/python -m pytest backend/tests -q` — **82 passed**, one third-party Starlette/httpx deprecation warning. TestClient had to run outside the command sandbox because its thread portal hung before app startup there.
- The migration regression upgrades an existing v1 consultation to v2 with `template_id=therapist`, downgrades, then re-upgrades without losing its row. A separate API test confirms a fresh demo database records `0002_consultation_template` in `alembic_version`.
- `python3 -m compileall -q backend/app backend/alembic` — passed after template integration.

Coverage includes unauthenticated access, per-doctor ownership, unknown roles, full demo review/approval/export, immutable AI snapshot, stale edits, rejected invalid transitions, duplicate export suppression, upload validation and size, retention protection, PII at the LLM boundary, live credential migration, restart recovery of a mock export, form selection/field validation, approved-only DOCX download and signer snapshot, bounded ICD search, validated doctor-selected code, and MIS code transfer.

Limits: PostgreSQL execution, an actual Whisper model download/transcription, OpenAI traffic, and Docker runtime were unavailable here. The MIS adapter is explicitly mock. A future real MIS adapter must reconcile an uncertain export after a crash rather than delete its reservation. The DOCX has a blank signature line; it is not digitally signed. PII redaction is conservative and requires a privacy review with the target deployment's real data patterns before using patient data.
