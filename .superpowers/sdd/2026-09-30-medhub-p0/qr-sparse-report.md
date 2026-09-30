# Branded verification PDF and sparse export implementation

User authorized accelerated implementation and explicitly approved saving the shown Canva draft. No production database, `.env`, source DOCX, process, or frontend files changed by this worker.

## Canva completed

Transaction `8823069169612064864` committed successfully. Saved design `DAHWqaMc-Ds` verified as 12 pages with the exact approved title. Editable link: https://www.canva.com/d/Gm_gkOnVEltusYu . No further slide updates or sharing changes. Notes/provenance: `docs/presentation/`. Native PDF export is unavailable through connected tools; manual Canva PDF download is required (600×337 preview images are not a suitable submission PDF).

## Backend behavior

- Authenticated, owner-only approved PDF GET lazily stores one immutable PDF per document/version. DB unique constraint and SQLite/PostgreSQL atomic conflict handling return the winning exact bytes to concurrent callers. Existing approval/freshness guards are retained.
- Artifact stores a 192-bit cryptorandom opaque public ID, final-byte SHA256, issuance timestamp, and PDF BLOB/BYTEA. Public `GET /api/v1/verification/{public_id}` returns exactly `issuer`, `issued_at`, `status`, `sha256`; unknown IDs return 404. No clinical data, patient/doctor names, internal IDs, template, or download is exposed. Public query selects only timestamp and digest, never the PDF bytes or clinical JSON.
- QR includes only configured `PUBLIC_BASE_URL + /verify/{opaque_id}`, never request Host. Default `http://localhost:5173` is local-demo-only. Configuration accepts HTTPS origin or loopback HTTP, rejects credentials/query/fragment/path. The user has no public address yet; no hosting or tunnel was created.
- PDF header uses vector geometry/colors from the existing stethoscope favicon, MedHub text, and a QR section clearly labeled not EDS. Hash is computed after QR rendering; the QR stores ID/URL, avoiding self-reference.
- Shared projection omits actual empty/null/whitespace clinical values and empty sections. PDF and source-based DOCX retain explicit negatives, `0`, and even explicitly entered literal `Не указано`. Administrative metadata, approval date, doctor and unsigned-signature label remain. Source DOCX ZIP files are never written; output packages retain their original non-document members/styles.
- Migration0004 creates only the artifact table. Existing approved JSON remains unchanged. Legacy approved rows with no transcript remain exportable and are lazily issued on first authenticated PDF request. Previously downloaded PDFs are not retroactively verified or overwritten.

## Files

Production: `backend/app/forms/{projection.py,__init__.py,pdf.py}`, `backend/app/{models.py,config.py,main.py,export_artifacts.py}`, `backend/alembic/versions/0004_export_artifacts.py`.
Tests: new `backend/tests/test_export_verification.py`; updated `test_forms.py`, `test_pdf.py`, `test_migrations.py`, and migration-head assertion in `test_api.py`.
Recovery snapshot of pre-change production files/forms/migrations and export tests: `/tmp/medhub-export-feature-base-n0cKJO`.

## Verification evidence

- RED: export/verification/forms/PDF focused run — **25 failed, 39 passed, 2 skipped**, 5.71s. Failures included printed empty clinical rows, missing QR/verification, nonidentical concurrent PDF bytes, absent configuration.
- GREEN: same focused group — **64 passed, 2 skipped**, 5.46s.
- SQLite+dedicated disposable PostgreSQL feature/migration group — **21 passed**, 9.92s. Covers concurrent first issuance, repeated byte identity without rerender, approved-only auth, exact public keys/hash, configured-origin QR vs attacker Host, unsafe origins, legacy no-transcript issuance, source/negative-value preservation, and migration preservation.
- First full SQLite+PostgreSQL backend run — **241 passed, 1 failed**, 68.14s. Sole failure was existing API test expecting migration0003 instead of0004. Assertion updated; focused regression **1 passed**, 1.79s.
- Final integrated SQLite+PostgreSQL backend run — **250 passed, 1 warning in 75.66s**. Command: `MEDHUB_P0_REVISION_DATABASE_URL='postgresql+psycopg://mephirious@/medhub_p0_task4_20260930?host=/tmp/medhub-p0-postgres.BJdoUn&port=55432' .venv/bin/python -m pytest backend/tests -q --tb=short`. Exit status 0. This includes the frozen protocol module and its eight tests.
- One existing Starlette TestClient/httpx deprecation warning remains.
- Migration preservation in the focused group ran on SQLite; artifact/legacy/concurrency scenarios ran on both SQLite and PostgreSQL.
- Synthetic-only visual artifact: `/tmp/medhub-export-feature-base-n0cKJO/synthetic-branded.pdf` and `.png`. Inspected first page: correct MedHub stethoscope, readable RU labels, sparse content, explicit negative retained, QR and no-EDS wording. Layout sample uses a dummy verification URL, not a real issued consultation.

## Limits / remaining coordination

Public validity is MedHub registry/hash identity, not governmental signature or proof of clinical correctness. No revocation feature was requested. Immutable artifacts preserve their original QR origin; configure a durable public HTTPS origin before first issuance when external scanning is needed. Localhost cannot be scanned from another device. DB backups now contain generated PDFs as well as clinical data.

Protocol router is registered exactly once inside `create_app`, after `current_user` is defined: `app.include_router(create_protocol_router(current_user))`. The actual application auth regression verifies unauthenticated protocol search returns 401. Protocol implementation belongs to the protocol worker; this worker owns only the registration in main.py. Backend feature files are frozen after the final integrated GREEN run; rollout remains controller-owned.
