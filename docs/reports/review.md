# Independent review — initial MVP pass

Reviewed actual files on 2026-09-30; no usable Git diff. Scope: `тз.txt`, implementation plan, backend/providers, deployment configuration and frontend source as it landed. Production files were not modified. This report precedes integration of the newly supplied specialty DOCX templates and the final browser verification.

## Verdict

The modular MVP implements the central consultation, transcription, masked extraction, editable review, approval and mock export workflow. Approval/ownership checks are enforced server-side, the AI snapshot and approved copy are distinct, and provider interfaces are replaceable. This pass found consequential privacy, credential migration and recovery/UI defects. Root accepted the findings and assigned corrections; do not treat the pre-fix snapshot as ready for real patient use. No unresolved Critical finding was established. Important findings below require their final regression checks.

## Important findings and disposition

1. **Ordinary spoken identifiers reached the external LLM boundary.** `backend/app/pii.py:17`, `backend/app/pii.py:27`, `backend/app/providers/llm.py:35`: a capturing fake OpenAI SDK received exactly `Меня зовут Иван Петров. Пациент иванов иван иванович. ИИН 010 203 500 123. Кашель три дня.` Regex redaction missed the common introduction, explicitly labeled lowercase name and spaced IIN. No external request was made. Root is adding rules and boundary regressions. General arbitrary-name recognition remains a documented heuristic limitation, distinct from these reproducible common cases.

2. **A custom demo account survived a switch to live with a different username.** `backend/app/auth.py:18`: direct isolated SQLAlchemy/bootstrap/authentication probe created demo user `demo-clinic`, then bootstrapped live user `clinic-doctor`; `authenticate(..., 'demo-clinic', 'demo-doctor')` still returned a doctor. The first correction only revoked literal username `doctor`. Backend has been asked to revoke credentials matching the public demo password regardless of username. Same-username replacement and default `doctor` replacement were present and checked in this pass.

3. **Interrupted mock export could become permanently unretryable.** `backend/app/main.py:414`: the endpoint commits a `MISExport(success=False)` reservation before invoking the provider, then rejects every retry when that reservation exists. Startup originally recovered `PROCESSING` consultations only. A process exit between reservation and success leaves an APPROVED consultation returning 409 indefinitely. Root routed mock-specific startup recovery to backend. This is static control-flow evidence; a crash/restart regression is still required. A future real MIS adapter needs its own idempotency/reconciliation policy.

4. **Creating a consultation bypassed edit/recording navigation guards.** Initial `src/App.tsx:92` called create and changed selection directly, while existing-consultation navigation checked dirty and recording state. Reproduce by editing a draft or recording, then creating a new consultation: pending edits may disappear and recorder context may remain associated with the preceding selection. Logout also lacked equivalent protection. Root assigned shared navigation guards and recorder lifecycle corrections to frontend.

5. **Failed generation and refreshed background processing were not recoverable in the UI.** Initial `src/App.tsx:77` had no summary polling; loading a consultation while its server status was PROCESSING could leave the page stuck after completion. Initial `canGenerate` excluded FAILED even though the backend permits retry with an existing transcript, and included REVIEWED although the backend correctly rejects regeneration of reviewed work. Root assigned status-aware polling and retry controls to frontend.

6. **File upload and microphone retry had mismatched state transitions.** Upload previously left a newly created consultation CREATED, but the frontend only offered transcription for RECORDING/FAILED. Starting a second microphone recording called `/recording`, which originally rejected existing RECORDING state. Backend now sets successful uploads to RECORDING and accepts repeated recording transitions from CREATED/RECORDING; the corrected source was inspected. Final UI checks remain with root.

## Already-correct protections inspected

- JWT decoding restricts HS256, routes reject unsupported roles, and ownership checks hide other doctors' consultations.
- Approval requires REVIEWED and current document version. Patches use conditional version/status writes; approved/sent documents cannot be edited or regenerated. Sequential duplicate exports return the prior stored result.
- The generation route passes stored masked text only; the OpenAI adapter masks again, sends no patient ID/mapping/audio, sets `store=False` and disables SDK retries. Invalid extraction receives at most one validation retry.
- Upload checks finite size, MIME and header before storage; storage rejects traversal and symlink keys and writes atomically.
- Retention now excludes PROCESSING consultations, deletes only expired registered audio, and leaves unrelated files alone. This is single-instance behavior; no distributed retention race guarantee was established.
- Demo extraction is explicitly synthetic and rejects arbitrary transcripts. Real audio goes to local Whisper rather than a fixture fallback.
- Deployment includes PostgreSQL, migrations, non-root backend, loopback-only default exposure, TLS override, secret-file support and restrictive response headers.

## Spec compliance and limits

Core stack and modular architecture match the specification. All supplied clinical schema fields have editor controls. Audit records compare edits with AI values. Diarization is explicitly optional and the segment model supports speaker labels. Medical normalization currently performs conservative whitespace cleanup rather than clinical spelling/number conversion. MockMIS is clearly marked and does not claim real UMC integration.

