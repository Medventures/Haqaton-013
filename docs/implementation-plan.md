# AI Medical Scribe Implementation Plan

> For agentic workers: implement assigned independent tasks with tests; root coordinates integration and review. User explicitly requested workers and implementation in this directory.

**Goal:** Deliver the MVP described in `тз.txt`, with an operational doctor workspace and replaceable local STT, PII, LLM and MIS providers.

**Architecture:** React/Vite frontend at project root, FastAPI modular monolith in `backend/app`, PostgreSQL in Compose and SQLite for local demo/tests. Local audio storage and lazy Whisper loading. Original compiled assets remain available; preserve original HTML in `legacy/` before replacing the entry point.

**Tech Stack:** React, TypeScript, Vite, Tailwind, shadcn-style Radix primitives, React Hook Form, Zod, TanStack Query; Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic; faster-whisper; OpenAI Structured Outputs; Docker Compose, Nginx.

**Spec:** `тз.txt` and six DOCX forms added by the user under `templates/`. The real MIS contract is unavailable; use an explicitly marked mock MIS adapter. No real patient data is used in verification.

## Global constraints

- Extract only explicitly spoken medical information. AI output always requires doctor review and approval.
- Only masked transcript reaches the external LLM. No mapping, raw audio, patient ID, raw transcript or logs of clinical payloads in outbound requests.
- JWT authentication, doctor/admin roles, per-consultation ownership, finite upload size and MIME/header validation.
- Demo is explicit (`APP_MODE=demo`), has synthetic fixture data and no external calls. Live mode never falls back silently to demo. Whisper always transcribes real uploaded audio; demo fixture is a separate explicit endpoint.
- Production secrets via environment or mounted secret files; refuse unsafe production settings. TLS via provided Nginx configuration and mounted certificates.
- No usable git repository exists; work in assigned disjoint paths, do not modify `.git`, `.agents` or `.codex`.
- No diagnoses invented by deterministic demo extraction; use a known synthetic fixture only, reject unsupported free text in demo LLM.

## Shared interfaces

Root owns `backend/app/schemas.py`; all workers import its Pydantic models. Backend owns settings and routes. AI worker owns `backend/app/providers/` and `backend/app/pii.py`, `backend/app/normalization.py`.

Provider signatures:

```python
PIIMaskingService().mask(transcript: str) -> MaskedTranscript
normalize_transcript(text: str) -> str
WhisperSTTProvider(model="small", device="cpu", compute_type="int8").transcribe(audio_path: str) -> Transcript
OpenAIProvider(api_key: str, model: str).extract_consultation(transcript: str) -> ConsultationData
DemoLLMProvider().extract_consultation(transcript: str) -> ConsultationData
MockMISProvider().send_consultation(consultation: ConsultationData, *, consultation_id: str, patient_id: str) -> MISResult
LocalStorage(root: Path).save(key: str, data: bytes) -> str
LocalStorage(root: Path).get(key: str) -> Path
LocalStorage(root: Path).delete(key: str) -> None
```

AI worker exports `DEMO_TRANSCRIPT: Transcript` in `app.providers.demo`, and protocols in `app.providers.base`. Provider errors are safe generic errors; no clinical text or credentials in their message. MaskedTranscript has text and entities(type,placeholder) only, no mapping.

All consultation states are UPPERCASE. All dates ISO UTC. API `/api/v1`:

- `GET /health` -> `{status:"ok", mode:"demo"|"live", stt_model, llm_model, mis_provider:"mock"}` (public).
- `POST /auth/login` JSON `{username,password}` -> `{access_token,token_type:"bearer",user:{id,username,role,display_name}}`. Demo credentials `doctor` / `demo-doctor`; only allowed in demo. `GET /auth/me` -> same user object.
- `GET /consultations` -> array of summaries; `POST /consultations` `{external_patient_id}` -> summary.
- Summary `{id,external_patient_id,status,created_at,updated_at,approved_at,error_message}`.
- `GET /consultations/{id}` -> summary.
- `POST /consultations/{id}/recording` -> summary, allows CREATED -> RECORDING.
- `POST /consultations/{id}/audio` multipart field `file` -> summary. Max 50 MiB, webm/wav/mp3/m4a. Accept valid recorder MIME `audio/webm;codecs=opus`. Upload persists audio; transcription separate.
- `POST /consultations/{id}/transcribe` -> transcript response after awaited local transcription (UI uses pending state).
- `POST /consultations/{id}/demo` -> transcript response; demo-only synthetic transcript fixture, sets TRANSCRIBED.
- `GET /consultations/{id}/transcript` -> `{raw_text,normalized_text,masked_text,language,duration_seconds,stt_model,segments:[{start,end,text,speaker:null|string}],pii_entities:[{type,placeholder}]}`.
- `POST /consultations/{id}/generate` -> document; TRANSCRIBED -> PROCESSING -> AI_GENERATED. Regenerate allowed only before approval, but must not destroy reviewed work without clear request. At most one retry on invalid LLM output.
- `GET /consultations/{id}/document` -> `{id,consultation_id,ai_generated_data,doctor_approved_data:null|ConsultationData,data:ConsultationData,llm_provider,llm_model,updated_at,version:int}`.
- `PATCH /consultations/{id}/document` `{data:ConsultationData,version:int}` -> document, persists edits and REVIEWED status, optimistic version conflict -> 409. All schema fields editable. Doctor-approved data stores reviewed working copy and freezes on approval.
- `POST /consultations/{id}/approve` `{version:int}` -> summary. Allow REVIEWED only. Approved/sent documents immutable; missing review -> 409.
- `POST /consultations/{id}/send-to-mis` -> `{success,document_id,provider:"mock"}`. APPROVED only; repeat SENT_TO_MIS returns existing export without duplicate side effect.
- `GET /consultations/{id}/audit` -> array `{id,field,ai_value,doctor_value,changed,created_at}` for edit history.
- Errors FastAPI `{detail:string|validation_errors}` with safe localized explanations; never return raw upstream errors.

