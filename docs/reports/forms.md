# Bundled clinical DOCX forms

Implemented a source-backed catalog and OOXML export for all six original files in `templates/`:

| ID | Original form |
| --- | --- |
| `therapist` | `Осмотр терапевта.docx` |
| `therapist_initial` | `Первичный осмотр врача терапевта.docx` |
| `cardiologist` | `Осмотр кардиолога (первичный).docx` |
| `pediatrician` | `Осмотр педиатра.docx` |
| `proctologist` | `Осмотр проктолога.docx` |
| `surgeon` | `Осмотр хирурга (первичный).docx` |

`app.forms` exports `list_templates`, `get_template`, `validate_template_fields`, and `render_docx`. Catalog entries include stable field keys, descriptive labels, original source prompts, sections, and paragraph indexes. Common clinical entries identify their `clinical_field` and are not accepted as duplicate specialty values. Selected-template validation rejects unknown and repeated specialty keys. Source paths are fixed by the six-ID whitelist and support `TEMPLATES_DIR` for the container's read-only mount.

The renderer rewrites clinical paragraphs in a copy of the original OOXML package, retaining paragraph-level layout and styles where possible. Every specialty slot has a manually reviewed neutral label; printed alternatives remain only in the catalog's source prompt and are replaced in the document with approved text or «Не указано». It includes patient and consultation identifiers, a readable UTC approval timestamp, doctor name, selected МКБ-10 code, all core clinical data, and all entered specialty values. The source templates are unchanged. Signatures are explicitly marked as not applied.

Verification: `.venv/bin/python -m pytest backend/tests -q` → **85 passed**, one Starlette/httpx deprecation warning. Tests cover all six ZIP/XML exports, blank-value safety, special XML characters, every specialty field, all common fields and five vital signs, diagnosis code, template-key validation, neutral labels, and readable UTC dates. All six DOCX files also converted to PDF in the root agent's LibreOffice check.

Limitations: The sources contain several long paragraphs combining many examination prompts; each such paragraph is exposed as one broad specialty field with the full original prompt. Filled paragraphs retain paragraph properties and the first run's style, but fine-grained run formatting inside the replaced text is flattened. Export is a clinical draft approved in this application, not a cryptographic signature or a certified external MIS form.
