# SDD ledger — plan: docs/superpowers/plans/2026-09-30-medhub-p0.md

User approved design and worker execution. Started 2026-09-30.
Workspace helper failed: no Git repository. Approved plan explicitly forbids initializing Git.

Ruling: Use in-place, sequential worker implementation with source snapshots/diff packages and retain this ledger — approved no-Git plan and protected configuration preclude worktrees/commits — cost if wrong: no Git rollback; backups/diffs provide recovery instead.
Ruling: Keep implementation workers sequential, including independent PDF task — SDD explicitly prohibits parallel implementers — cost if wrong: additional wall-clock time, no product behavior change.

## Preflight task scan

| Task | Internal tests/files/interfaces check |
| --- | --- |
| 1 | Additive schemas/migration; legacy null source revision deliberately supported. |
| 2 | Canonical provider return breaks API until Task 4; component gate only explicitly recorded. |
| 3 | Independent PDF projection/fonts; packaging included; no API ownership. |
| 4 | Source revision and expected revision gates align; runtime provider doubles adapted here. |
| 5 | Callback timing added to transcripts helper; independent sessions must avoid write-lock overlap. |
| 6 | Typed APIs/panels not yet used by App; test fixtures may need new metadata. |
| 7 | App/editor cache gating, evidence and audio lifecycle align with contracts. |
| 8 | Worker/canvas owns copy of bytes; Blob retained for download; CSP explicit. |
| 9 | Synthetic acceptance precedes user DB backup/migration; main owns actual rollout. |

## Shared-file/interface scan
| Tasks | Producer → consumer / shared file | Finding |
| --- | --- | --- |
| 1/2 | Pydantic stored/canonical/evidence models → grounding/providers | Names match. |
| 1/4 | Revision/document models → snapshots/CAS | source null legacy exception retained. |
| 1/5 | ProcessingRunRow → tracker/summary | JSON reassignment required. |
| 1/6 | Response models → TypeScript | Nullable source revision explicit. |
| 2/4 | Canonical helpers/provider envelope → generation/edit | Main adaptations owned by 4; no deployment between. |
| 2/5 | Stage callback → persisted tracker | Events key/state/attempt match. |
| 2/6 | EvidenceLink/source masked text → UI types/privacy | Only server timestamps trusted. |
| 2/7 | AI path semantics → evidence display | Array changed => detached original evidence. |
| 3/5 | render_pdf approved data → protected route | Metadata mirrors DOCX. |
| 3/8 | PDF bytes → PDF.js | Independent of exact DOCX layout. |
| 4/5 | main.py/service.py/transcripts.py/test_api.py | Sequential; short transaction discipline mandatory. |
| 4/6 | PATCH/transcript/document response → api/types | Body expected_revision and changes fixed. |
| 4/7 | Freshness 409 → cache cancellation/dirty guard | No stale editor rendering after edit. |
| 5/6 | Summary runs and binary endpoints → typed clients | Latest per-operation run; no raw run payload. |
| 5/7 | Audio availability/server seek and status → workspace/player | Missing file race must fall back safely. |
| 5/8 | Protected PDF → preview | Same authenticated fetched bytes. |
| 6/7 | API/types/panels → App/editor | Shared required props/types maintained. |
| 6/8 | api.pdf Blob/cancellation → preview | Abort behavior defined. |
| 7/8 | App/styles | Sequential writes; dirty guards preserved. |
| 1–8/9 | All contracts → acceptance | Synthetic only; deploy after final review. |

## Tasks
Source snapshot directories moved (not deleted) to `/tmp/medhub-p0-snapshots.BPZlzl/`: baseline, task-1-fix-base, task-2-fix-base, task-4-base, task-6-base, task-8-base, task-9-base. Vitest's discovery included archived test copies inside .superpowers; keeping code snapshots outside project removes false/duplicate tests. Review/report artifacts remain in this workspace; existing diff packages unaffected. All future source snapshot comparisons use the /tmp path.
Persistent compressed pre-change source archive retained at `.superpowers/sdd/2026-09-30-medhub-p0/source-baseline.tar.gz` (no .env/storage/user recordings); archive avoids Vitest discovery and is not deleted with /tmp cleanup.
Ruling: User explicitly requested parallel workers mid-execution; supersedes sequential-worker skill restriction — run up to 3 disjoint workers, preserving review gates and file ownership — cost if wrong: integration rework, reduced by stable contracts and staged shared-file edits.
Parallel schedule: Task4 finishes backend revisions; Task6 starts types/API/panels; Task8 starts standalone PDF preview + dependency/CSP work. Task8 must NOT edit App.tsx/styles.css until Task7 releases ownership; Task7 will own initial preview wiring/style integration. Main controls shared-file handoffs. Final integration checks remain mandatory.
Ruling: Runtime refuses new/reloaded reviewer threads at the current thread cap even with a completed worker; reuse an existing worker for independent backup implementation while retaining separate-review ownership — keeps 3 workers useful without letting anyone review their own code — cost if wrong: more context carried between tasks, mitigated by explicit briefs/diffs.
Ruling: Task 1 also updates only the hardcoded Alembic-head assertion in test_api.py — additive migration necessarily changes head and otherwise leaves a known failing baseline test — cost if wrong: possible test expectation drift; independent review checks actual head.
Baseline: 92 backend tests passed (9.14s), existing StarletteDeprecationWarning; 9 frontend tests passed (2.59s). Source snapshot at baseline/ excludes .env, storage and medical source files. Task 1 implementer: /root/p0_persistence.
Disposable PostgreSQL16 running via Unix socket only: postgresql+psycopg://mephirious@/postgres?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432 ; controller must stop cluster `/tmp/medhub-p0-postgres.BJdoUn/data` after verification. Docker unavailable. No production DB changed.