Status lifecycle: CREATED -> RECORDING -> PROCESSING -> TRANSCRIBED -> PROCESSING -> AI_GENERATED -> REVIEWED -> APPROVED -> SENT_TO_MIS. FAILED permits safe retry based on presence of audio/transcript. Deny invalid transitions and simultaneous mutations. Recording can be omitted for file upload.

Settings names: APP_MODE (demo default), DATABASE_URL (sqlite:///./storage/medhub.db default; Compose PostgreSQL), JWT_SECRET, DOCTOR_USERNAME, DOCTOR_PASSWORD_HASH, OPENAI_API_KEY, OPENAI_MODEL (gpt-4.1-mini default), WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, AUDIO_STORAGE_DIR, AUDIO_RETENTION_DAYS (7), CORS_ORIGINS (JSON list), MAX_UPLOAD_MB (50).

## Review focus

1. Unauthenticated/other doctor's access must fail; role and ownership tests in backend.
2. Unreviewed or stale drafts must never be approved/exported; state/version integration tests.
3. Synthetic identifiers (IIN, names, phone, email, DOB, address, document) must disappear before LLM; PII and provider request tests.
4. Invalid/oversized audio must fail before STT; retention must remove only expired stored audio, not arbitrary files.
5. Refresh, API errors, edits and async recording completion must preserve selected consultation and pending edits; browser interaction smoke test.

## Task 1 — Backend and persistence (worker backend)

Own `backend/` except root schemas and AI worker paths above; includes pyproject.toml, tests/test_api.py, config, auth, models, routes, service, db, Alembic migration, Dockerfile.

- [ ] Write and run failing API behavior tests (auth/ownership, full demo workflow, invalid transitions, stale version, duplicate export, upload validation, persisted audit).
- [ ] Implement SQLAlchemy six domain tables plus users if useful, migrations portable SQLite/PostgreSQL with JSONB variant. JWT/password hashing and safe live configuration validation.
- [ ] Integrate provider interfaces above; configure lazy dependencies, PII before LLM, immutable AI snapshot, safe errors, retained audio expiry cleanup on periodic lifespan task/CLI, recover interrupted PROCESSING on single-instance startup.
- [ ] Run backend pytest; report commands/results and limitations to `docs/reports/backend.md`.

## Task 2 — AI, privacy and storage providers (worker ai)

Own `backend/app/providers/`, `backend/app/pii.py`, `backend/app/normalization.py`, `backend/tests/test_providers.py`, `backend/tests/test_pii.py`. Do not edit schemas/config/dependencies; request extra deps from root/backend.

- [ ] Test PII categories, preservation of medication/dose/measurements, malformed/extra LLM fields, retry limit, masked-only outbound request, no invented demo data.
- [ ] Implement replaceable protocols, Whisper CPU default with `asyncio.to_thread` and lazy model load, safe normalization, Kazakhstan-aware conservative PII masking, OpenAI Responses structured parsing (`store=False`, SDK retries disabled), MockMIS and traversal-safe local storage.
- [ ] Expose synthetic demo transcript and strictly bounded demo extractor. Tests never require model downloads or external API keys.
- [ ] Run scoped pytest and report to `docs/reports/ai.md`.

## Task 3 — Doctor workspace (worker frontend)

Own root package/config/index.html, `src/`, `public/`, `legacy/index.html`; no backend/docs/deploy edits except `docs/reports/frontend.md`.

- [ ] Build React TS Vite app using given stack. Preserve original root HTML as legacy/index.html before replacing. Source map can inform existing design, but user permits replacement.
- [ ] Polished Russian clinical workspace: login, consultation sidebar/history, external patient ID, recording/upload panel, transcript and editable consultation side by side, badges, lifecycle stepper, save/review/approve/export, audit display, responsive and accessible states. Restrained teal/navy/ivory palette, high-quality typography and real interactive controls.
- [ ] Implement MediaRecorder states, permissions, cleanup and stop-before-upload; API client with Bearer JWT and safe errors, TanStack Query, RHF/Zod editable nested schema. Token kept session-only/in memory; no PII in browser persistent storage. Explicit demo banner and sample button.
- [ ] Typecheck/build and meaningful form tests; report to `docs/reports/frontend.md`.

## Task 4 — Integration, deployment and verification (root)

Own shared schemas, `compose.yaml`, `deploy/`, `.env.example`, `.gitignore`, README, docs, integration smoke scripts.

- [ ] Define shared schema and plan before workers implement.
- [ ] Compose PostgreSQL/API/Nginx, health checks, named volumes, optional TLS override, non-root backend and practical secret settings.
- [ ] Install dependencies, run all tests/build, migrate test database and run browser/API end-to-end with synthetic data.
- [ ] Review worker output and resolve integration failures, then independent review and covering verification.
- [ ] Document exact start commands, credentials, real/development mode, PII limitations, unavailable real UMC form/API, verification evidence.

## Added requirement — user-provided output forms

User supplied six DOCX templates during implementation. Preserve originals unchanged. Add a template catalog with stable IDs (`therapist`, `therapist_initial`, `cardiologist`, `pediatrician`, `proctologist`, `surgeon`), select at consultation creation (default `therapist` pending optional preference), persist selected template via Alembic migration, and allow approved-document DOCX download using the selected original file as the layout source. Do not invent normal findings from alternatives printed on forms.

Root owns shared schema additions. `ConsultationData.template_fields` is a list of `TemplateFieldValue(key: str, value: str | None)` for specialty details absent from core schema. Template catalog includes ALL meaningful clinical paragraphs/fields from each provided document, with stable keys, label, original prompt, section and paragraph mapping. General clinical fields remain editable and map to common form fields; additional specialty entries are editable separately. Missing information stays null/«Не указано», never automatically chosen «норма/нет».

Template worker owns `backend/app/forms/` and `backend/tests/test_forms.py`: catalog, strict selected-template business validation, filling original DOCX, mapping core data to template slots, safe filenames. Backend worker owns endpoint/model/migration integration: `GET /api/v1/templates` returns `[{id,name,fields:[{key,label,prompt,section}]}]`; create accepts `template_id`, summary includes it; generation passes selected field catalog to provider; PATCH rejects unknown or duplicated field keys; `GET /api/v1/consultations/{id}/document.docx` returns approved data only (APPROVED/SENT_TO_MIS), proper DOCX MIME and safe Content-Disposition. Template path must come from catalog, never client filesystem path.

Provider interface adds optional keyword `template_fields: list[dict] | None = None` to `extract_consultation`; all implementations support it. OpenAI instructions enumerate selected specialty keys and prompts as form metadata, explicitly prohibiting default assertions, while only masked clinical transcript is transmitted. Demo returns common fixture data and empty specialty fields. Root integrates providers and shared schemas. Frontend worker adds template selection, field editor and download controls; unknown clinical details remain empty. Tests cover catalog completeness for all six files, empty values never imply normal findings, special characters in generated XML, form-specific fields retained after review/download, and export approval guard.

## Added requirement — user-provided ICD-10 reference

User supplied `seed/ref_disability_diagnoses_202609301227.csv` with code and Russian/Kazakh names. Root owns `backend/app/diagnoses.py` and `backend/tests/test_diagnoses.py`: load immutable CSV catalog using stdlib, configurable `DIAGNOSES_CSV`, cached validated codes, search by code/RU/KZ names with bounded results, no inference. Interface `search_diagnoses(query: str, limit: int = 20) -> dict(items=[{code,name_ru,name_kz}], total=int)` and `get_diagnosis(code: str) -> dict | None`.

Shared `ConsultationData.diagnosis_code: str | None = None` stores doctor's selected catalog code. LLM provider must leave this null; physicians explicitly select it, separately from free-text diagnosis. Backend adds authenticated `GET /api/v1/diagnoses?q=...&limit=20` with q<=100 and limit<=50; validates selected code on PATCH and includes code in immutable approved snapshot/audit/MIS. Frontend searchable picker next to diagnosis, RU/KZ label results, clear selection action, preserve separate diagnosis text. Forms render code alongside confirmed diagnosis in DOCX. Root mounts seed read-only in Compose and documents provenance. CSV is a provided reference, not automatically assumed to be an updated complete official ICD release.
