# Task2 fix1 review

## backend/app/grounding.py
```diff
--- before/backend/app/grounding.py
+++ after/backend/app/grounding.py
@@ -81,20 +81,19 @@
     if not isinstance(source, CanonicalTranscript):
         raise ValueError("Canonical transcript required")
     if source.text != "\n".join(segment.text for segment in source.segments):
         raise ValueError("Canonical text differs from segments")
     if len({segment.id for segment in source.segments}) != len(source.segments):
         raise ValueError("Duplicate source segment ID")
     if any(segment.speaker is not None for segment in source.segments):
         raise ValueError("Source speaker metadata is forbidden")
-    projected = mask_segments(source.segments, revision=source.revision)
-    if projected.text != source.text or [segment.text for segment in projected.segments] != [
-        segment.text for segment in source.segments
-    ]:
+    # Inspect the exact joined text sent to the provider. Rebuilding it through
+    # normalization would erase whitespace left by a cross-segment projection.
+    if PIIMaskingService().detect_spans(source.text):
         raise ValueError("Source contains unmasked identifiers")
 
 
 def _populated_field(data: ConsultationData, path: str) -> bool:
     parts = path.split("/")
     if len(parts) == 1 and parts[0] in _SCALAR_FIELDS:
         value = getattr(data, parts[0])
         return isinstance(value, str) and bool(value.strip())

```

## backend/tests/test_grounding.py
```diff
--- before/backend/tests/test_grounding.py
+++ after/backend/tests/test_grounding.py
@@ -1,11 +1,11 @@
 import pytest
 
-from app.grounding import mask_segments, normalize_segments, validate_evidence
+from app.grounding import assert_canonical_source, mask_segments, normalize_segments, validate_evidence
 from app.schemas import (
     CanonicalTranscript, ConsultationData, EvidenceClaim, ExtractionResult,
     Medication, StoredTranscriptSegment, TemplateFieldValue, VitalSigns,
 )
 
 
 def segment(identifier: str, text: str, start: float = 0, end: float = 1) -> StoredTranscriptSegment:
     return StoredTranscriptSegment(id=identifier, start=start, end=end, text=text)
@@ -43,16 +43,33 @@
     assert len(source.segments) == 4
     assert [item.id for item in source.segments] == ["s1", "s2", "s3", "s4"]
     assert source.segments[2].text == ""
     assert "Әлиев" not in source.text and "Ержан" not in source.text
     assert "Қызуы 38°С; жүрек соғысы 80." in source.segments[3].text
     assert source.text == "\n".join(item.text for item in source.segments)
 
 
+def test_projected_whitespace_remains_valid_evidence_source():
+    source = mask_segments([
+        segment("s1", "ИИН 010203", 2, 3),
+        segment("s2", "500123 кашель три дня.", 3, 4),
+    ], revision=6)
+    assert source.segments[0].text == "ИИН [IIN_1]"
+    assert source.segments[1].text == " кашель три дня."
+    assert source.text == "ИИН [IIN_1]\n кашель три дня."
+    assert_canonical_source(source)
+    links = validate_evidence(ExtractionResult(
+        data=ConsultationData(complaints=["кашель"]),
+        evidence=[EvidenceClaim(field_path="complaints/0", segment_id="s2", quote=" кашель")],
+    ), source)
+    assert links[0].quote == " кашель"
+    assert (links[0].start, links[0].end, links[0].transcript_revision) == (3, 4, 6)
+
+
 def evidence_fixture() -> tuple[ExtractionResult, CanonicalTranscript]:
     result = ExtractionResult(data=ConsultationData(
         complaints=["сухой кашель"], anamnesis_morbi="три дня",
         medications=[Medication(name="Парацетамол", dosage="500 мг")],
         vital_signs=VitalSigns(temperature="38°С"),
         template_fields=[TemplateFieldValue(key="p_014", value="болезненность")],
         diagnosis_code="J20.9",
     ))

```

## backend/tests/test_providers.py
```diff
--- before/backend/tests/test_providers.py
+++ after/backend/tests/test_providers.py
@@ -1,9 +1,10 @@
 import asyncio
+import json
 from pathlib import Path
 from types import SimpleNamespace
 
 import pytest
 
 from app.grounding import mask_segments
 from app.providers.demo import DEMO_TRANSCRIPT, DemoLLMProvider
 from app.providers.mis import MockMISProvider
@@ -192,16 +193,39 @@
     provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
     with pytest.raises(Exception, match="проверить ответ"):
         run(provider.extract_consultation(original))
     assert len(calls) == 2
     assert calls[0]["input"] == calls[1]["input"]
     assert "Выдуманный фрагмент" not in calls[0]["input"]
 
 
+def test_openai_accepts_cross_segment_masked_source_with_literal_quote_spacing():
+    calls = []
+    masked = mask_segments([
+        StoredTranscriptSegment(id="s1", start=2, end=3, text="ИИН 010203"),
+        StoredTranscriptSegment(id="s2", start=3, end=4, text="500123 кашель три дня."),
+    ], revision=6)
+
+    async def parse(**kwargs):
+        calls.append(kwargs)
+        return SimpleNamespace(output_parsed=ExtractionResult(
+            data=ConsultationData(complaints=["кашель"]),
+            evidence=[EvidenceClaim(field_path="complaints/0", segment_id="s2", quote=" кашель")],
+        ))
+
+    provider = OpenAIProvider("synthetic-key", "gpt-4.1-mini", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
+    result = run(provider.extract_consultation(masked))
+    assert len(calls) == 1
+    assert result.evidence[0].quote == " кашель"
+    sent = json.loads(calls[0]["input"])
+    assert sent["segments"][1] == {"id": "s2", "start": 3.0, "end": 4.0, "text": " кашель три дня."}
+    assert "500123" not in calls[0]["input"]
+
+
 def test_local_storage_rejects_traversal_and_symlink(tmp_path: Path):
     store = LocalStorage(tmp_path / "audio")
     assert store.save("consultation.webm", b"synthetic audio") == "consultation.webm"
     assert store.get("consultation.webm").read_bytes() == b"synthetic audio"
     for key in ("../outside", "/tmp/outside", "nested/../outside", "nested\\outside"):
         with pytest.raises(ValueError):
             store.save(key, b"x")
     outside = tmp_path / "outside"

```

