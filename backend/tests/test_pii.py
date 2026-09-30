from app.normalization import normalize_transcript
from app.pii import PIIMaskingService


def test_spoken_introduction_lowercase_name_and_spaced_iin_are_removed():
    source = (
        "Меня зовут Иван Петров. Пациент иванов иван иванович. "
        "ИИН 010 203 500 123. Кашель три дня, парацетамол 500 мг."
    )
    masked = PIIMaskingService().mask(source).text
    for secret in ("Иван Петров", "иванов иван иванович", "010 203 500 123"):
        assert secret not in masked
    assert "Кашель три дня, парацетамол 500 мг" in masked


def test_masks_kazakhstan_identifiers_and_keeps_clinical_values():
    source = (
        "Пациент Иванов Иван Иванович, ИИН 010203500123, "
        "телефон +7 701 123 45 67, email ivan@example.kz. "
        "Дата рождения 03.02.2001, паспорт N12345678, "
        "адрес: г. Алматы, ул. Абая 10. "
        "Парацетамол 500 мг, АД 120/80, температура 38.2°C."
    )
    masked = PIIMaskingService().mask(source)

    for secret in (
        "Иванов", "010203500123", "+7 701 123 45 67", "ivan@example.kz",
        "03.02.2001", "N12345678", "Абая 10",
    ):
        assert secret not in masked.text
    assert "Парацетамол 500 мг" in masked.text
    assert "АД 120/80" in masked.text
    assert "38.2°C" in masked.text
    assert {item.type for item in masked.entities} >= {
        "PERSON", "IIN", "PHONE", "EMAIL", "DOB", "DOCUMENT", "ADDRESS"
    }
    assert all(set(item.model_dump()) == {"type", "placeholder"} for item in masked.entities)
    assert not hasattr(masked, "mapping")


def test_contextual_two_part_name_and_unlabelled_iin_are_masked():
    masked = PIIMaskingService().mask(
        "ФИО: Ахметов Ержан. 990101300123. Сатурация 97%, пульс 78."
    )
    assert "Ахметов Ержан" not in masked.text
    assert "990101300123" not in masked.text
    assert "Сатурация 97%" in masked.text
    assert "пульс 78" in masked.text


def test_clinical_speech_after_patient_marker_is_not_a_person_name():
    source = "Пациент сообщает о сухом кашле. Пациент принимал парацетамол 500 мг."
    assert PIIMaskingService().mask(source).text == source


def test_birth_date_words_and_multiword_address_with_apartment_are_masked():
    source = (
        "Родился 01.02.1990, дата рождения 1 января 1990. "
        "Адрес: г. Алматы, ул. Кабанбай батыра 10, кв. 5."
    )
    masked = PIIMaskingService().mask(source)
    for secret in ("01.02.1990", "1 января 1990", "Кабанбай батыра 10", "кв. 5"):
        assert secret not in masked.text


def test_normalization_preserves_uncertain_clinical_meaning():
    raw = "  Возможно   парацетомол 500 мг?\nАД 120 на 80; аллергии нет.  "
    assert normalize_transcript(raw) == "Возможно парацетомол 500 мг?\nАД 120 на 80; аллергии нет."
