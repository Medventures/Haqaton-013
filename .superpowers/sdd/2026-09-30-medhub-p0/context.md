# MedHub P0 Trust Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved P0 workflow: correct a transcript, inspect masked sources and actual processing, review fresh clinical data, then preview and download approved PDF/DOCX documents.

**Architecture:** Keep the modular monolith and flat clinical schema. Add revision/evidence/stage persistence, a canonical masked extraction boundary, and an independent PDF renderer; integrate these through focused React components. Deliver backend contracts before dependent UI integration, with separate worker ownership and review gates.

**Tech Stack:** Existing Python 3.12/FastAPI/SQLAlchemy/Alembic/Pydantic, local Whisper and OpenAI Structured Outputs; React/TypeScript/Vite/TanStack Query; ReportLab with bundled Unicode fonts; locally bundled PDF.js.

**Spec:** `docs/superpowers/specs/2026-09-30-medhub-p0-design.md` (user-approved 2026-09-30).

## Global Constraints

- Keep `ConsultationData` and document `data` compatible.
- Existing clinical and approved data must be preserved.
- Keep the modular monolith and the current doctor's account.
- No token or medical data goes in URL query parameters.
- No raw-to-masked identifier mapping goes to OpenAI or the browser.
- Original source files and recorded patient data are not fixtures and must not be copied into tests or logs.
- Never infer normal findings from form alternatives; evidence proves provenance, not medical correctness.
- No percentage may imply elapsed-work accuracy; historical unknown timings stay unknown.
- Keep DOCX; PDF uses approved JSON, not DOCX conversion; retain `object-src 'none'`.
- No new external API call occurs during migration. Do not change the user's API key, password or database type.
- Do not approve or export the user's consultation on their behalf.
- Excluded features remain excluded as listed in the spec. No authentication redesign, real MIS, queue, embeddings, diagnosis inference, or transcription streaming.
- No usable Git repository is present. Do not initialize Git, create a worktree, commit, or modify protected configuration; record reviewed file lists and test results instead.

## Review Focus

1. PII spanning adjacent segments must not leak through evidence or the final provider input: Task 2 cross-boundary tests.
2. Edit/generate/save/approve races must not revive a stale document or overwrite a competing transcript correction: Task 4 conditional-write tests with two sessions.
3. A reordered or duplicated list item must not inherit another item's citation; cached documents must disappear immediately after invalidation: Task 7 UI tests.
4. Navigation/logout during slow audio/PDF fetches must not attach another patient's bytes or leave object URLs/workers alive: Tasks 7–8 cancellation tests.
5. Legacy approved documents and long RU/KZ specialty text must survive migration and render without omitted values or invalid markup: Tasks 1, 3 and 5 tests.

---

## Delivery and worker ownership

The user requested workers. Preserve that execution method. Use a fresh implementer and review gate per independently testable task; no two workers write the same file concurrently. Main agent coordinates interfaces, integration, verification and deployment. Read the required execution skill before dispatching.

| Task | Worker responsibility | Exclusive write area during task | Dependency |
| --- | --- | --- | --- |
| 1 | Persistence/contracts | `models.py`, `schemas.py`, migration, migration/schema tests | None |
| 2 | Masking/grounded extraction | `pii.py`, new `grounding.py`, provider contracts/LLM/demo, provider tests | 1 |
| 3 | Document projection/PDF | `forms/`, font assets, backend packaging, form/PDF tests | None |
| 4 | Revision workflow | new `transcripts.py`, `main.py`, `service.py`, revision/API tests | 1–2 |
| 5 | Processing and protected files | new `processing.py`, `main.py`, `service.py`, processing/file tests | 3–4 |
| 6 | Frontend contracts/panels | `types.ts`, `api.ts`, processing/privacy components and tests | 1–2, 4–5 |
| 7 | Transcript/evidence integration | `App.tsx`, `DocumentEditor.tsx`, transcript/evidence components, styles/tests | 6 |
| 8 | PDF preview | new PDF preview, `App.tsx`, dependencies/lockfile, Nginx CSP/tests | 5, 7 |
| 9 | Acceptance/deployment | smoke scripts, README, verified backup/migration/restart | All |

Task 3 is logically independent of Tasks 1–2; parallel dispatch is allowed only if the execution skill permits it and file ownership remains disjoint. Do not parallelize Tasks 4–5 or 7–8. Never run live API migration while workers are changing schemas.

### Shared contracts locked by this plan

- Leave STT `TranscriptSegment` input unchanged. Add `StoredTranscriptSegment(TranscriptSegment)` with `id: str`; deterministic IDs are `seg-000001`, `seg-000002`, … in original order and remain stable on text edits.
- `CanonicalTranscript`: `revision: int`, `segments: list[StoredTranscriptSegment]` containing only masked text, `text: str`, `entities: list[PIIEntity]`. No original-to-placeholder mapping.
- `EvidenceClaim`: `field_path: str` (1–200 characters), `segment_id: str` (1–64), `quote: str` (1–2000, non-whitespace; retain literal spacing). `ExtractionResult`: `data: ConsultationData`, `evidence: list[EvidenceClaim]` (maximum 1000). All models reject extra fields.
- `EvidenceLink(EvidenceClaim)` adds server-owned `transcript_revision: int`, `start: float`, `end: float`. Neither times nor revision appear in the model's output schema.
- `TranscriptPatch` contains `expected_revision: int` and `changes: list[TranscriptTextChange]`; `TranscriptTextChange` contains `segment_id: str` and `text: str`. Positive revision, unique known IDs, at most 50000 changes, each text at most 20000 characters, combined current text at most 500000 characters and not entirely blank.
- Transcript response retains existing properties and adds `revision`, `current_text`, `audio_available`. Its segments have IDs. Document response retains existing properties and adds `source_transcript_revision: number | null`, `evidence: EvidenceLink[]`, `source_masked_text: string | null`.
- Consultation summary adds `transcript_revision: number | null`, `audio_available: boolean`, `processing_runs: ProcessingRun[]` (latest run per operation, at most three). No clinical payload in these runs.
- `ProcessingRun`: `id`, `operation: upload | transcribe | generate`, `status: running | done | error`, UTC `started_at`, nullable `finished_at`, and ordered `stages`. `ProcessingStage`: `key`, `attempt` (starting at 1), `status: pending | running | done | error`, nullable UTC start/end, nullable nonnegative `duration_ms`, nullable safe `error_code`.
- Planned stages: upload `[upload]`; transcribe `[stt, normalization, pii_masking]`; generate `[llm_extraction, output_validation]`. Retry attempts append actual attempted stage records, not invented durations. Pending stages retain null timestamps/durations.
- Freshness is server-enforced using current/source transcript revision, not only lifecycle status. Legacy documents with no associated transcript keep a null source revision and remain exportable if approved; no invented transcript is created.


## Execution environment
No Git repository: no commits/worktrees. Use apply_patch. Do not change .env, user database, recordings or running services. Test only disposable data. No subagents from workers. Read TDD skill, use red-green tests. Escalated pytest may be needed for TestClient; use .venv/bin/python -m pytest, Node22 PATH for npm. Main agent owns progress ledger and reviews.

