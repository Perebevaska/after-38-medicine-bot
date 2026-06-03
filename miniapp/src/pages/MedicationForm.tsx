import { useState, useEffect } from 'react'
import {
  useMedications,
  useDependents,
  useCreateMedication,
  useUpdateMedication,
  useSettings,
} from '../api/hooks'
import type { MealRelation, Frequency, ScheduleRule, RuleIn } from '../api/types'
import TimePicker from '../components/TimePicker'
import { MEAL_OPTIONS } from '../constants'

// ─── helpers ─────────────────────────────────────────────────────────────────

// MF4: локальная дата, не UTC — иначе anchor_date для interval-правил смещается
// на дальних поясах (toISOString даёт UTC-день).
const todayStr = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const nowHHMM = () => {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const FREQ_OPTIONS: { value: Frequency; label: string }[] = [
  { value: 'daily', label: 'Ежедневно' },
  { value: 'interval', label: 'Каждые N дней' },
  { value: 'weekdays', label: 'По дням' },
  { value: 'monthly', label: 'Раз в месяц' },
]

const WEEKDAY_LABELS = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']

// ─── form state types ─────────────────────────────────────────────────────────

interface RuleState {
  reminder_time: string
  frequency: Frequency
  interval_days: number
  weekdays: number[]
  month_day: number
  anchor_date: string
  custom_dosage: string
}

interface FormState {
  name: string
  dosage: string
  meal_relation: MealRelation
  times_per_day: number
  dependent_id: number | null
  rules: RuleState[]
}

// ─── converters ──────────────────────────────────────────────────────────────

function defaultRule(): RuleState {
  return {
    reminder_time: nowHHMM(),
    frequency: 'daily',
    interval_days: 2,
    weekdays: [1, 2, 3, 4, 5],
    month_day: 1,
    anchor_date: todayStr(),
    custom_dosage: '',
  }
}

function ruleFromData(r: ScheduleRule): RuleState {
  return {
    reminder_time: r.reminder_time,
    frequency: r.frequency,
    interval_days: r.interval_days ?? 2,
    weekdays: r.weekdays ? r.weekdays.split(',').map(Number) : [1, 2, 3, 4, 5],
    month_day: r.month_day ?? 1,
    anchor_date: r.anchor_date ?? todayStr(),
    custom_dosage: r.dosage ?? '',
  }
}

function ruleToIn(r: RuleState): RuleIn {
  const base: RuleIn = {
    reminder_time: r.reminder_time,
    frequency: r.frequency,
    ...(r.custom_dosage.trim() ? { dosage: r.custom_dosage.trim() } : {}),
  }
  switch (r.frequency) {
    case 'interval':
      return { ...base, interval_days: r.interval_days, anchor_date: r.anchor_date }
    case 'weekdays':
      return { ...base, weekdays: [...r.weekdays].sort((a, b) => a - b).join(',') }
    case 'monthly':
      return { ...base, month_day: r.month_day }
    default:
      return base
  }
}

function syncRules(current: RuleState[], n: number): RuleState[] {
  if (n === current.length) return current
  if (n > current.length)
    return [...current, ...Array.from({ length: n - current.length }, () => defaultRule())]
  return current.slice(0, n)
}

// ─── validation ───────────────────────────────────────────────────────────────

type Errors = Record<string, string>

function validate(form: FormState): Errors {
  const errs: Errors = {}
  if (!form.name.trim()) errs.name = 'Введите название'
  const hasAnyDosage = form.dosage.trim() || form.rules.some((r) => r.custom_dosage.trim())
  if (!hasAnyDosage) errs.dosage = 'Введите дозировку или свою дозировку для каждого приёма'
  form.rules.forEach((r, i) => {
    if (!/^\d{2}:\d{2}$/.test(r.reminder_time)) {
      errs[`rule_${i}_time`] = 'Формат ЧЧ:ММ'
    }
    if (r.frequency === 'interval') {
      if (!r.interval_days || r.interval_days < 1)
        errs[`rule_${i}_interval`] = 'Кол-во дней > 0'
      if (!r.anchor_date)
        errs[`rule_${i}_anchor`] = 'Укажите дату начала'
    }
    if (r.frequency === 'weekdays' && r.weekdays.length === 0)
      errs[`rule_${i}_weekdays`] = 'Выберите хотя бы один день'
    if (r.frequency === 'monthly' && (!r.month_day || r.month_day < 1 || r.month_day > 31))
      errs[`rule_${i}_monthday`] = 'День 1–31'
  })
  return errs
}

// ─── RuleSection ─────────────────────────────────────────────────────────────

interface RuleSectionProps {
  rule: RuleState
  index: number
  errors: Errors
  onChange: (index: number, patch: Partial<RuleState>) => void
}

function RuleSection({ rule, index, errors, onChange }: RuleSectionProps) {
  const set = (patch: Partial<RuleState>) => onChange(index, patch)
  const [showDosage, setShowDosage] = useState(!!rule.custom_dosage)
  const [drumOpen, setDrumOpen] = useState(false)

  const toggleWeekday = (day: number) => {
    const days = rule.weekdays.includes(day)
      ? rule.weekdays.filter((d) => d !== day)
      : [...rule.weekdays, day]
    set({ weekdays: days })
  }

  return (
    <div className="rule-section">
      <div className="rule-label">Приём {index + 1}</div>

      <div className="form-field">
        <label className="field-label">Время</label>
        <span
          className={`settings-time-chip${drumOpen ? ' settings-time-chip--active' : ''}`}
          onClick={() => setDrumOpen((v) => !v)}
        >
          {rule.reminder_time}
          <span className="settings-time-chip-chevron">{drumOpen ? '‹' : '›'}</span>
        </span>
        {drumOpen && (
          <div className="plan-time-expand">
            <TimePicker value={rule.reminder_time} onChange={(v) => set({ reminder_time: v })} />
            <button type="button" className="plan-time-done-btn" onClick={() => setDrumOpen(false)}>Готово</button>
          </div>
        )}
        {errors[`rule_${index}_time`] && (
          <span className="field-error">{errors[`rule_${index}_time`]}</span>
        )}
      </div>

      <div className="form-field">
        <label className="field-label">Частота</label>
        <div className="seg-ctrl seg-ctrl--freq">
          {FREQ_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              className={`seg-btn${rule.frequency === o.value ? ' seg-btn--active' : ''}`}
              onClick={() => set({ frequency: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {rule.frequency === 'interval' && (
        <div className="freq-extra">
          <div className="form-field form-field--row">
            <label className="field-label">Каждые</label>
            <input
              type="number"
              className="field-input field-input--short"
              min={1}
              max={365}
              value={rule.interval_days}
              onChange={(e) => set({ interval_days: Math.max(1, +e.target.value) })}
            />
            <span className="field-unit">дней</span>
          </div>
          {errors[`rule_${index}_interval`] && (
            <span className="field-error">{errors[`rule_${index}_interval`]}</span>
          )}
          <div className="form-field">
            <label className="field-label">Начиная с</label>
            <input
              type="date"
              className="field-input"
              value={rule.anchor_date}
              onChange={(e) => set({ anchor_date: e.target.value })}
            />
            {errors[`rule_${index}_anchor`] && (
              <span className="field-error">{errors[`rule_${index}_anchor`]}</span>
            )}
          </div>
        </div>
      )}

      {rule.frequency === 'weekdays' && (
        <div className="form-field">
          <label className="field-label">Дни недели</label>
          <div className="weekdays-picker">
            {WEEKDAY_LABELS.map((label, i) => {
              const day = i + 1
              return (
                <button
                  key={day}
                  type="button"
                  className={`weekday-btn${rule.weekdays.includes(day) ? ' weekday-btn--active' : ''}`}
                  onClick={() => toggleWeekday(day)}
                >
                  {label}
                </button>
              )
            })}
          </div>
          {errors[`rule_${index}_weekdays`] && (
            <span className="field-error">{errors[`rule_${index}_weekdays`]}</span>
          )}
        </div>
      )}

      {rule.frequency === 'monthly' && (
        <div className="form-field form-field--row">
          <label className="field-label">Числа</label>
          <input
            type="number"
            className="field-input field-input--short"
            min={1}
            max={31}
            value={rule.month_day}
            onChange={(e) => set({ month_day: Math.min(31, Math.max(1, +e.target.value)) })}
          />
          <span className="field-unit">каждого месяца</span>
          {errors[`rule_${index}_monthday`] && (
            <span className="field-error">{errors[`rule_${index}_monthday`]}</span>
          )}
        </div>
      )}

      {showDosage ? (
        <div className="form-field">
          <div className="custom-dosage-header">
            <label className="field-label">Своя дозировка</label>
            <button
              type="button"
              className="custom-dosage-remove"
              onClick={() => { setShowDosage(false); set({ custom_dosage: '' }) }}
            >
              убрать
            </button>
          </div>
          <input
            type="text"
            className="field-input"
            placeholder="Например: 200 мг"
            value={rule.custom_dosage}
            onChange={(e) => set({ custom_dosage: e.target.value })}
          />
        </div>
      ) : (
        <button
          type="button"
          className="custom-dosage-toggle"
          onClick={() => setShowDosage(true)}
        >
          + своя дозировка для этого приёма
        </button>
      )}
    </div>
  )
}

// ─── MedicationForm ───────────────────────────────────────────────────────────

interface Props {
  editId?: number
  linkedUserId?: number  // F7: create/edit for linked dependent (their user_id)
  forDepShareId?: number // F8: create/edit for shared dep (share_id)
  onBack: () => void
}

export default function MedicationForm({ editId, linkedUserId, forDepShareId, onBack }: Props) {
  const { data: meds } = useMedications()
  const { data: deps } = useDependents()
  const { data: settings } = useSettings()
  const createMed = useCreateMedication()
  const updateMed = useUpdateMedication()

  // For linked dep edits, find the med from the combined list
  const existing = editId != null ? meds?.find((m) => m.id === editId) : undefined
  // F7-3.8: linked dependents available for "Для кого" dropdown
  const linkedDeps = settings?.active_dependents ?? []
  // F8: shared deps (помогаю №2) available for "Для кого" dropdown
  const viewingDeps = settings?.viewing_deps ?? []

  // Effective linkedUserId / depShareId: from prop, from existing med, or dropdown
  const [selectedLinkedUserId, setSelectedLinkedUserId] = useState<number | undefined>(
    linkedUserId ?? existing?.linked_user_id
  )
  const [selectedDepShareId, setSelectedDepShareId] = useState<number | undefined>(
    forDepShareId ?? existing?.dep_share_id
  )
  const effectiveLinkedUserId = selectedLinkedUserId
  const effectiveDepShareId = selectedDepShareId
  // Контекст зафиксирован (редактирование или открыто для конкретного получателя) —
  // прячем выбор «Для кого»; иначе (новое из «+») показываем полный список.
  const recipientLocked = editId != null || linkedUserId != null || forDepShareId != null
  const showRecipientPicker = !recipientLocked &&
    ((deps?.length ?? 0) > 0 || linkedDeps.length > 0 || viewingDeps.length > 0)

  const [form, setForm] = useState<FormState>(() => {
    if (existing) {
      return {
        name: existing.name,
        dosage: existing.dosage,
        meal_relation: existing.meal_relation,
        times_per_day: existing.times_per_day,
        dependent_id: existing.dependent_id,
        rules: existing.rules.map(ruleFromData),
      }
    }
    return {
      name: '',
      dosage: '',
      meal_relation: 'any',
      times_per_day: 1,
      dependent_id: null,
      rules: [defaultRule()],
    }
  })

  const [errors, setErrors] = useState<Errors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Re-initialize form when editing med loads after initial render
  useEffect(() => {
    if (existing && !form.name) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setForm({
        name: existing.name,
        dosage: existing.dosage,
        meal_relation: existing.meal_relation,
        times_per_day: existing.times_per_day,
        dependent_id: existing.dependent_id,
        rules: existing.rules.map(ruleFromData),
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing?.id])

  const setTimes = (n: number) =>
    setForm((f) => ({ ...f, times_per_day: n, rules: syncRules(f.rules, n) }))

  const patchRule = (index: number, patch: Partial<RuleState>) =>
    setForm((f) => ({
      ...f,
      rules: f.rules.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    }))

  const isPending = createMed.isPending || updateMed.isPending

  const handleSubmit = async () => {
    const errs = validate(form)
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    const body = {
      name: form.name.trim(),
      dosage: form.dosage.trim(),
      meal_relation: form.meal_relation,
      times_per_day: form.times_per_day,
      dependent_id: (effectiveLinkedUserId || effectiveDepShareId) ? null : form.dependent_id,
      for_linked_user_id: effectiveLinkedUserId ?? null,
      for_dep_share_id: effectiveDepShareId ?? null,
      rules: form.rules.map(ruleToIn),
    }

    try {
      if (editId != null) {
        await updateMed.mutateAsync({ id: editId, ...body })
      } else {
        await createMed.mutateAsync(body)
      }
      onBack()
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Ошибка сохранения')
    }
  }

  return (
    <div className="form-page">
      <div className="form-header">
        <button className="form-back-btn" onClick={onBack} type="button">
          ←
        </button>
        <h1 className="form-title">
          {editId != null
            ? (effectiveLinkedUserId || effectiveDepShareId) ? 'Редактировать (близкий)' : 'Редактировать'
            : (effectiveLinkedUserId || effectiveDepShareId) ? 'Добавить близкому' : 'Добавить в аптечку'}
        </h1>
      </div>

      <div className="form-body">
        {/* Единый выбор получателя: себе / локальный близкий / помогаю №1 / №2 */}
        {showRecipientPicker && (
          <div className="form-section">
            <label className="field-label">Для кого</label>
            <select
              className="field-select"
              value={
                effectiveLinkedUserId != null
                  ? `linked:${effectiveLinkedUserId}`
                  : effectiveDepShareId != null
                  ? `share:${effectiveDepShareId}`
                  : form.dependent_id != null
                  ? `dep:${form.dependent_id}`
                  : ''
              }
              onChange={(e) => {
                const v = e.target.value
                setForm((f) => ({ ...f, dependent_id: v.startsWith('dep:') ? +v.slice(4) : null }))
                setSelectedLinkedUserId(v.startsWith('linked:') ? +v.slice(7) : undefined)
                setSelectedDepShareId(v.startsWith('share:') ? +v.slice(6) : undefined)
              }}
            >
              <option value="">Себе</option>
              {deps?.map((d) => (
                <option key={`dep:${d.id}`} value={`dep:${d.id}`}>
                  {d.name}
                </option>
              ))}
              {linkedDeps.map((d) => (
                <option key={`linked:${d.dependent_user_id}`} value={`linked:${d.dependent_user_id}`}>
                  @{d.dependent_username ?? `id${d.dependent_telegram_id}`}
                </option>
              ))}
              {viewingDeps.map((vd) => (
                <option key={`share:${vd.share_id}`} value={`share:${vd.share_id}`}>
                  {vd.dep_name} · @{vd.owner_username}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Name */}
        <div className="form-section">
          <div className="form-field">
            <label className="field-label">Название</label>
            <input
              type="text"
              className={`field-input${errors.name ? ' field-input--error' : ''}`}
              placeholder="Например: Аспирин"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            {errors.name && <span className="field-error">{errors.name}</span>}
          </div>

          <div className="form-field">
            <label className="field-label">Дозировка</label>
            <input
              type="text"
              className={`field-input${errors.dosage ? ' field-input--error' : ''}`}
              placeholder="Например: 100 мг"
              value={form.dosage}
              onChange={(e) => setForm((f) => ({ ...f, dosage: e.target.value }))}
            />
            {errors.dosage && <span className="field-error">{errors.dosage}</span>}
          </div>
        </div>

        {/* Meal relation */}
        <div className="form-section">
          <label className="field-label">Как принимать</label>
          <div className="seg-ctrl">
            {MEAL_OPTIONS.map((o) => (
              <button
                key={o.value}
                type="button"
                className={`seg-btn${form.meal_relation === o.value ? ' seg-btn--active' : ''}`}
                onClick={() => setForm((f) => ({ ...f, meal_relation: o.value }))}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        {/* Times per day */}
        <div className="form-section">
          <label className="field-label">Приёмов в день</label>
          <div className="seg-ctrl">
            {[1, 2, 3, 4, 5, 6].map((n) => (
              <button
                key={n}
                type="button"
                className={`seg-btn${form.times_per_day === n ? ' seg-btn--active' : ''}`}
                onClick={() => setTimes(n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* Schedule rules */}
        {form.rules.map((rule, i) => (
          <div key={i} className="form-section">
            <RuleSection rule={rule} index={i} errors={errors} onChange={patchRule} />
          </div>
        ))}

        {submitError && <p className="submit-error">{submitError}</p>}

        <div className="form-section form-section--actions">
          <button
            type="button"
            className="btn-primary"
            onClick={handleSubmit}
            disabled={isPending}
          >
            {isPending ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
