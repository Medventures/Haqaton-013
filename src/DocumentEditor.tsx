import { useEffect, useRef, useState } from 'react'
import { zodResolver } from '@hookform/resolvers/zod'
import { useFieldArray, useForm, type Control, type FieldErrors, type UseFormRegister } from 'react-hook-form'
import { AlertCircle, Check, CheckCheck, FileText, Plus, Save, ShieldCheck, Trash2 } from 'lucide-react'
import { Button } from './ui'
import { DiagnosisPicker } from './DiagnosisPicker'
import { ApiError } from './api'
import { canApprove, clinicalSchema, clinicalToForm, formToClinical, type ClinicalForm } from './clinical'
import { SourceEvidence, type SourceSelection } from './SourceEvidence'
import { ProtocolPanel } from './ProtocolPanel'
import type { ClinicalData, ConsultationTemplate, Document, Status } from './types'
import './clinical-review.css'

type Props = {
  document: Document; template: ConsultationTemplate; status: Status; busy: boolean; regenerationRevision: number;
  onSave: (data: ReturnType<typeof formToClinical>, version: number) => Promise<Document>;
  onApprove: (version: number) => Promise<void>;
  onReload: () => Promise<Document>;
  onDirtyChange: (dirty: boolean) => void;
  onSourceSelect?: (selection: SourceSelection) => void;
}

function sourcePaths(data: ClinicalData): string[] {
  const paths: string[] = []
  for (const [key, value] of Object.entries(data)) {
    if (key === 'diagnosis_code' || value == null) continue
    if (key === 'template_fields') {
      for (const field of data.template_fields) if (field.value) paths.push(`template_fields/${field.key}`)
    } else if (key === 'vital_signs') {
      for (const [name, entry] of Object.entries(data.vital_signs ?? {})) if (entry) paths.push(`vital_signs/${name}`)
    } else if (Array.isArray(value)) {
      value.forEach((entry, index) => {
        if (typeof entry === 'string') paths.push(`${key}/${index}`)
        else if (entry && typeof entry === 'object') for (const [name, part] of Object.entries(entry)) if (part) paths.push(`${key}/${index}/${name}`)
      })
    } else if (value) paths.push(key)
  }
  return paths
}

function pathLabel(path: string, template: ConsultationTemplate): string {
  if (path.startsWith('template_fields/')) return template.fields.find(field => field.key === path.split('/')[1])?.label ?? path
  const names: Record<string, string> = { complaints: 'Жалобы', anamnesis_morbi: 'История заболевания', anamnesis_vitae: 'Анамнез жизни', allergies: 'Аллергии', medications: 'Принимаемые препараты', vital_signs: 'Показатели', objective_status: 'Объективный статус', diagnosis: 'Диагноз', recommendations: 'Рекомендации', prescribed_medications: 'Назначенные препараты', additional_notes: 'Дополнительные заметки' }
  const [root, index, part] = path.split('/')
  return [names[root] ?? root, index && /^\d+$/.test(index) ? `№${Number(index) + 1}` : index, part].filter(Boolean).join(' · ')
}

function Field({ label, name, register, multiline = false, disabled = false, hint }: { label: string; name: keyof Pick<ClinicalForm, 'anamnesis_morbi' | 'anamnesis_vitae' | 'objective_status' | 'diagnosis' | 'additional_notes'>; register: UseFormRegister<ClinicalForm>; multiline?: boolean; disabled?: boolean; hint?: string }) {
  const id = `field-${name}`
  return <label htmlFor={id} className="field-label">{label}{hint && <span className="field-hint">{hint}</span>}{multiline ? <textarea id={id} {...register(name)} disabled={disabled} rows={3} className="input resize-y" /> : <input id={id} {...register(name)} disabled={disabled} className="input" />}</label>
}

function OptionalField({ label, initialValue, resetToken, editable, disabled, children }: { label: string; initialValue: string | null | undefined; resetToken: number; editable: boolean; disabled: boolean; children: React.ReactNode }) {
  const [expanded, setExpanded] = useState(Boolean(initialValue?.trim()))
  useEffect(() => { setExpanded(Boolean(initialValue?.trim())) }, [resetToken])
  if (!expanded) return editable ? <button type="button" className="add-field" disabled={disabled} aria-label={`Добавить: ${label}`} onClick={() => setExpanded(true)}><Plus size={15} /> Добавить: {label}</button> : null
  return <>{children}</>
}

