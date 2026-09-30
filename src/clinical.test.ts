import { describe, expect, it } from 'vitest'
import { clinicalSchema, emptyClinicalData, formToClinical, clinicalToForm, canApprove } from './clinical'

describe('clinical editor contract', () => {
  it('keeps every clinical field when mapping a reviewed form to the API', () => {
    const form = clinicalToForm({
      complaints: ['Кашель'], anamnesis_morbi: '3 дня', anamnesis_vitae: 'Не уточнено',
      allergies: ['Пенициллин'], medications: [{ name: 'Парацетамол', dosage: '500 мг', frequency: '2 раза', duration: '3 дня' }],
      vital_signs: { temperature: '38 °C', blood_pressure: '120/80', heart_rate: '80', respiratory_rate: '16', oxygen_saturation: '98%' },
      objective_status: 'Без особенностей', diagnosis: 'ОРВИ', diagnosis_code: 'J06.9', recommendations: ['Покой'],
      prescribed_medications: [{ name: 'Ибупрофен', dosage: '200 мг', frequency: 'при боли', duration: null }],
      additional_notes: 'Повторный осмотр', template_fields: [{ key: 'heart_rhythm', value: 'Ритмичный' }],
    })
    expect(formToClinical(clinicalSchema.parse(form))).toEqual({
      complaints: ['Кашель'], anamnesis_morbi: '3 дня', anamnesis_vitae: 'Не уточнено',
      allergies: ['Пенициллин'], medications: [{ name: 'Парацетамол', dosage: '500 мг', frequency: '2 раза', duration: '3 дня' }],
      vital_signs: { temperature: '38 °C', blood_pressure: '120/80', heart_rate: '80', respiratory_rate: '16', oxygen_saturation: '98%' },
      objective_status: 'Без особенностей', diagnosis: 'ОРВИ', diagnosis_code: 'J06.9', recommendations: ['Покой'],
      prescribed_medications: [{ name: 'Ибупрофен', dosage: '200 мг', frequency: 'при боли', duration: null }],
      additional_notes: 'Повторный осмотр', template_fields: [{ key: 'heart_rhythm', value: 'Ритмичный' }],
    })
  })

  it('sends no invented fields and rejects medication without a name', () => {
    expect(formToClinical(clinicalSchema.parse(clinicalToForm(emptyClinicalData)))).toEqual(emptyClinicalData)
    const invalid = clinicalToForm(emptyClinicalData)
    invalid.medications.push({ name: '', dosage: '500 мг', frequency: '', duration: '' })
    expect(clinicalSchema.safeParse(invalid).success).toBe(false)
  })

  it('initializes all specialty prompts empty and preserves edited values by stable key', () => {
    const fields = [
      { key: 'clinical_note', label: 'Заметка', prompt: 'Исходный вопрос', section: 'Осмотр' },
      { key: 'mapped_diagnosis', label: 'Диагноз', prompt: 'Диагноз', section: 'Заключение', clinical_field: 'diagnosis' },
    ]
    const form = clinicalToForm(emptyClinicalData, fields)
    expect(form.template_fields).toEqual([{ key: 'clinical_note', value: '' }])
    form.template_fields[0].value = 'Указано врачом'
    expect(formToClinical(clinicalSchema.parse(form)).template_fields).toEqual([{ key: 'clinical_note', value: 'Указано врачом' }])
  })

  it('requires a saved reviewed version before approval', () => {
    expect(canApprove('AI_GENERATED', false, 1)).toBe(false)
    expect(canApprove('REVIEWED', true, 2)).toBe(false)
    expect(canApprove('REVIEWED', false, 0)).toBe(false)
    expect(canApprove('REVIEWED', false, 2)).toBe(true)
  })
})
