# Task1 fix1 review

## backend/app/schemas.py
```diff
--- before/backend/app/schemas.py
+++ after/backend/app/schemas.py
@@ -166,20 +166,28 @@
 
     @field_validator("started_at", "finished_at")
     @classmethod
     def utc_time(cls, value: datetime | None) -> datetime | None:
         if value is None:
             return None
         if value.tzinfo is None or value.utcoffset() is None:
             raise ValueError("Timestamp must be timezone-aware")
         return value.astimezone(timezone.utc)
 
+    @model_validator(mode="after")
+    def pending_has_no_timing(self) -> Self:
+        if self.status == "pending" and any(
+            value is not None for value in (self.started_at, self.finished_at, self.duration_ms)
+        ):
+            raise ValueError("Pending stages cannot have measured timing")
+        return self
+
 
 class ProcessingRun(StrictModel):
     id: str = Field(min_length=1, max_length=36)
     operation: str = Field(pattern=r"^(upload|transcribe|generate)$")
     status: str = Field(pattern=r"^(running|done|error)$")
     started_at: datetime
     finished_at: datetime | None = None
     stages: list[ProcessingStage] = Field(default_factory=list)
 
     @field_validator("started_at", "finished_at")

```

## backend/tests/test_schemas.py
```diff
--- before/backend/tests/test_schemas.py
+++ after/backend/tests/test_schemas.py
@@ -79,10 +79,24 @@
         ProcessingRun.model_validate({"id": "run-1", "operation": "unknown", "status": "running", "started_at": "2026-01-01T00:00:00Z", "stages": []})
 
 
 def test_processing_stage_accepts_safe_codes_and_rejects_free_text():
     from app.schemas import ProcessingStage
 
     for code in ("UPLOAD_FAILED", "STT_FAILED", "NORMALIZATION_FAILED", "MASKING_FAILED", "LLM_FAILED", "VALIDATION_FAILED", "INTERRUPTED"):
         assert ProcessingStage(key="stt", attempt=1, status="error", error_code=code).error_code == code
     with pytest.raises(ValidationError):
         ProcessingStage(key="stt", attempt=1, status="error", error_code="Patient name: Иван Иванов")
+
+
+def test_pending_processing_stage_has_no_measured_timing():
+    from app.schemas import ProcessingStage
+
+    base = {"key": "stt", "attempt": 1, "status": "pending"}
+    assert ProcessingStage.model_validate(base).duration_ms is None
+    for timing in (
+        {"started_at": "2026-01-01T00:00:00Z"},
+        {"finished_at": "2026-01-01T00:00:00Z"},
+        {"duration_ms": 12},
+    ):
+        with pytest.raises(ValidationError):
+            ProcessingStage.model_validate({**base, **timing})

```

