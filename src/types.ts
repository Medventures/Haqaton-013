export type Status = 'CREATED' | 'RECORDING' | 'PROCESSING' | 'TRANSCRIBED' | 'AI_GENERATED' | 'REVIEWED' | 'APPROVED' | 'SENT_TO_MIS' | 'FAILED'

export interface User { id: string; username: string; role: 'doctor' | 'admin'; display_name: string }
export interface Health { status: 'ok'; mode: 'demo' | 'live'; stt_model: string; llm_provider: 'demo' | 'openai'; llm_model: string; mis_provider: 'mock' }
export interface TemplateField { key: string; label: string; prompt: string; section: string; clinical_field?: string | null }
export interface ConsultationTemplate { id: string; name: string; fields: TemplateField[] }
export type ProcessingOperation = 'upload' | 'transcribe' | 'generate'
export type ProcessingStatus = 'running' | 'done' | 'error'
export type StageStatus = 'pending' | ProcessingStatus
export type ProcessingErrorCode = 'UPLOAD_FAILED' | 'STT_FAILED' | 'NORMALIZATION_FAILED' | 'MASKING_FAILED' | 'LLM_FAILED' | 'VALIDATION_FAILED' | 'INTERRUPTED'
export interface ProcessingStage { key: string; attempt: number; status: StageStatus; started_at: string | null; finished_at: string | null; duration_ms: number | null; error_code: ProcessingErrorCode | null }
export interface ProcessingRun { id: string; operation: ProcessingOperation; status: ProcessingStatus; started_at: string; finished_at: string | null; stages: ProcessingStage[] }
export interface Consultation { id: string; external_patient_id: string; template_id: string; status: Status; created_at: string; updated_at: string; approved_at: string | null; error_message: string | null; transcript_revision: number | null; audio_available: boolean; processing_runs: ProcessingRun[] }
export interface TranscriptSegment { id: string; start: number; end: number; text: string; speaker: string | null }
export interface TranscriptTextChange { segment_id: string; text: string }
export interface PIIEntity { type: string; placeholder: string }
export interface Transcript { raw_text: string; normalized_text: string; masked_text: string; current_text: string; revision: number; audio_available: boolean; language: string; duration_seconds: number; stt_model: string; segments: TranscriptSegment[]; pii_entities: PIIEntity[] }
export interface Medication { name: string; dosage: string | null; frequency: string | null; duration: string | null }
export interface VitalSigns { temperature: string | null; blood_pressure: string | null; heart_rate: string | null; respiratory_rate: string | null; oxygen_saturation: string | null }
export interface ClinicalData {
  complaints: string[]
  anamnesis_morbi: string | null
  anamnesis_vitae: string | null
  allergies: string[]
  medications: Medication[]
  vital_signs: VitalSigns | null
  objective_status: string | null
  diagnosis: string | null
  diagnosis_code: string | null
  recommendations: string[]
  prescribed_medications: Medication[]
  additional_notes: string | null
  template_fields: { key: string; value: string | null }[]
}
export interface EvidenceLink { field_path: string; segment_id: string; quote: string; transcript_revision: number; start: number; end: number }
export interface Document { id: string; consultation_id: string; ai_generated_data: ClinicalData; doctor_approved_data: ClinicalData | null; data: ClinicalData; llm_provider: string; llm_model: string; updated_at: string; version: number; source_transcript_revision: number | null; source_masked_text: string | null; evidence: EvidenceLink[] }
export interface AuditEntry { id: string; field: string; ai_value: unknown; doctor_value: unknown; changed: boolean; created_at: string }
export interface ExportResult { success: boolean; document_id: string; provider: 'mock' }
export interface PublicVerification { issuer: 'MedHub'; issued_at: string; status: 'valid'; sha256: string }
export interface ProtocolCandidate { id: string; name: string; source_url: string; candidate_only: true }
export interface ProtocolChecklistItem { id: string; label: string; quote: string; mapped_fields: string[]; manual_review: true }
export interface ClinicalProtocol { id: string; name: string; version: string; source_url: string; retrieved_at: string; checklist: ProtocolChecklistItem[]; scope: 'partial_diagnostic_sections' }
