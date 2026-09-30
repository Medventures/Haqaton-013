"""User-supplied ICD reference lookup, without diagnostic inference."""

import csv
import os
from functools import lru_cache
from pathlib import Path


DEFAULT_CSV = Path(__file__).resolve().parents[2] / "seed" / "ref_disability_diagnoses_202609301227.csv"


@lru_cache(maxsize=4)
def _catalog(path: str) -> tuple[dict[str, dict], list[tuple[dict, str]]]:
    by_code: dict[str, dict] = {}
    indexed = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"code", "name_ru", "name_kz"}.issubset(reader.fieldnames or []):
            raise ValueError("Diagnosis reference columns are missing")
        for source in reader:
            row = {key: (source.get(key) or "").strip() for key in ("code", "name_ru", "name_kz")}
            if not row["code"] or not row["name_ru"] or row["code"] in by_code:
                raise ValueError("Invalid or duplicate diagnosis reference entry")
            by_code[row["code"]] = row
            indexed.append((row, " ".join(row.values()).casefold()))
    return by_code, indexed


def _data():
    return _catalog(os.getenv("DIAGNOSES_CSV", str(DEFAULT_CSV)))


def get_diagnosis(code: str) -> dict | None:
    row = _data()[0].get(code.strip().upper())
    return dict(row) if row else None


def search_diagnoses(query: str, limit: int = 20) -> dict:
    if not 1 <= limit <= 50 or len(query) > 100:
        raise ValueError("Search bounds exceeded")
    query = query.strip().casefold()
    if not query:
        return {"items": [], "total": 0}
    tokens = query.split()
    matches = [row for row, haystack in _data()[1] if all(token in haystack for token in tokens)]
    matches.sort(key=lambda row: (row["code"].casefold() != query,
                                  not row["code"].casefold().startswith(query), row["code"]))
    return {"items": [dict(row) for row in matches[:limit]], "total": len(matches)}
