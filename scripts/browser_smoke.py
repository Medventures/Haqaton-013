"""Exercise the approved P0 workflow in a disposable same-origin browser.

Run through scripts/p0_smoke.py, which supplies synthetic providers, a private
SQLite database, built frontend assets, and the production Nginx CSP.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse
import zipfile

from playwright.sync_api import expect, sync_playwright

from p0_smoke import CORRECTED_SECOND, synthetic_wav


def canvas_fingerprint(page) -> str:
    page.wait_for_function("""() => {
      const canvas = document.querySelector('.pdf-preview-pages canvas');
      return canvas && canvas.width > 0 && canvas.height > 0 && !document.querySelector('.pdf-preview-painting');
    }""")
    ratio = page.locator(".pdf-preview-pages canvas").evaluate("""canvas => {
      const rect = canvas.getBoundingClientRect();
      return { rendered: rect.width / rect.height, page: canvas.width / canvas.height };
    }""")
    assert abs(ratio["rendered"] - ratio["page"]) < 0.02, f"PDF page aspect ratio changed: {ratio}"
    image = page.locator(".pdf-preview-pages canvas").evaluate("canvas => canvas.toDataURL()")
    return hashlib.sha256(image.encode()).hexdigest()


def main() -> None:
    output = Path(os.environ["MEDHUB_QA_OUTPUT"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    base_url = os.environ["MEDHUB_BASE_URL"]
    origin = urlparse(base_url)
    username = os.getenv("MEDHUB_USERNAME", "doctor")
    password = os.getenv("MEDHUB_PASSWORD", "demo-doctor")
    patient = f"SYNTHETIC-BROWSER-{int(time.time())}"
    checks: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=os.getenv("MEDHUB_BROWSER_EXECUTABLE") or None)
        context = browser.new_context(viewport={"width": 1600, "height": 900}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors: list[str] = []
        external_requests: list[str] = []
        worker_responses: list[tuple[int, str]] = []
        page.add_init_script("""(() => {
          window.__medhubPdfHashes = [];
          const originalFetch = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const response = await originalFetch(...args);
            const url = String(args[0] instanceof Request ? args[0].url : args[0]);
            if (url.endsWith('/document.pdf') && response.ok) {
              const buffer = await response.clone().arrayBuffer();
              const digest = await crypto.subtle.digest('SHA-256', buffer);
              window.__medhubPdfHashes.push({
                size: buffer.byteLength,
                hash: Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
              });
            }
            return response;
          };
        })();""")
        def inspect_request(request):
            parsed = urlparse(request.url)
            if parsed.scheme in ("http", "https") and (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                external_requests.append(request.url)
            if any("token" in key.lower() or "secret" in key.lower() for key in parse_qs(parsed.query)):
                errors.append("Credential appeared in a request URL")

        def inspect_response(response):
            parsed = urlparse(response.url)
            if parsed.path.endswith(".mjs"):
                worker_responses.append((response.status, response.headers.get("content-type", "")))

        page.on("request", inspect_request)
        page.on("response", inspect_response)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())

        page.goto(base_url)
        page.screenshot(path=str(output / "synthetic-login.png"))
        page.get_by_label("Логин", exact=True).fill(username)
        page.get_by_label("Пароль", exact=True).fill(password)
        page.get_by_role("button", name="Войти", exact=True).click()
        page.get_by_role("button", name="Новая консультация", exact=True).first.click()
        page.get_by_label("ID пациента", exact=True).fill(patient)
        expect(page.get_by_role("combobox", name="Бланк консультации", exact=True).locator("option")).to_have_count(6)
        page.get_by_role("button", name="Создать", exact=True).click()
        expect(page.get_by_role("dialog", name="Новая консультация")).to_have_count(0)
        expect(page.get_by_role("button", name=re.compile(patient))).to_be_visible()
        page.screenshot(path=str(output / "synthetic-workspace.png"))

        page.locator('input[type="file"]').set_input_files({"name": "synthetic.wav", "mimeType": "audio/wav", "buffer": synthetic_wav()})
        transcribe = page.get_by_role("button", name="Транскрибировать аудио", exact=True)
        expect(transcribe).to_be_enabled()
        transcribe.click()
        expect(page.get_by_role("heading", name="Ход обработки")).to_be_visible()
        page.get_by_role("heading", name="Ход обработки").scroll_into_view_if_needed()
        page.screenshot(path=str(output / "synthetic-processing.png"))
        expect(page.locator(".transcript-panel .version-chip")).to_have_text("Версия 1", timeout=30000)
        page.get_by_role("tab", name="Обезличено").click()
        expect(page.locator(".transcript-prose")).not_to_contain_text("900101300456")
        page.get_by_role("heading", name="Транскрипция", exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output / "synthetic-transcript.png"))
        checks.append("upload-processing-masking")

        page.get_by_role("button", name="Сформировать черновик", exact=True).click()
        expect(page.get_by_role("form", name=re.compile("документ", re.I))).to_be_visible(timeout=30000)
        add_field = page.get_by_role("button", name="Добавить: Пульс")
        assert add_field.evaluate("el => getComputedStyle(el).display") == "flex", "Sparse fields are missing their inline button layout"
        page.get_by_role("button", name="Добавить: Пульс").click()
        page.get_by_role("textbox", name="Пульс").fill("80/мин")
        page.locator("#field-anamnesis_morbi").scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -110)")
        page.screenshot(path=str(output / "synthetic-doctor-review.png"))
        page.locator(".privacy-card").screenshot(path=str(output / "synthetic-privacy.png"))
        source_button = page.get_by_role("button", name=re.compile("Показать фрагмент записи:.*Кашель длится"))
        source_button.first.click()
        expect(page.get_by_role("status").filter(has_text="Фрагмент записи · 00:04")).to_be_visible()
        page.get_by_role("status").filter(has_text="Фрагмент записи · 00:04").scroll_into_view_if_needed()
        page.screenshot(path=str(output / "synthetic-evidence.png"))
        audio = page.get_by_label("Аудиозапись консультации")
        expect(audio).to_be_visible()
        page.wait_for_function("""() => {
          const audio = document.querySelector('audio[aria-label="Аудиозапись консультации"]');
          return audio && audio.readyState >= 1 && audio.currentTime >= 3.9;
        }""")
        checks.append("grounded-evidence-audio-seek")

        page.get_by_role("button", name="Исправить текст").click()
        page.get_by_role("textbox", name="Фрагмент 2").fill(CORRECTED_SECOND)
        page.get_by_role("button", name="Сохранить исправления").click()
        expect(page.locator(".transcript-panel .version-chip")).to_have_text("Версия 2")
        expect(page.get_by_role("form", name=re.compile("документ", re.I))).to_have_count(0)
        page.get_by_role("button", name="Сформировать черновик", exact=True).click()
        expect(page.get_by_role("form", name=re.compile("документ", re.I))).to_be_visible(timeout=30000)
        checks.append("correction-invalidates-and-regenerates")

        diagnosis = page.locator("#field-diagnosis")
        diagnosis.fill("Синтетическое заключение после проверки врачом")
        page.get_by_role("button", name="Сохранить проверку", exact=True).click()
        expect(page.get_by_role("button", name="Подтвердить", exact=True)).to_be_enabled()
        page.get_by_role("button", name="Подтвердить", exact=True).click()
        expect(page.get_by_role("button", name="Скачать DOCX")).to_be_visible()
        expect(diagnosis).to_be_disabled()

        with page.expect_download() as download_event:
            page.get_by_role("button", name="Скачать DOCX").click()
        docx_path = output / "browser-approved.docx"
        download_event.value.save_as(docx_path)
        with zipfile.ZipFile(docx_path) as docx:
            xml = docx.read("word/document.xml").decode("utf-8")
        assert "Синтетическое заключение после проверки врачом" in xml
        checks.append("review-approval-docx")

        protocol_panel = page.get_by_role("region", name="Протоколы РК")
        search_form = protocol_panel.locator("form")
        assert search_form.evaluate("el => getComputedStyle(el).display") == "grid", "Protocol search controls are not laid out as a grid"
        assert protocol_panel.evaluate("el => getComputedStyle(el).paddingTop") == "30px", "Protocol panel is missing its top spacing"
        protocol_panel.scroll_into_view_if_needed()
        page.screenshot(path=str(output / "synthetic-protocol-panel.png"))
        checks.append("protocol-panel-layout")

        with page.expect_response(lambda response: response.url.endswith("/document.pdf") and response.ok):
            page.get_by_role("button", name="Просмотреть PDF").click()
        dialog = page.get_by_role("dialog", name="Просмотр PDF")
        expect(dialog).to_be_visible()
        first = canvas_fingerprint(page)
        page.screenshot(path=str(output / "synthetic-pdf-preview.png"))
        page.get_by_role("button", name="Следующая страница").click()
        expect(dialog.get_by_text(re.compile(r"Страница 2 из [2-9]"))).to_be_visible()
        second = canvas_fingerprint(page)
        assert first != second, "PDF next page did not paint distinct content"
        with page.expect_download() as pdf_download:
            page.get_by_role("button", name="Скачать PDF").click()
        pdf_path = output / "browser-approved.pdf"
        pdf_download.value.save_as(pdf_path)
        downloaded_pdf = pdf_path.read_bytes()
        page.wait_for_function("window.__medhubPdfHashes.length === 1")
        preview_pdf = page.evaluate("window.__medhubPdfHashes[0]")
        assert preview_pdf == {"size": len(downloaded_pdf), "hash": hashlib.sha256(downloaded_pdf).hexdigest()}, (
            f"Preview response and download differ: preview={preview_pdf}, "
            f"download={{'size': {len(downloaded_pdf)}, 'hash': '{hashlib.sha256(downloaded_pdf).hexdigest()}'}}"
        )
        assert any(status == 200 and mime.startswith(("application/javascript", "text/javascript")) for status, mime in worker_responses), worker_responses
        checks.append("local-worker-two-pages-identical-download")

        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        with page.expect_response(lambda response: response.url.endswith("/document.pdf") and response.ok):
            page.get_by_role("button", name="Просмотреть PDF").click()
        assert canvas_fingerprint(page)
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        page.get_by_role("button", name=re.compile("SYNTHETIC-P0-CARDIOLOGIST")).click()
        expect(page.get_by_role("heading", name="SYNTHETIC-P0-CARDIOLOGIST")).to_be_visible()
        checks.append("close-reopen-consultation-switch")

        page.set_viewport_size({"width": 375, "height": 812})
        page.get_by_role("button", name="Просмотреть PDF").click()
        expect(dialog).to_be_visible()
        assert canvas_fingerprint(page)
        assert page.evaluate("""() => {
          const rect = document.querySelector('.pdf-preview-dialog').getBoundingClientRect();
          return rect.left >= -1 && rect.right <= innerWidth + 1 && rect.top >= -1 && rect.bottom <= innerHeight + 1;
        }"""), "PDF dialog exceeds 375px viewport"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "375px horizontal overflow"
        page.screenshot(path=str(output / "browser-mobile-preview.png"))
        page.keyboard.press("Escape")
        checks.append("mobile-375px-containment")

        public_id = os.environ["MEDHUB_PUBLIC_ID"]
        public_pdf = os.environ["MEDHUB_PUBLIC_PDF"]
        public_context = browser.new_context(viewport={"width": 1440, "height": 900})
        public_page = public_context.new_page()
        public_requests: list[str] = []
        public_page.on("request", lambda request: public_requests.append(f"{request.method} {request.url}"))
        public_page.goto(f"{base_url}/verify/{public_id}")
        expect(public_page.get_by_text("Запись PDF действительна.")).to_be_visible()
        assert "SYNTHETIC-P0" not in public_page.locator("body").inner_text()
        file_input = public_page.get_by_label("Проверить файл PDF")
        file_input.set_input_files(public_pdf)
        expect(public_page.get_by_text("Выбранный PDF совпадает с зарегистрированным хешем.")).to_be_visible()
        file_input.set_input_files(str(pdf_path))
        expect(public_page.get_by_text("Выбранный PDF не совпадает с зарегистрированным хешем.")).to_be_visible()
        assert not any(request.startswith("POST ") for request in public_requests), public_requests
        public_context.close()
        checks.append("anonymous-public-hash-match-and-mismatch")

        assert not external_requests, external_requests
        assert not errors, errors
        assert not any("SYNTHETIC-P0-" in url for url in external_requests)
        browser.close()
    print(json.dumps({"status": "passed", "checks": checks, "artifacts": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
