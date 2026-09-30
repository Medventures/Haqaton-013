import { z } from 'zod'
import type { ClinicalData, Medication, Status, TemplateField, VitalSigns } from './types'

const optionalText = z.string().max(10000, 'Слишком длинный текст')
const shortText = z.string().max(500, 'Слишком длинный текст')
const item = z.object({ value: shortText })
const medication = z.object({
  name: z.string().trim().min(1, 'Укажите название препарата').max(500),
  dosage: shortText, frequency: shortText, duration: shortText,
})
const vital = z.object({
  temperature: shortText, blood_pressure: shortText, heart_rate: shortText,
  respiratory_rate: shortText, oxygen_saturation: shortText,
})
const templateField = z.object({ key: z.string().min(1).max(200), value: optionalText })
export const clinicalSchema = z.object({
  complaints: z.array(item).max(100), anamnesis_morbi: optionalText, anamnesis_vitae: optionalText,
  allergies: z.array(item).max(100), medications: z.array(medication).max(100), vital_signs: vital,
  objective_status: optionalText, diagnosis: optionalText, diagnosis_code: z.string().max(50),
  recommendations: z.array(item).max(100), prescribed_medications: z.array(medication).max(100),
  additional_notes: optionalText, template_fields: z.array(templateField).max(200),
})
export type ClinicalForm = z.infer<typeof clinicalSchema>

export const emptyClinicalData: ClinicalData = {
  complaints: [], anamnesis_morbi: null, anamnesis_vitae: null, allergies: [],
  medications: [], vital_signs: null, objective_status: null, diagnosis: null,
  diagnosis_code: null, recommendations: [], prescribed_medications: [], additional_notes: null, template_fields: [],
}

const shown = (value: string | null | undefined) => value ?? ''
const cleaned = (value: string) => value.trim() || null
const medicationToForm = (med: Medication) => ({ name: med.name, dosage: shown(med.dosage), frequency: shown(med.frequency), duration: shown(med.duration) })
const formMedication = (med: ClinicalForm['medications'][number]): Medication => ({ name: med.name.trim(), dosage: cleaned(med.dosage), frequency: cleaned(med.frequency), duration: cleaned(med.duration) })

export function clinicalToForm(data: ClinicalData, catalog: TemplateField[] = []): ClinicalForm {
  const v = data.vital_signs
  const values = new Map((data.template_fields ?? []).map(field => [field.key, field.value]))
  const specialtyFields = catalog.length ? catalog.filter(field => !field.clinical_field).map(field => ({ key: field.key, value: values.get(field.key) ?? null })) : (data.template_fields ?? [])
  return {
    complaints: data.complaints.map(value => ({ value })),
    anamnesis_morbi: shown(data.anamnesis_morbi), anamnesis_vitae: shown(data.anamnesis_vitae),
    allergies: data.allergies.map(value => ({ value })),
    medications: data.medications.map(medicationToForm),
    vital_signs: { temperature: shown(v?.temperature), blood_pressure: shown(v?.blood_pressure), heart_rate: shown(v?.heart_rate), respiratory_rate: shown(v?.respiratory_rate), oxygen_saturation: shown(v?.oxygen_saturation) },
    objective_status: shown(data.objective_status), diagnosis: shown(data.diagnosis), diagnosis_code: shown(data.diagnosis_code),
    recommendations: data.recommendations.map(value => ({ value })),
    prescribed_medications: data.prescribed_medications.map(medicationToForm),
    additional_notes: shown(data.additional_notes),
    template_fields: specialtyFields.map(field => ({ key: field.key, value: shown(field.value) })),
  }
}

export function formToClinical(form: ClinicalForm): ClinicalData {
  const vital = Object.fromEntries(Object.entries(form.vital_signs).map(([key, value]) => [key, cleaned(value)])) as unknown as VitalSigns
  return {
    complaints: form.complaints.map(x => x.value.trim()).filter(Boolean),
    anamnesis_morbi: cleaned(form.anamnesis_morbi), anamnesis_vitae: cleaned(form.anamnesis_vitae),
    allergies: form.allergies.map(x => x.value.trim()).filter(Boolean), medications: form.medications.map(formMedication),
    vital_signs: Object.values(vital).some(Boolean) ? vital : null,
    objective_status: cleaned(form.objective_status), diagnosis: cleaned(form.diagnosis), diagnosis_code: cleaned(form.diagnosis_code),
    recommendations: form.recommendations.map(x => x.value.trim()).filter(Boolean),
    prescribed_medications: form.prescribed_medications.map(formMedication), additional_notes: cleaned(form.additional_notes),
    template_fields: form.template_fields.map(field => ({ key: field.key, value: cleaned(field.value) })),
  }
}

export function canApprove(status: Status, isDirty: boolean, version: number): boolean {
  return status === 'REVIEWED' && !isDirty && version > 0
}
