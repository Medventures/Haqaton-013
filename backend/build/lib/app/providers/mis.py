"""Deterministic, local-only MIS export placeholder."""

import hashlib

from app.schemas import ConsultationData, MISResult


class MockMISProvider:
    async def send_consultation(
        self, consultation: ConsultationData, *, consultation_id: str, patient_id: str
    ) -> MISResult:
        # The backend owns the durable export record and approval checks. This
        # stable identifier avoids duplicate mock side effects on repeat calls.
        digest = hashlib.sha256(consultation_id.encode("utf-8")).hexdigest()[:16].upper()
        return MISResult(success=True, document_id=f"MIS-{digest}", provider="mock")
