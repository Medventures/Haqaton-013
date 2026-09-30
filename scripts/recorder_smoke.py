"""Exercise browser MediaRecorder with generated audio, never a real microphone."""

import json
import os
import re
import time

from playwright.sync_api import expect, sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        headless=True,
        executable_path=os.getenv("MEDHUB_BROWSER_EXECUTABLE") or None,
        args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    )
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["microphone"])
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(os.getenv("MEDHUB_BASE_URL", "http://127.0.0.1:5173"))
    page.get_by_label("Логин", exact=True).fill("doctor")
    page.get_by_label("Пароль", exact=True).fill("demo-doctor")
    page.get_by_role("button", name="Войти", exact=True).click()
    page.get_by_role("button", name="Новая консультация", exact=True).first.click()
    page.get_by_label("ID пациента", exact=True).fill(f"SYNTHETIC-RECORDER-{int(time.time())}")
    page.get_by_role("button", name="Создать", exact=True).click()
    responses = []
    for attempt in range(2):
        page.get_by_role("button", name="Начать запись", exact=True).click()
        expect(page.get_by_role("heading", name=re.compile(r"Идёт запись.*00:0[1-9]"))).to_be_visible(timeout=15000)
        with page.expect_response(lambda response: response.url.endswith("/audio") and response.request.method == "POST") as uploaded:
            page.get_by_role("button", name="Завершить запись", exact=True).click()
        assert uploaded.value.status == 200, uploaded.value.text()
        assert uploaded.value.json()["status"] == "RECORDING"
        expect(page.get_by_role("button", name="Транскрибировать аудио", exact=True)).to_be_enabled()
        responses.append(uploaded.value.status)
    assert not errors, errors
    print(json.dumps({"status": "passed", "uploads": responses,
                      "checks": ["generated microphone audio", "MediaRecorder upload", "recording retry", "transcribe enabled", "no JS errors"]}))
    browser.close()