- [x] Task 1: persistence/contracts
  Implemented by /root/p0_persistence; report task-1-report.md; review package task-1-review-final.md; reviewer /root/p0_review_1 running. Fresh backend 97 passed/1 existing warning, focused11; PostgreSQL migration round trip1 passed. Safe-code mismatch found by controller and fixed with red/green test before review.
  Review1: Important pending stage accepts non-null timing (schemas.py). Fix round1 dispatched. Cross-task warning resolved: Task4 explicitly owns complete-current-text/known-ID validation. Minor deferred: baseline Starlette deprecation warning.
Task 1: fix round 1/5 (1 addressed, 0 open); focused schemas10 passed. Reviewer /root/p0_review_1 confirms no new breakage.
Task 1: complete (source diff packages retained, review clean; baseline warning deferred).
- [x] Task 2: masking/evidence
  Implementer /root/p0_grounding dispatched; task2 focused gate, integrated API contract follows in Task4. Full-suite failures at old provider call sites must be reported explicitly, not hidden.
  Implemented; task-2-report.md evidence: focused44 passed; full118 passed/8 expected old-call-site failures listed in report. Reviewer /root/p0_review_2 running with task-2-review.md. No live OpenAI call. Provider freezes canonical input; removes raw speaker metadata.
  Review2 Important: assert_canonical_source re-normalizes projected cross-boundary text and rejects valid builder output with residual spaces. Probe: 'ИИН 010203' / '500123 кашель три дня.'. Fix round1 to original implementer. API warning resolved as explicit Task4 dependency; baseline warning already deferred. test_pii.py unchanged accepted because detector regression exercises real mask path in grounding tests.
Task 2: fix round 1/5 (1 addressed, 0 open), focused46 passed. Reviewer confirms exact text detection without renormalization, no new breakage.
Task 2: complete (diff packages retained, review clean; Task4 API integration pending).
- [x] Task 3: PDF
  Implementer /root/p0_pdf dispatched with fonts/docs references. API integration failures from Task2 are not Task3's scope. No live-data verification.
  Implemented; report task-3-report.md; focused51 passed, full134 passed/8 known API failures. Fonts/license verified in installed wheel; synthetic all6 PDFs +4page visual check. Reviewer /root/p0_review_3 running on task-3-review.md. Resolved ReportLab5.0.1/pypdf6.19.0. Main viewed therapist preview.
Task 3: complete (review spec+quality approved). Cross-task checks resolved: Task5 owns approved snapshot/auth/CPU offload explicitly.
Task 3: minor (deferred): DOCX catalog/residual traversal at forms/__init__.py:410 remains separate from projection.py:94 despite shared formatting; current behavior correct, final review to triage drift risk.
- [x] Task 4: transcript workflow
  Implementer /root/p0_revisions (astra/high) dispatched. Pre-task snapshot at task-4-base/; handoff task-4-handoff.md. Full API contract integration and race tests required; no user DB migration yet.
  Dedicated disposable PostgreSQL DB medhub_p0_task4_20260930 created for race suite; URL same socket/port as references. Main owns cluster lifecycle, worker permitted test-local setup/cleanup only in dedicated DB.
  Task4 implementation report ready, full188 passed both DBs (1 baseline warning); review package task-4-review.md assembled. Fresh reviewer spawn/followup temporarily hit thread limit with 2 frontend workers running + completed Task4 seat; no review skipped. Task4 reviewer pending free slot.
  Independent Task4 reviewer running on reused /root/p0_panels seat (did not implement backend). Review package task-4-review.md.
