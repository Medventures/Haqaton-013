"""Source-only RK protocol discovery never infers clinical compliance."""

from __future__ import annotations

import json
import re

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from app.protocols import create_protocol_router


RK_URL = "https://diseases.medelement.com/disease/аллергический-ринит-кп-рк-2023/18218"
FOREIGN_URL = "https://diseases.medelement.com/disease/гемофилия-кп-кр-2013/16785"
GENERIC_URL = "https://diseases.medelement.com/disease/абдоминальная-травма/15016"


def page(version: str) -> str:
    return f"""
    <html><body>
      <nav>Протоколы Казахстан — список всех стран</nav>
      <div class="disease-information__version-name"><p class="lead">Версия: {version}</p></div>
      <section class="page-section" data-section-name="DIAGNOSTICS">
        <h2>Диагностика</h2><table>
          <tr><td><strong>Жалобы и анамнез</strong></td>
              <td>Выделения из носа, зуд в носу. Уточнить сезонность заболевания.</td></tr>
          <tr><td><strong>Физикальное обследование</strong></td>
              <td>Осмотр слизистой оболочки носа и кожи около носа.</td></tr>
          <tr><td><strong>Лабораторные методы</strong></td>
              <td>Определение общего IgE в сыворотке крови.</td></tr>
        </table>
      </section>
      <section data-section-name="TREATMENT"><table><tr><td>Лечение</td><td>Не извлекать</td></tr></table></section>
    </body></html>"""


def client(tmp_path, *, html: str | Exception = page("Клинические протоколы МЗ РК - 2023 (Казахстан)")):
    catalog = tmp_path / "diseases.json"
    catalog.write_text(json.dumps([
        {"name": "Аллергический ринит", "url": RK_URL},
        {"name": "Гемофилия", "url": FOREIGN_URL},
        {"name": "Абдоминальная травма", "url": GENERIC_URL},
        {"name": "Поддельный протокол", "url": "https://evil.example/disease/подделка-кп-рк-2023/99999"},
    ], ensure_ascii=False), encoding="utf-8")
    fetched = []

    def fetch(url):
        fetched.append(url)
        if isinstance(html, Exception):
            raise html
        return html

    def auth(authorization: str | None = Header(None)):
        if authorization != "Bearer synthetic":
            raise HTTPException(401, "Требуется вход")
        return object()

    app = FastAPI()
    app.include_router(create_protocol_router(auth, catalog_path=catalog, fetch_html=fetch))
    return TestClient(app), fetched


def test_search_returns_only_catalogued_rk_candidates_without_fetching(tmp_path):
    api, fetched = client(tmp_path)
    unauthorized = api.post("/api/v1/protocols/search", json={"query": "ринит"})
    assert unauthorized.status_code == 401
    found = api.post("/api/v1/protocols/search", headers={"Authorization": "Bearer synthetic"}, json={"query": "ринит"})
    assert found.status_code == 200
    assert found.json() == {"items": [{"id": "18218", "name": "Аллергический ринит", "source_url": RK_URL, "candidate_only": True}]}
    assert fetched == []


def test_get_confirms_page_version_and_returns_literal_diagnostic_snippets(tmp_path):
    api, fetched = client(tmp_path)
    result = api.get("/api/v1/protocols/18218", headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 200
    body = result.json()
    assert body["id"] == "18218" and body["name"] == "Аллергический ринит"
    assert body["version"] == "Клинические протоколы МЗ РК - 2023 (Казахстан)"
    assert body["source_url"] == RK_URL and body["scope"] == "partial_diagnostic_sections"
    assert body["retrieved_at"].endswith("Z")
    assert body["checklist"][0] == {
        "id": "diagnostic-1", "label": "Жалобы и анамнез",
        "quote": "Выделения из носа, зуд в носу. Уточнить сезонность заболевания.",
        "mapped_fields": ["complaints", "anamnesis_morbi"], "manual_review": True,
    }
    assert body["checklist"][1]["mapped_fields"] == ["objective_status"]
    assert body["checklist"][2]["mapped_fields"] == []
    assert all("Не извлекать" not in item["quote"] for item in body["checklist"])
    assert fetched == [RK_URL]


def test_foreign_generic_and_external_catalog_entries_never_fetch(tmp_path):
    api, fetched = client(tmp_path)
    for ident in ("16785", "15016", "99999", "https://evil.example"):
        result = api.get(f"/api/v1/protocols/{ident}", headers={"Authorization": "Bearer synthetic"})
        assert result.status_code == 404
    assert fetched == []


def test_navigation_country_text_cannot_substitute_for_rk_version(tmp_path):
    api, fetched = client(tmp_path, html=page("Клинические протоколы КР - 2023 (Кыргызстан)"))
    result = api.get("/api/v1/protocols/18218", headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 422
    assert result.json()["detail"] == "Версия протокола РК не подтверждена"
    assert fetched == [RK_URL]


def test_upstream_failure_returns_safe_message_without_source_body(tmp_path):
    api, _ = client(tmp_path, html=RuntimeError("secret source bytes"))
    result = api.get("/api/v1/protocols/18218", headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 502
    assert result.json()["detail"] == "Источник протокола временно недоступен"
    assert "secret" not in result.text


def test_unstructured_diagnostic_page_fails_closed(tmp_path):
    source = page("Клинические протоколы МЗ РК - 2023 (Казахстан)")
    source = re.sub(r"<table>.*?</table>", "<p>Диагностический текст без структурированных пунктов.</p>", source, count=1, flags=re.S)
    api, _ = client(tmp_path, html=source)
    result = api.get("/api/v1/protocols/18218", headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 422
    assert result.json()["detail"] == "Диагностические разделы не распознаны"


def test_missing_catalog_does_not_block_api_startup(tmp_path):
    app = FastAPI()
    app.include_router(create_protocol_router(lambda: object(), catalog_path=tmp_path / "missing.json"))
    result = TestClient(app).post("/api/v1/protocols/search", json={"query": "ринит"})
    assert result.status_code == 503
    assert result.json()["detail"] == "Каталог протоколов недоступен"


def test_script_and_style_text_are_not_clinical_quotes(tmp_path):
    source = page("Клинические протоколы МЗ РК - 2023 (Казахстан)")
    source = source.replace("Выделения из носа", "<script>Ложный обязательный критерий</script><style>Скрытый критерий</style>Выделения из носа")
    api, _ = client(tmp_path, html=source)
    result = api.get("/api/v1/protocols/18218", headers={"Authorization": "Bearer synthetic"})
    assert result.status_code == 200
    assert result.json()["checklist"][0]["quote"] == "Выделения из носа, зуд в носу. Уточнить сезонность заболевания."
