"""Catalog-bound, source-only Kazakhstan protocol section lookup.

This is a partial documentation aid. It does not assess clinical compliance.
No patient/document data is sent to the public source.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from typing import Callable
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "diseases.json"
MAX_SOURCE_BYTES = 2_000_000
RK_VERSION = re.compile(r"Версия:\s*(Клинические протоколы МЗ РК\s*[-–]\s*20\d{2}\s*\(Казахстан\))", re.I)
VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class ProtocolSearch(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    limit: int = Field(default=10, ge=1, le=20)


def _text(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class _SourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.version_depth = 0
        self.version_parts: list[str] = []
        self.version = ""
        self.diagnostics_depth = 0
        self.row: list[str] | None = None
        self.cell_depth = 0
        self.cell_parts: list[str] = []
        self.rows: list[list[str]] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in ("script", "style") or self.ignored_depth:
            self.ignored_depth += 1
        if self.version_depth:
            if tag not in VOID_TAGS:
                self.version_depth += 1
        elif tag == "div" and "disease-information__version-name" in (attributes.get("class") or "").split():
            self.version_depth = 1

        if self.diagnostics_depth:
            if tag not in VOID_TAGS:
                self.diagnostics_depth += 1
            if tag == "tr":
                self.row = []
            elif tag == "td" and self.row is not None and not self.cell_depth:
                self.cell_depth = 1
                self.cell_parts = []
            elif self.cell_depth and tag not in VOID_TAGS:
                self.cell_depth += 1
        elif tag == "section" and attributes.get("data-section-name") == "DIAGNOSTICS":
            self.diagnostics_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self.ignored_depth:
            self.ignored_depth -= 1
        if self.cell_depth:
            self.cell_depth -= 1
            if self.cell_depth == 0 and self.row is not None:
                self.row.append(_text(self.cell_parts))
        if tag == "tr" and self.row is not None:
            if len(self.row) >= 2:
                self.rows.append(self.row)
            self.row = None
        if self.diagnostics_depth:
            self.diagnostics_depth -= 1
        if self.version_depth:
            self.version_depth -= 1
            if not self.version_depth:
                self.version = _text(self.version_parts)

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        if self.version_depth:
            self.version_parts.append(data)
        if self.cell_depth:
            self.cell_parts.append(data)


def _mapped_fields(label: str) -> list[str]:
    lowered = label.casefold()
    fields: list[str] = []
    if "жалоб" in lowered:
        fields.append("complaints")
    if "анамнез" in lowered:
        fields.append("anamnesis_morbi")
    if any(word in lowered for word in ("физикаль", "объектив", "осмотр")):
        fields.append("objective_status")
    if any(word in lowered for word in ("температур", "давлени", "пульс", "витал")):
        fields.append("vital_signs")
    return fields


def parse_protocol_page(html: str) -> tuple[str, list[dict]]:
    parser = _SourceParser()
    parser.feed(html)
    version_match = RK_VERSION.fullmatch(parser.version)
    if not version_match:
        raise ValueError("Версия протокола РК не подтверждена")
    checklist = []
    for row in parser.rows:
        label, source_text = row[:2]
        if not label or len(label) > 120 or len(source_text) < 12:
            continue
        checklist.append({
            "id": f"diagnostic-{len(checklist) + 1}", "label": label,
            "quote": source_text[:160].rstrip(), "mapped_fields": _mapped_fields(label),
            "manual_review": True,
        })
        if len(checklist) == 6:
            break
    if not checklist:
        raise ValueError("Диагностические разделы не распознаны")
    return version_match.group(1), checklist


def _catalog_url(url: object) -> tuple[str, str] | None:
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "diseases.medelement.com" or parsed.query or parsed.fragment:
        return None
    path = unquote(parsed.path)
    match = re.fullmatch(r"/disease/([^/]+)/([0-9]{1,8})", path)
    if not match or not any(marker in match.group(1).casefold() for marker in ("-кп-рк-", "-кп-казахстан-")):
        return None
    return match.group(2), url


def load_catalog(path: Path) -> dict[str, dict]:
    items = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(items, list):
        raise ValueError("Catalog is not a list")
    candidates: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        valid = _catalog_url(item.get("url"))
        if not valid:
            continue
        ident, url = valid
        candidates.setdefault(ident, {"id": ident, "name": item["name"].strip()[:200], "source_url": url, "candidate_only": True})
    return candidates


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch_protocol_html(url: str) -> str:
    if _catalog_url(url) is None:
        raise ValueError("Source URL is not an eligible catalog URL")
    parsed = urlsplit(url)
    ascii_url = urlunsplit((parsed.scheme, parsed.netloc, quote(parsed.path, safe="/%-._~"), "", ""))
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    request = Request(ascii_url, headers={"Accept": "text/html", "Accept-Encoding": "identity", "User-Agent": "MedHubProtocolSource/1.0"})
    with opener.open(request, timeout=7) as response:
        if response.geturl() != ascii_url or response.status != 200 or response.headers.get_content_type() != "text/html":
            raise ValueError("Unexpected source response")
        body = response.read(MAX_SOURCE_BYTES + 1)
    if len(body) > MAX_SOURCE_BYTES:
        raise ValueError("Source page is too large")
    return body.decode("utf-8", errors="replace")


def create_protocol_router(current_user: Callable, *, catalog_path: Path | None = None, fetch_html: Callable[[str], str] | None = None) -> APIRouter:
    try:
        catalog = load_catalog(catalog_path or Path(os.getenv("DISEASES_JSON", DEFAULT_CATALOG)))
    except (OSError, ValueError):
        catalog = None
    fetch = fetch_html or fetch_protocol_html
    router = APIRouter(prefix="/api/v1/protocols", tags=["protocols"])

    @router.post("/search")
    def search(request: ProtocolSearch, _user=Depends(current_user)):
        if catalog is None:
            raise HTTPException(503, "Каталог протоколов недоступен")
        query = request.query.strip().casefold()
        if len(query) < 2:
            raise HTTPException(422, "Введите не менее двух символов")
        items = [item for item in catalog.values() if query in item["name"].casefold()]
        return {"items": items[:request.limit]}

    @router.get("/{protocol_id}")
    def detail(protocol_id: str, _user=Depends(current_user)):
        if catalog is None:
            raise HTTPException(503, "Каталог протоколов недоступен")
        candidate = catalog.get(protocol_id)
        if candidate is None:
            raise HTTPException(404, "Протокол не найден в каталоге")
        try:
            html = fetch(candidate["source_url"])
        except Exception:
            raise HTTPException(502, "Источник протокола временно недоступен") from None
        try:
            version, checklist = parse_protocol_page(html)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {
            "id": protocol_id, "name": candidate["name"], "version": version,
            "source_url": candidate["source_url"],
            "retrieved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "checklist": checklist, "scope": "partial_diagnostic_sections",
        }

    return router