type ArrayName = 'complaints' | 'allergies' | 'recommendations'
function TextList({ name, title, placeholder, control, register, errors, disabled }: { name: ArrayName; title: string; placeholder: string; control: Control<ClinicalForm>; register: UseFormRegister<ClinicalForm>; errors: FieldErrors<ClinicalForm>; disabled: boolean }) {
  const { fields, append, remove } = useFieldArray({ control, name })
  if (disabled && fields.length === 0) return null
  return <section className="form-section"><div className="form-section-head"><h3>{title}</h3>{!disabled && <Button type="button" variant="ghost" size="sm" aria-label={`Добавить: ${title}`} onClick={() => append({ value: '' })}><Plus size={15} /> Добавить</Button>}</div>
    <div className="space-y-2">{fields.map((field, i) => <div className="flex items-start gap-2" key={field.id}><div className="flex-1"><input aria-label={`${title}, пункт ${i + 1}`} placeholder={placeholder} {...register(`${name}.${i}.value`)} disabled={disabled} className="input" />{errors[name]?.[i]?.value && <p className="field-error">{errors[name]?.[i]?.value?.message}</p>}</div>{!disabled && <Button aria-label={`Удалить пункт ${i + 1} из ${title.toLowerCase()}`} type="button" variant="ghost" size="icon" onClick={() => remove(i)}><Trash2 size={16} /></Button>}</div>)}</div>
  </section>
}

type MedicationName = 'medications' | 'prescribed_medications'
function MedicationList({ name, title, control, register, errors, disabled }: { name: MedicationName; title: string; control: Control<ClinicalForm>; register: UseFormRegister<ClinicalForm>; errors: FieldErrors<ClinicalForm>; disabled: boolean }) {
  const { fields, append, remove } = useFieldArray({ control, name })
  if (disabled && fields.length === 0) return null
  return <section className="form-section"><div className="form-section-head"><h3>{title}</h3>{!disabled && <Button type="button" variant="ghost" size="sm" aria-label={`Добавить: ${title}`} onClick={() => append({ name: '', dosage: '', frequency: '', duration: '' })}><Plus size={15} /> Добавить</Button>}</div>
    {fields.map((field, i) => <div className="med-card" key={field.id}><div className="med-card-head"><span>Препарат {i + 1}</span>{!disabled && <Button aria-label={`Удалить препарат ${i + 1}`} type="button" variant="ghost" size="icon" onClick={() => remove(i)}><Trash2 size={16} /></Button>}</div><div className="grid gap-3 sm:grid-cols-2"><label className="field-label">Название<input aria-label={`${title}: название ${i + 1}`} {...register(`${name}.${i}.name`)} disabled={disabled} className="input" />{errors[name]?.[i]?.name && <span className="field-error">{errors[name]?.[i]?.name?.message}</span>}</label><label className="field-label">Дозировка<input {...register(`${name}.${i}.dosage`)} disabled={disabled} className="input" /></label><label className="field-label">Частота<input {...register(`${name}.${i}.frequency`)} disabled={disabled} className="input" /></label><label className="field-label">Длительность<input {...register(`${name}.${i}.duration`)} disabled={disabled} className="input" /></label></div></div>)}
  </section>
}

const vitalFields = [
  ['temperature', 'Температура'], ['blood_pressure', 'Давление'], ['heart_rate', 'Пульс'],
  ['respiratory_rate', 'Частота дыхания'], ['oxygen_saturation', 'Сатурация'],
] as const

