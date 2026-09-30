# Task 3 report: independent PDF and shared form projection

## Delivered

- Added `backend/app/forms/projection.py` with frozen `DocumentField` and `DocumentSection` records, shared clinical value formatting, text sanitization, and `project_sections(template_id, data)`. It projects every selected form slot plus populated core values without a source slot, including all medication properties, five vital signs, prescribed medication, notes and physician-selected ICD code.
- Kept the original DOCX source package and paragraph layout. `render_docx` now calls the shared formatting/sanitization functions; its public signature and unsigned signature wording are unchanged.
- Added `backend/app/forms/pdf.py` and public `render_pdf` with the same metadata arguments as DOCX. It renders directly from `ConsultationData` and the source-backed catalog through ReportLab; no DOCX conversion, LibreOffice process or external request. Paragraph markup is escaped, unsupported XML controls are replaced, long content splits across A4 pages, and all pages have a header/footer. The signature explicitly says `Подпись врача: не проставлена`.
- Added local DejaVu Sans regular/bold fonts and the distribution license to `backend/app/forms/assets/`, with wheel package data. Runtime font loading uses package resources, not host font paths.
- Added `backend/tests/test_pdf.py` and a DOCX/projection compatibility test in `backend/tests/test_forms.py`.

## RED/GREEN evidence

- RED: `.venv/bin/python -m pytest backend/tests/test_pdf.py backend/tests/test_forms.py -q` failed at collection: `ImportError: cannot import name 'render_pdf' from 'app.forms'` and `ModuleNotFoundError: No module named 'app.forms.projection'`. This was after the new tests were written and before product implementation.
- GREEN: the same focused command finished `51 passed in 1.21s`.
- Full backend check: `.venv/bin/python -m pytest backend/tests -q` finished `8 failed, 134 passed, 1 warning in 10.38s`. The eight failures are the same known Task 2/Task 4 provider API integration cases: `test_api.py::{test_doctor_selected_diagnosis_code_is_validated_audited_and_approved,test_template_fields_allow_selected_keys_and_reject_unknown_or_duplicates,test_docx_requires_approval_and_uses_frozen_data,test_docx_uses_approval_actor_snapshot_after_profile_rename,test_full_demo_review_approval_export_and_audit,test_restart_releases_unfinished_mock_export,test_invalid_state_transition_and_regeneration_protects_review}` and `test_runtime_llm.py::test_demo_login_and_actual_document_provider_are_independent[auto-demo]`. This worker did not edit API/provider files. The warning is Starlette's `httpx` TestClient deprecation.

## Dependency and packaging check

- Selected ReportLab `>=5.0.1,<6` as a runtime dependency and pypdf `>=6.19,<7` as a PDF-text extraction test dependency. Resolved versions: ReportLab `5.0.1`, pypdf `6.19.0`, setuptools `84.0.0`, build `1.6.1`. Selection was checked against the [ReportLab TrueType/Unicode guide](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/), [Platypus guide](https://docs.reportlab.com/reportlab/userguide/ch5_platypus/), [ReportLab release](https://pypi.org/project/reportlab/), [pypdf extraction guide](https://pypdf.readthedocs.io/en/stable/user/extract-text.html), and [pypdf release](https://pypi.org/project/pypdf/).
- `.venv/bin/python -m build --wheel --no-isolation backend --outdir /tmp/medhub-p0-task3-dist` succeeded. The wheel was installed with `pip --no-deps --target /tmp/medhub-p0-task3-installed`. Package resource reads from the installed copy returned `DejaVuSans.ttf` 759720 bytes, `DejaVuSans-Bold.ttf` 708920 bytes, and `LICENSE-DejaVu.txt` 3859 bytes. `pdffonts` reported both DejaVu faces embedded and Unicode mapped in a rendered PDF.

## Visual and text review

- Synthetic PDFs for all six forms are at `/tmp/medhub-p0-task3-visual/{therapist,therapist_initial,cardiologist,pediatrician,proctologist,surgeon}.pdf`; the long sample is `/tmp/medhub-p0-task3-visual/long.pdf` (4 A4 pages). Corresponding `*-first.png` previews and `long-last.png` were generated with `pdftoppm` at 900 px and visually inspected. Titles, sections, metadata, page furniture and Cyrillic/Kazakh glyphs were legible; the last long page retained its final marker and unsigned signature. The source DOCX appearance was not used as a pixel template, per the approved design.
- pypdf extraction tests checked all six forms for every populated core, medication property, vital, specialty entry and ICD value. The long case checked Kazakh `Ә Ғ Қ Ң Ө Ұ Ү Һ І`, literal `<>&`, control replacement, pagination, footer on every page, approval timestamp without microseconds, and final text without truncation. Blank forms showed `Не указано` and no source alternative normal findings.

## Handoff and scope

- Task 5 may call `render_pdf(template_id, approved_data, patient_id=..., consultation_id=..., doctor_name=..., approved_at=...)`; its async handler should offload the CPU rendering. It must use the frozen approved snapshot. The selected form catalog still reads the bundled source DOCX files as specified in the design.
- No API, database, `.env`, live process, user record or deployment file was edited. No Git operation was run. Build output generated `backend/build/` and `backend/medhub_backend.egg-info/`; the distributable wheel and synthetic samples are in `/tmp`.
- Ruling: The execution skill's Git worktree, commit and review-package steps conflict with the plan's explicit no-Git constraint, so this task used the existing workspace, recorded RED/GREEN evidence here, and did not run those steps.
