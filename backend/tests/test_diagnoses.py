import pytest

from app.diagnoses import get_diagnosis, search_diagnoses


def test_exact_code_precedes_related_codes_and_preserves_source_name():
    result = search_diagnoses("J20.9")
    assert result["items"][0] == {
        "code": "J20.9", "name_ru": "Острый бронхит неуточненный",
        "name_kz": "Орналасу орны анықталмаған Капош саркомасы",
    }
    assert get_diagnosis("J20.9")["name_ru"] == "Острый бронхит неуточненный"


def test_reference_search_handles_both_languages_and_caps_results():
    assert search_diagnoses("бронхит")["total"] > 1
    assert any(row["code"] == "A00" for row in search_diagnoses("Тырысқақ")["items"])
    assert len(search_diagnoses("A", limit=3)["items"]) == 3
    assert search_diagnoses("   ") == {"items": [], "total": 0}


def test_unknown_code_rejected_but_source_specific_codes_retained():
    assert get_diagnosis("NOT-A-CODE") is None
    assert get_diagnosis("U071")["code"] == "U071"
    with pytest.raises(ValueError):
        search_diagnoses("A", limit=50000)