export function DocumentEditor({ document, template, status, busy, regenerationRevision, onSave, onApprove, onReload, onDirtyChange, onSourceSelect }: Props) {
  const [version, setVersion] = useState(document.version)
  const lastRegeneration = useRef(regenerationRevision)
  const dirtyRef = useRef(false)
  const [saved, setSaved] = useState(false)
  const [actionError, setActionError] = useState('')
  const [conflict, setConflict] = useState(false)
  const editable = status === 'AI_GENERATED' || status === 'REVIEWED'
  const { register, control, handleSubmit, reset, watch, setValue, formState: { errors, isDirty, isSubmitting } } = useForm<ClinicalForm>({ resolver: zodResolver(clinicalSchema), defaultValues: clinicalToForm(document.data, template.fields) })
  useEffect(() => { if (!dirtyRef.current && document.version !== version) { reset(clinicalToForm(document.data, template.fields)); setVersion(document.version) } }, [document, isDirty, reset, version, template.fields])
  useEffect(() => {
    if (lastRegeneration.current === regenerationRevision) return
    lastRegeneration.current = regenerationRevision
    reset(clinicalToForm(document.data, template.fields))
    dirtyRef.current = false
    setVersion(document.version)
    setSaved(false)
    setActionError('')
    setConflict(false)
    onDirtyChange(false)
  }, [regenerationRevision, document, reset, template.fields, onDirtyChange])
  useEffect(() => { dirtyRef.current = isDirty; onDirtyChange(isDirty) }, [isDirty, onDirtyChange])

  async function save(form: ClinicalForm) {
    setActionError('')
    setConflict(false)
    try {
      const updated = await onSave(formToClinical(form), version)
      setVersion(updated.version)
      reset(clinicalToForm(updated.data, template.fields))
      dirtyRef.current = false
      setSaved(true)
    } catch (error) { setConflict(error instanceof ApiError && error.status === 409); setActionError(error instanceof Error ? error.message : 'Не удалось сохранить изменения') }
  }
  async function approve() {
    setActionError('')
    try { await onApprove(version) }
    catch (error) { setConflict(error instanceof ApiError && error.status === 409); setActionError(error instanceof Error ? error.message : 'Не удалось подтвердить документ') }
  }
  async function reload() {
    if (isDirty && !window.confirm('Загрузить актуальную версию? Несохранённые правки будут потеряны.')) return
    try {
      const updated = await onReload()
      reset(clinicalToForm(updated.data, template.fields))
      dirtyRef.current = false
      setVersion(updated.version)
      setActionError('')
      setConflict(false)
      setSaved(false)
      onDirtyChange(false)
    } catch (error) { setActionError(error instanceof Error ? error.message : 'Не удалось обновить документ') }
  }

  const specialty = template.fields.filter(field => !field.clinical_field)
  const currentData = formToClinical(watch())
  const paths = sourcePaths(document.ai_generated_data)
  return <div className="document-editor"><div className="panel-heading"><div className="heading-icon"><FileText size={20} /></div><div><p className="eyebrow">Клинический документ</p><h2>{template.name}</h2></div><span className="version-chip">Версия {version}</span></div>
    <div className={`review-note ${editable ? '' : 'review-note-locked'}`}>{editable ? <AlertCircle size={17} /> : <ShieldCheck size={17} />}<span>{status === 'REVIEWED' ? 'Проверка сохранена. Подтвердите документ после финального просмотра.' : editable ? 'ИИ подготовил черновик. Проверьте каждое поле перед подтверждением.' : 'Документ подтверждён врачом. Поля доступны только для просмотра.'}</span></div>
    <form aria-label="Клинический документ" onSubmit={handleSubmit(save)} noValidate><fieldset disabled={!editable || busy || isSubmitting} className="form-fields">
      <TextList name="complaints" title="Жалобы" placeholder="Жалоба пациента" control={control} register={register} errors={errors} disabled={!editable || busy} />
      <div className="form-section space-y-4"><h3>Анамнез</h3><OptionalField label="История заболевания" initialValue={document.data.anamnesis_morbi} resetToken={version} editable={editable} disabled={busy}><Field label="История заболевания" name="anamnesis_morbi" register={register} multiline /></OptionalField><OptionalField label="Анамнез жизни" initialValue={document.data.anamnesis_vitae} resetToken={version} editable={editable} disabled={busy}><Field label="Анамнез жизни" name="anamnesis_vitae" register={register} multiline /></OptionalField></div>
      <TextList name="allergies" title="Аллергии" placeholder="Указанная аллергия" control={control} register={register} errors={errors} disabled={!editable || busy} />
      <MedicationList name="medications" title="Принимаемые препараты" control={control} register={register} errors={errors} disabled={!editable || busy} />
      <section className="form-section"><h3>Показатели</h3><div className="grid gap-3 sm:grid-cols-2">{vitalFields.map(([name, label]) => <OptionalField key={name} label={label} initialValue={document.data.vital_signs?.[name]} resetToken={version} editable={editable} disabled={busy}><label className="field-label">{label}<input {...register(`vital_signs.${name}`)} className="input" placeholder="Не указано" /></label></OptionalField>)}</div></section>
      <div className="form-section space-y-4"><h3>Осмотр и заключение</h3><OptionalField label="Объективный статус" initialValue={document.data.objective_status} resetToken={version} editable={editable} disabled={busy}><Field label="Объективный статус" name="objective_status" register={register} multiline /></OptionalField><OptionalField label="Диагноз" initialValue={document.data.diagnosis || document.data.diagnosis_code} resetToken={version} editable={editable} disabled={busy}><Field label="Диагноз" name="diagnosis" register={register} multiline hint="Только после проверки врачом" /><DiagnosisPicker value={watch('diagnosis_code')} onChange={code => setValue('diagnosis_code', code, { shouldDirty: true, shouldValidate: true })} disabled={!editable || busy || isSubmitting} /></OptionalField><input type="hidden" {...register('diagnosis_code')} /></div>
      <TextList name="recommendations" title="Рекомендации" placeholder="Рекомендация" control={control} register={register} errors={errors} disabled={!editable || busy} />
      <MedicationList name="prescribed_medications" title="Назначенные препараты" control={control} register={register} errors={errors} disabled={!editable || busy} />
      <div className="form-section"><OptionalField label="Дополнительные заметки" initialValue={document.data.additional_notes} resetToken={version} editable={editable} disabled={busy}><Field label="Дополнительные заметки" name="additional_notes" register={register} multiline /></OptionalField></div>
      {specialty.length > 0 && <section className="form-section specialty-section"><div className="specialty-intro"><h3>Поля выбранного бланка</h3><p>Заполняйте только сведения, прозвучавшие на приёме.</p></div>{specialty.map((field, index) => <div key={field.key}><input type="hidden" {...register(`template_fields.${index}.key`)} /><OptionalField label={field.label} initialValue={document.data.template_fields.find(item => item.key === field.key)?.value} resetToken={version} editable={editable} disabled={busy}><label className="field-label specialty-field">{field.label}<span className="specialty-section-name">{field.section}</span><span className="field-hint">{field.prompt}</span><textarea rows={2} className="input resize-y" aria-label={field.label} {...register(`template_fields.${index}.value`)} placeholder="Не указано" /></label></OptionalField></div>)}</section>}
    </fieldset>
    <section className="evidence-section" aria-label="Источники AI-версии"><h3>Источники AI-версии</h3><p>Фрагменты показывают происхождение AI-черновика, а не медицинскую достоверность.</p>
      {paths.length ? paths.map(path => <div className="evidence-field" key={path}><h4>{pathLabel(path, template)}</h4><SourceEvidence fieldPath={path} aiData={document.ai_generated_data} currentData={currentData} evidence={document.evidence} onSelect={onSourceSelect ?? (() => {})} /></div>) : <p>Источники для этой генерации не записаны.</p>}
    </section>
    {actionError && <div role="alert" className="action-error">{actionError}{conflict && <><span> Версия документа изменилась. Ваши правки остались в форме.</span><Button type="button" variant="secondary" size="sm" className="mt-2" onClick={reload}>Загрузить актуальную версию</Button></>}</div>}
    {editable && saved && !isDirty && <p className="saved-note"><Check size={15} /> Изменения сохранены. Теперь документ можно подтвердить.</p>}
    {editable && <div className="editor-actions"><Button type="submit" disabled={busy || isSubmitting} variant="secondary"><Save size={16} /> {isSubmitting ? 'Сохраняем…' : 'Сохранить проверку'}</Button><Button type="button" onClick={approve} disabled={!canApprove(status, isDirty, version) || busy || isSubmitting} title={isDirty ? 'Сначала сохраните изменения' : undefined}><CheckCheck size={17} /> Подтвердить</Button></div>}
    {editable && isDirty && <p className="unsaved-note">Есть несохранённые изменения. Сохраните их перед подтверждением.</p>}
    </form>
    <ProtocolPanel key={document.consultation_id} consultationId={document.consultation_id} data={currentData} />
  </div>
}
