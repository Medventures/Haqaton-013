# User-directed parallel execution

User explicitly requested parallel workers on 2026-09-30 to accelerate execution. This supersedes the sequential implementation restriction in SDD. At most three active workers plus main, with disjoint write ownership. Existing no-subagents-from-workers rule stays; controller dispatches reviews.

- Task4 backend revisions: owns its brief's backend/API files until report.
- Task6 frontend contracts: owns types.ts/api.ts, ProcessingPanel/PrivacyPanel and tests; may adapt DocumentEditor.test.tsx fixture metadata only to keep types compiling. Does not touch App, DocumentEditor production, PdfPreview, styles, package manifests or deployment.
- Task8 PDF preview: starts as standalone component + tests, dependency manifests/lockfile and both Nginx CSPs. DOES NOT touch App.tsx or styles.css while Task7 is pending/running. Use scoped component classes or local stylesheet PdfPreview.css. Consume api.pdf contract from context.md; task6 implements it concurrently. Main will arrange integration wiring via Task7 or a scoped followup after ownership handoff.
- Task7 starts after Task6 review; owns App/DocumentEditor/transcript/evidence/styles and preview button wiring once Task8 interface is available.
- Task5 starts after Task4 review; backend files only. Task9 backup/smoke tasks can follow free slots once required runtime exists.

Run focused tests while other workers edit; do not misreport failures caused by in-flight dependent contracts. Record exact test state; controller runs whole-stack tests after integration. Do not repair another worker's files. All user DB/process/.env changes remain reserved for controller's reviewed rollout.
