"""Canonical masked segment projection and server-owned evidence links."""

from __future__ import annotations

from collections import defaultdict

from app.normalization import normalize_transcript
from app.pii import PIIMaskingService
from app.schemas import (
    CanonicalTranscript, ConsultationData, EvidenceLink, ExtractionResult,
    Medication, PIIEntity, StoredTranscriptSegment, VitalSigns,
)


_SCALAR_FIELDS = {
    "anamnesis_morbi", "anamnesis_vitae", "objective_status", "diagnosis", "additional_notes",
}
_LIST_FIELDS = {"complaints", "allergies", "recommendations"}
_MEDICATION_FIELDS = {"medications", "prescribed_medications"}
_MEDICATION_PROPERTIES = set(Medication.model_fields)
_VITAL_PROPERTIES = set(VitalSigns.model_fields)


def normalize_segments(segments: list[StoredTranscriptSegment]) -> list[StoredTranscriptSegment]:
    """Clean whitespace within each original segment without changing its identity or timing."""
    return [segment.model_copy(update={"text": normalize_transcript(segment.text)}) for segment in segments]


def mask_segments(segments: list[StoredTranscriptSegment], *, revision: int) -> CanonicalTranscript:
    """Mask a joined transcript, then project replacements onto original segment boundaries."""
    normalized = normalize_segments(segments)
    joined = "\n".join(segment.text for segment in normalized)
    spans = PIIMaskingService().detect_spans(joined)
    ranges: list[tuple[int, int]] = []
    position = 0
    for segment in normalized:
        ranges.append((position, position + len(segment.text)))
        position += len(segment.text) + 1

    replacements: list[list[tuple[int, int, str]]] = [[] for _ in normalized]
    counters: defaultdict[str, int] = defaultdict(int)
    entities: list[PIIEntity] = []
    for start, end, kind in spans:
        counters[kind] += 1
        placeholder = f"[{kind}_{counters[kind]}]"
        entities.append(PIIEntity(type=kind, placeholder=placeholder))
        inserted = False
        for index, (segment_start, segment_end) in enumerate(ranges):
            covered_start = max(start, segment_start)
            covered_end = min(end, segment_end)
            if covered_start >= covered_end:
                continue
            replacements[index].append((
                covered_start - segment_start,
                covered_end - segment_start,
                "" if inserted else placeholder,
            ))
            inserted = True

    projected: list[StoredTranscriptSegment] = []
    for segment, edits in zip(normalized, replacements, strict=True):
        cursor = 0
        pieces: list[str] = []
        for start, end, replacement in edits:
            pieces.extend((segment.text[cursor:start], replacement))
            cursor = end
        pieces.append(segment.text[cursor:])
        projected.append(segment.model_copy(update={"text": "".join(pieces), "speaker": None}))

    projected = [StoredTranscriptSegment.model_validate(segment.model_dump()) for segment in projected]
    return CanonicalTranscript(
        revision=revision,
        segments=projected,
        text="\n".join(segment.text for segment in projected),
        entities=entities,
    )


def assert_canonical_source(source: CanonicalTranscript) -> None:
    """Reject malformed or newly detectable PII before any external transport."""
    if not isinstance(source, CanonicalTranscript):
        raise ValueError("Canonical transcript required")
    if source.text != "\n".join(segment.text for segment in source.segments):
        raise ValueError("Canonical text differs from segments")
    if len({segment.id for segment in source.segments}) != len(source.segments):
        raise ValueError("Duplicate source segment ID")
    if any(segment.speaker is not None for segment in source.segments):
        raise ValueError("Source speaker metadata is forbidden")
    # Inspect the exact joined text sent to the provider. Rebuilding it through
    # normalization would erase whitespace left by a cross-segment projection.
    if PIIMaskingService().detect_spans(source.text):
        raise ValueError("Source contains unmasked identifiers")


def _populated_field(data: ConsultationData, path: str) -> bool:
    parts = path.split("/")
    if len(parts) == 1 and parts[0] in _SCALAR_FIELDS:
        value = getattr(data, parts[0])
        return isinstance(value, str) and bool(value.strip())

    if len(parts) == 2 and parts[0] in _LIST_FIELDS | {"template_fields"}:
        if parts[0] == "template_fields":
            return any(item.key == parts[1] and item.value and item.value.strip() for item in data.template_fields)
        if not parts[1].isascii() or not parts[1].isdecimal() or str(int(parts[1])) != parts[1]:
            return False
        items = getattr(data, parts[0])
        index = int(parts[1])
        return index < len(items) and bool(items[index].strip())

    if len(parts) == 3 and parts[0] in _MEDICATION_FIELDS and parts[2] in _MEDICATION_PROPERTIES:
        if not parts[1].isascii() or not parts[1].isdecimal() or str(int(parts[1])) != parts[1]:
            return False
        items = getattr(data, parts[0])
        index = int(parts[1])
        if index >= len(items):
            return False
        value = getattr(items[index], parts[2])
        return isinstance(value, str) and bool(value.strip())

    if len(parts) == 2 and parts[0] == "vital_signs" and parts[1] in _VITAL_PROPERTIES:
        value = getattr(data.vital_signs, parts[1]) if data.vital_signs else None
        return isinstance(value, str) and bool(value.strip())
    return False


def validate_evidence(result: ExtractionResult, source: CanonicalTranscript) -> list[EvidenceLink]:
    """Resolve model claims against populated values and the exact masked segment text."""
    assert_canonical_source(source)
    keys = [item.key for item in result.data.template_fields]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate specialty key")
    segments = {segment.id: segment for segment in source.segments}
    links: list[EvidenceLink] = []
    for claim in result.evidence:
        segment = segments.get(claim.segment_id)
        if segment is None or claim.quote not in segment.text or not _populated_field(result.data, claim.field_path):
            raise ValueError("Invalid evidence claim")
        links.append(EvidenceLink(
            field_path=claim.field_path,
            segment_id=claim.segment_id,
            quote=claim.quote,
            transcript_revision=source.revision,
            start=segment.start,
            end=segment.end,
        ))
    return links