The initial schema was a provisional implementation of the example in `тз.txt`; six specialty DOCX templates arrived during this review and require separate schema/form/export assessment. This pass does not certify compatibility with those forms.

## Verification evidence and declined judgments

- Independently ran capturing-provider privacy probe and temporary-database bootstrap/authentication probes; no real patient data or outbound network calls.
- Root reported the existing backend suite passing (initially 28 tests, later 31), SQLite upgrade/downgrade/upgrade passing, and Compose configuration parsing. These checks were not redundantly rerun by the reviewer.
- An isolated TestClient probe stalled under the execution sandbox and was interrupted. Direct component probes supplied the concrete evidence above instead.
- Docker daemon was unavailable. Actual image builds, PostgreSQL runtime behavior, mounted secret permissions and TLS serving were not verified by this reviewer.
- No real Whisper model, live OpenAI response, medical extraction quality, privacy recall corpus or real MIS integration was externally tested. Prompt/schema constraints alone do not establish clinical correctness or full anonymization.
- Frontend was still changing. Root owns final browser checks, including recorder stop/upload, edits, refresh/polling, approval/export and responsive layout. This report is a handoff of the current pass, not the final release gate.

## Final scoped integration review — specialty forms and ICD reference

Re-read the completed backend, frontend state handling, form renderer, ICD catalog, provider changes, migration and Compose mounts. The six Important findings from the initial pass are addressed in the current source: common spoken PII patterns are masked, live bootstrap revokes the public demo password for every stored username, interrupted mock exports are recoverable, navigation protects unsaved/active recording work, processing summaries poll, generation retries are available, and upload/recording transitions agree with the UI. The original privacy probe now produces `Меня зовут [PERSON_1]. Пациент [PERSON_2]. ИИН [IIN_1]. Кашель три дня.`

Two additional Important findings were raised and corrected during this final pass:

- **Printed alternatives leaked into generated field labels.** The initial derived label for surgeon `p_014` yielded `Глотание нарушено: Не указано` on blank export and `Глотание нарушено: свободное` for an explicitly normal finding. Other labels included `тяжелое` and competing alternatives. The forms worker replaced automatic label extraction with a reviewed, explicit neutral label catalog for all specialties. An independent rendering probe after the correction returns `Глотание: Не указано` and `Глотание: свободное`; the other identified labels are neutral. Regression tests cover the contradictory-output example and labels. Original form prompts remain metadata for editing/extraction, not approved assertions.
- **Confirmed regeneration retained the old dirty form/version.** Updating the cached draft and clearing only parent dirty state did not reset DocumentEditor's dirty values. Frontend now passes a dedicated `regenerationRevision`; only successful intentional regeneration resets form values, version, error/saved flags and dirty state. Ordinary background updates continue to preserve unsaved edits. The source and dedicated regression were inspected.

No unresolved Critical or Important finding remains in the scoped source review after those corrections. This supports the implemented MVP workflow, subject to the runtime and clinical limitations below; it is not a clinical deployment certification.

### New integration protections verified

- Six template IDs are whitelisted and persisted by migration; DOCX uses only the approved snapshot and frozen approving physician name. Paths cannot be supplied by API clients. Specialty keys are validated against the selected template and duplicates/common-field substitutions are rejected.
- All core data and specialty values have explicit render paths or residual paragraphs. An independent comparison of empty exports against source paragraphs found only headings/instructions surviving unchanged, not source clinical assertions. Every provided original remains the layout source, and XML text is escaped with unsupported controls replaced.
- Physician-selected ICD codes are normalized, validated against the supplied CSV and remain separate from diagnosis text. OpenAI extraction explicitly clears codes; the route also rejects a code from another extraction provider. Review, approval, DOCX and MIS preserve the selected code. Search is authenticated and bounded.
- Compose mounts `templates/` and `seed/` read-only and points the application to those mounts. The CSV is a user-supplied reference; the reported RU/KZ mismatch at J20.9 is a source-data limitation, not an inference made by the application.

### Evidence and remaining limits

Root reported 82 backend tests passing before the last neutral-label regressions, successful frontend build/tests, and a browser workflow covering six-form selection, synthetic extraction, specialty editing, ICD selection, save/reload, approval, DOCX download and MockMIS. Root also converted all six generated DOCX files to PDF with LibreOffice. The reviewer did not repeat these complete suites; direct probes were limited to identified privacy and rendering concerns. Root owns recording/browser and final layout checks plus the last changed-test reruns.

Live Whisper/OpenAI, Docker/PostgreSQL/TLS runtime and real MIS remain unverified in this environment. The DOCX fields preserve the supplied forms at paragraph granularity; exact certified formatting and clinical suitability require the receiving institution's assessment. Regex PII recall remains limited for arbitrary names/recognition errors, and the supplied ICD descriptions are not independently certified. These limits must remain explicit in the handoff.
