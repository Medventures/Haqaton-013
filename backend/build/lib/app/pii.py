"""Local, conservative Kazakhstan-aware PII redaction before external calls."""

from __future__ import annotations

import re
from collections import defaultdict

from app.schemas import MaskedTranscript, PIIEntity


_CYR_WORD = r"[А-ЯЁӘҒҚҢӨҰҮҺІ][а-яёәғқңөұүһі]+"
_CYR_ANY = r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі-]+"
_ADDRESS_WORD = r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі-]+"
_STREET = rf"(?:ул\.|улица|проспект|мкр\.?|микрорайон)\s*(?:{_ADDRESS_WORD}\s+){{1,4}}\d+[А-Яа-яA-Za-z]?"
_APARTMENT = r"(?:,\s*(?:кв\.?|квартира)\s*\d+)?"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}(?![\w-])", re.I)),
    ("IIN", re.compile(r"(?i:ИИН)\s*[:№-]?\s*((?:\d[\s-]*){11}\d)(?!\d)")),
    ("IIN", re.compile(r"(?<!\d)(?:\d[ \t\n-]*){11}\d(?!\d)")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+7|8)[\s().-]*\(?7\d{2}\)?(?:[\s().-]*\d){7}(?!\d)")),
    ("DOB", re.compile(
        r"(?:дата\s+рождения|д\.?\s*р\.?|родил(?:ся|ась))\s*[:–-]?\s*"
        r"(\d{1,2}(?:[./-]\d{1,2}[./-]|\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+)\d{4})",
        re.I,
    )),
    ("DOCUMENT", re.compile(r"(?:паспорт|удостоверени[ея]\s+личности|номер\s+документа)\s*(?:№|#|номер)?\s*[:–-]?\s*([A-ZА-ЯЁ]{0,2}\d{6,10})", re.I)),
    ("ADDRESS", re.compile(rf"\bадрес\s*:\s*((?:г\.\s*{_ADDRESS_WORD},?\s*)?{_STREET}{_APARTMENT})", re.I)),
    ("ADDRESS", re.compile(rf"\b{_STREET}{_APARTMENT}", re.I)),
    ("PERSON", re.compile(rf"(?i:меня\s+зовут|мое\s+имя|моё\s+имя|ФИО|фамилия\s+и\s+имя)\s*[:–-]?\s*({_CYR_ANY}(?:\s+{_CYR_ANY}){{1,2}})(?!\w)")),
    ("PERSON", re.compile(rf"(?i:пациент(?:ка)?)\s*[:–-]?\s*({_CYR_WORD}\s+{_CYR_WORD}(?:\s+{_CYR_WORD})?)(?!\w)")),
    ("PERSON", re.compile(rf"(?i:пациент(?:ка)?)\s*[:–-]?\s*({_CYR_ANY}\s+{_CYR_ANY}\s+{_CYR_ANY}(?:вич|вна|улы|ұлы|қызы|кызы))(?!\w)", re.I)),
    ("PERSON", re.compile(rf"(?<!\w){_CYR_WORD}\s+{_CYR_WORD}\s+{_CYR_WORD}(?!\w)")),
)


class PIIMaskingService:
    def detect_spans(self, transcript: str) -> list[tuple[int, int, str]]:
        if not isinstance(transcript, str):
            raise TypeError("Transcript must be text")

        spans: list[tuple[int, int, str]] = []
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(transcript):
                target = match.group(1) if match.lastindex else match.group(0)
                start = match.start(1) if match.lastindex else match.start()
                end = start + len(target)
                if start == end or any(start < used_end and end > used_start for used_start, used_end, _ in spans):
                    continue
                spans.append((start, end, kind))

        return sorted(spans, key=lambda value: value[0])

    def mask(self, transcript: str) -> MaskedTranscript:
        spans = self.detect_spans(transcript)
        counters: defaultdict[str, int] = defaultdict(int)
        entities: list[PIIEntity] = []
        chunks: list[str] = []
        cursor = 0
        for start, end, kind in spans:
            counters[kind] += 1
            placeholder = f"[{kind}_{counters[kind]}]"
            chunks.extend((transcript[cursor:start], placeholder))
            entities.append(PIIEntity(type=kind, placeholder=placeholder))
            cursor = end
        chunks.append(transcript[cursor:])
        return MaskedTranscript(text="".join(chunks), entities=entities)
