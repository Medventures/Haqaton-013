## Task 3: Render complete independent PDFs

**Files:** Create `backend/app/forms/projection.py`, `backend/app/forms/pdf.py`, `backend/app/forms/assets/DejaVuSans.ttf`, `backend/app/forms/assets/DejaVuSans-Bold.ttf`, `backend/app/forms/assets/LICENSE-DejaVu.txt`, `backend/tests/test_pdf.py`; modify `backend/app/forms/__init__.py`, `backend/pyproject.toml`, `backend/tests/test_forms.py`.

**Interfaces:** `project_sections(template_id: str, data: ConsultationData) -> list[DocumentSection]`, with immutable `DocumentSection(title: str, fields: list[DocumentField])` and `DocumentField(key: str, label: str, value: str)`. `render_pdf(template_id, data, *, patient_id, consultation_id, doctor_name, approved_at) -> bytes` matches DOCX metadata arguments. Existing `render_docx` public signature stays unchanged.

- [ ] Add `test_all_six_forms_preserve_every_populated_value` for projection and extracted PDF text: sentinel values in every core field, medication property, vital, specialty field and ICD code must appear. Include residual fields not mapped into source paragraphs, and assert empty values use `Не указано` without invented findings.
- [ ] Add `test_pdf_unicode_markup_and_pagination`: RU/KZ `Ә Ғ Қ Ң Ө Ұ Ү Һ І`, `<>&`, unsupported control characters and multi-page text yield a readable PDF, repeated page furniture and explicitly unsigned signature. Assert no unescaped markup crash, no truncation and correct approval metadata.

  Core assertions: `assert pdf.startswith(b"%PDF-")`; `assert len(reader.pages) > 1`; `assert all(value in extracted_text for value in populated_sentinels)`; `assert "Ә Ғ Қ Ң Ө Ұ Ү Һ І" in extracted_text`.
- [ ] Run `.venv/bin/python -m pytest backend/tests/test_pdf.py backend/tests/test_forms.py -q`; confirm failure for the missing renderer/projection.
- [ ] Extract shared value formatting/projection without replacing DOCX paragraph layout. Add ReportLab runtime and a PDF-text extraction test dependency in `backend/pyproject.toml`; select supported releases from official documentation and record resolved versions. Bundle the local licensed regular/bold fonts and license; configure wheel package data so production does not depend on host font paths.
- [ ] Implement the ReportLab renderer with escaped paragraphs, wrapping tables/flowables that can span pages, header/footer and unsigned signature. Offload CPU rendering from async handlers when integrating. No LibreOffice subprocess or external request.
- [ ] Run both test modules and build/install the backend package into a disposable location; assert font resources exist in the built artifact. Review visual samples from synthetic PDFs for all six forms, including a long multipage case.
- [ ] Record visual/test results and hand off `render_pdf`; do not edit API or deployment files owned by later tasks.


Read shared constraints/interfaces in .superpowers/sdd/2026-09-30-medhub-p0/context.md.