Task 4: complete (independent spec+quality approved, no blocking findings). Existing TestClient warning recorded. Placeholders intentionally owned by Task5.
- [x] Task 5: processing/protected files
  Assigned to /root/p0_revisions after fixing independently discovered backup race; base snapshot task-5-base. Preserve Task4 guards, no live DB/process mutation.
  Task5 frozen/report ready: focused60 SQLite/PG passed; full219passed/2 concurrent Task9 missingharness errors, 1 baselinewarning. Exact task-5-review.md package ready; p0_panels independentreview nowrunning. Main/services/tracker/files ownership remains frozen untilreviewfix.
Task5 complete: independent p0_panels spec+quality approved; no blockingissues. Minor deferred: processing_response scans whole runhistory to selectlatest3 (service42–49); future queryoptimization. Root fresh wholebackend221passed1baselinewarning42.58s withSQLite+PG; Task9 missingmodulegapresolved.
- [x] Task 6: frontend contracts/panels
  Parallel implementer /root/p0_panels; task6-base snapshot. May adapt DocumentEditor.test.tsx fixture metadata only. No App/styles/manifest writes.
  Implemented: final frontend33 tests passed/build0; report task-6-report.md, package task-6-review-final.md. Independent reviewer /root/p0_revisions (did not implement frontend) running. Build warnings dependency comments/large chunk; no compile errors.
Task 6: complete (independent /root/p0_revisions spec+quality approved, no blocking findings).
Task 6: minor (carry to Task7): PrivacyPanel uses whitespace-pre-wrap utility absent from styles.css; add explicit whitespace preservation/wrapping during workspace styling. Dependency comment/large-chunk build warnings recorded for final review.
- [ ] Task 7: workspace/evidence/audio
  Parallel implementer /root/p0_panels dispatched with task-7-handoff; owns App/editor/styles/evidence/audio and preview wiring. Task8 component/deploy remain separately owned.
  Task7 frozen/reportready:57frontendtests/10files passed,Node22build0. task-7-review.md assembled. Independent review pending; actual375px/keyboardbrowseracceptance belongsTask9. No api.ts ownershipextension needed.
Task7 review byp0_revisions:3Important unsaveddraftversionreset, latePATCHAclearsBdirty, readonlytransition/approvalignoresunsavedtranscript. task-7-review-verdict.md details. Fixround1 sentoriginalp0_panels, snapshot task-7-fix-base. Deletedarrayoriginalevidence independentlyconfirmedreachable (noissue). Rootfrontend57passed7.32s plusNodePDFadvisory beforefix; testsneednewregressions.
- [ ] Task 8: PDF preview
  Parallel implementer /root/p0_preview; task8-base snapshot. Standalone PdfPreview + local CSS + package/deploy only. App wiring belongs to Task7; API shared contract implemented by Task6.
  Independent original-snapshot review by /root/p0_revisions: Important cleanup promise race and missing .mjs JavaScript MIME mapping in both Nginx configs. Cleanup regression fixed RED→GREEN focused8/full35/build0; MIME fix dispatched. Combined fix re-review pending. Original component/test reconstructed at task-8-fix-base outside project.
  MIME fix frozen: disposable Nginx reproduced octet-stream RED; both configs GREEN JavaScript worker + unchanged normal assets/API proxy/security headers. Combined task-8-fix-1-review.md sent to original reviewer, pending verdict.
Task8 fix round1 approved by /root/p0_revisions: cleanup and MIME findings both addressed, no new breakage. Standalone component review complete; Task7 wiring and Task9 actual bundled browser/CSP acceptance remain before task checkbox completion.
- [ ] Task 9: acceptance/rollout
  Independent backup-only subtask running on reused /root/p0_revisions seat due thread cap: scripts/backup_database.py + backend/tests/test_backup_database.py; report task-9-backup-report.md. No user backup/migration/restart authorized to worker; main owns rollout.
  Backup subtask implemented: focused8 passed, full173 passed/23 optional PG skips; task-9-backup-report.md and task-9-backup-review.md ready. Separate review pending; no real backup made.
  Independent /root/p0_preview review reproduced destination path-replacement race: reopening reserved pathname can overwrite another DB via symlink. Rollout blocked on fix and independent re-review; fix sent to original implementer /root/p0_revisions. User data unaffected (synthetic probe only).
Task9 backup: fix round1 approved by independent original reviewer. Private staging + atomic no-overwrite publication, no public-path cleanup, final published identity/mode verified; both original findings resolved, no new blocking issues. Root fresh focused11 passed0.37s. Report/diff retained; no user backup yet.
Task9 acceptance: /root/p0_preview owns synthetic browser harness/browser_smoke/README, disjoint from Tasks5/7. Controller Compose quiet checks passed; task-9-controller-checks.md. Main owns rollout only after integration/final review.
