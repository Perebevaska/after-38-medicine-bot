import { useState, useEffect } from 'react'
import {
  useMedications,
  useDependents,
  useCreateMedication,
  useUpdateMedication,
  useSettings,
} from '../api/hooks'
import type { MealRelation, Frequency, ScheduleRule, RuleIn } from '../api/types'
import TimePicker, { NumberDrum } from '../components/TimePicker'
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

// Единицы дозировки (та же единица у «дозировки 1 ед.» и у «назначено за приём»).
const DOSE_UNITS = ['мг', 'мкг', 'г', 'мл', 'ЕД', 'таб', 'капля', 'доза']

const fmtNum = (n: number) => (Number.isInteger(n) ? String(n) : String(Number(n.toFixed(3))))

// Старые лекарства хранят дозировку строкой ("100 мг"). Разбираем её на число+единицу,
// чтобы при редактировании не заставлять вводить заново.
function parseDosage(s: string): { value: string; label: string } {
  const m = (s || '').trim().match(/^([\d.,]+)\s*(.*)$/)
  if (!m) return { value: '', label: 'мг' }
  const unit = m[2].trim()
  return { value: m[1].replace(',', '.'), label: DOSE_UNITS.includes(unit) ? unit : 'мг' }
}

// ─── form state types ─────────────────────────────────────────────────────────

interface RuleState {
  reminder_time: string
  frequency: Frequency
  interval_days: number
  weekdays: number[]
  month_day: number
  anchor_date: string
  dosage: string  // своя доза приёма (число; '' = наследует общую)
}

interface FormState {
  name: string
  // упаковка
  unit_dose_value: string  // дозировка 1 ед. (500)
  unit_dose_label: string  // единица (мг)
  pack_size: number        // ед. в упаковке (10)
  // приём / курс
  dose_per_intake: string  // назначено за приём (250), та же единица
  course_total: string     // приёмов по назначению (опц.)
  per_dose: boolean        // разная доза по приёмам (своя dosage у каждого правила)
  meal_relation: MealRelation
  times_per_day: number
  rules: RuleState[]
  dependent_id: number | null
}

// ─── converters ──────────────────────────────────────────────────────────────

function defaultRule(time?: string): RuleState {
  return {
    reminder_time: time ?? nowHHMM(),
    frequency: 'daily',
    interval_days: 2,
    weekdays: [1, 2, 3, 4, 5],
    month_day: 1,
    anchor_date: todayStr(),
    dosage: '',
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
    dosage: r.dosage ? parseDosage(r.dosage).value : '',
  }
}

function ruleToIn(r: RuleState, perDose: boolean, unit: string): RuleIn {
  const base: RuleIn = { reminder_time: r.reminder_time, frequency: r.frequency }
  if (perDose && r.dosage.trim()) base.dosage = `${r.dosage.trim()} ${unit}`
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
  if (n > current.length) {
    // Стаггерим время новых приёмов (+1ч от последнего), иначе несколько приёмов
    // на одно время = дубль слота (backend отклонит).
    const lastH = parseInt((current[current.length - 1]?.reminder_time ?? nowHHMM()).slice(0, 2), 10)
    const add = Array.from({ length: n - current.length }, (_, i) => {
      const h = Math.min(23, (Number.isNaN(lastH) ? 8 : lastH) + i + 1)
      return defaultRule(`${String(h).padStart(2, '0')}:00`)
    })
    return [...current, ...add]
  }
  return current.slice(0, n)
}

function buildDosage(f: FormState): string {
  const unit = f.unit_dose_label
  if (f.dose_per_intake.trim()) return `${f.dose_per_intake.trim()} ${unit}`
  if (f.unit_dose_value.trim()) return `${f.unit_dose_value.trim()} ${unit}`
  return ''
}

// ─── validation ───────────────────────────────────────────────────────────────

type Errors = Record<string, string>

function validate(form: FormState, scheduleOn: boolean): Errors {
  const errs: Errors = {}
  if (!form.name.trim()) errs.name = 'Введите название'
  if (!form.unit_dose_value.trim()) errs.unit_dose_value = 'Укажите дозировку 1 ед.'
  if (scheduleOn) {
    form.rules.forEach((r, i) => {
      if (!/^\d{2}:\d{2}$/.test(r.reminder_time)) errs[`rule_${i}_time`] = 'Формат ЧЧ:ММ'
      if (r.frequency === 'interval') {
        if (!r.interval_days || r.interval_days < 1) errs[`rule_${i}_interval`] = 'Кол-во дней > 0'
        if (!r.anchor_date) errs[`rule_${i}_anchor`] = 'Укажите дату начала'
      }
      if (r.frequency === 'weekdays' && r.weekdays.length === 0)
        errs[`rule_${i}_weekdays`] = 'Выберите хотя бы один день'
      if (r.frequency === 'monthly' && (!r.month_day || r.month_day < 1 || r.month_day > 31))
        errs[`rule_${i}_monthday`] = 'День 1–31'
    })
    // Дубли приёмов (одинаковое время + частота) запрещены: схлопнутся в один слот.
    const seen = new Set<string>()
    form.rules.forEach((r, i) => {
      const key = `${r.reminder_time}|${r.frequency}`
      if (seen.has(key)) errs[`rule_${i}_time`] = 'Уже есть приём на это время — измените'
      seen.add(key)
    })
  }
  return errs
}

// ─── RuleSection ─────────────────────────────────────────────────────────────

interface RuleSectionProps {
  rule: RuleState
  index: number
  errors: Errors
  onChange: (index: number, patch: Partial<RuleState>) => void
  perDose: boolean
  unitLabel: string
}

function RuleSection({ rule, index, errors, onChange, perDose, unitLabel }: RuleSectionProps) {
  const set = (patch: Partial<RuleState>) => onChange(index, patch)
  const [drumOpen, setDrumOpen] = useState(false)

  const toggleWeekday = (day: number) => {
    const days = rule.weekdays.includes(day)
      ? rule.weekdays.filter((d) => d !== day)
      : [...rule.weekdays, day]
    set({ weekdays: days })
  }

  return (
    <div className="form-section rule-card">
      <div className="rule-card-head">
        <span className="rule-num">{index + 1}</span>
        <span
          className={`settings-time-chip rule-time-chip${drumOpen ? ' settings-time-chip--active' : ''}`}
          onClick={() => setDrumOpen((v) => !v)}
        >
          🕐 {rule.reminder_time}
          <span className="settings-time-chip-chevron">{drumOpen ? '‹' : '›'}</span>
        </span>
        {perDose && (
          <span className="rule-dose">
            <input
              type="number"
              inputMode="decimal"
              min="0"
              className="field-input rule-dose-input"
              placeholder="доза"
              value={rule.dosage}
              onChange={(e) => set({ dosage: e.target.value })}
            />
            <span className="field-unit">{unitLabel}</span>
          </span>
        )}
      </div>

      {drumOpen && (
        <div className="plan-time-expand">
          <TimePicker value={rule.reminder_time} onChange={(v) => set({ reminder_time: v })} />
          <button type="button" className="plan-time-done-btn" onClick={() => setDrumOpen(false)}>Готово</button>
        </div>
      )}
      {errors[`rule_${index}_time`] && (
        <span className="field-error">{errors[`rule_${index}_time`]}</span>
      )}

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
    </div>
  )
}

// ─── MedicationForm ───────────────────────────────────────────────────────────

interface Props {
  editId?: number
  linkedUserId?: number  // F7: create/edit for linked dependent (their user_id)
  forDepShareId?: number // F8: create/edit for shared dep (share_id)
  openSchedule?: boolean // открыть форму сразу на блоке расписания (из «+ расписание»)
  onBack: () => void
}

export default function MedicationForm({ editId, linkedUserId, forDepShareId, openSchedule, onBack }: Props) {
  const { data: meds } = useMedications()
  const { data: deps } = useDependents()
  const { data: settings } = useSettings()
  const createMed = useCreateMedication()
  const updateMed = useUpdateMedication()

  const existing = editId != null ? meds?.find((m) => m.id === editId) : undefined
  const linkedDeps = settings?.active_dependents ?? []
  const viewingDeps = settings?.viewing_deps ?? []

  const [selectedLinkedUserId, setSelectedLinkedUserId] = useState<number | undefined>(
    linkedUserId ?? existing?.linked_user_id
  )
  const [selectedDepShareId, setSelectedDepShareId] = useState<number | undefined>(
    forDepShareId ?? existing?.dep_share_id
  )
  const effectiveLinkedUserId = selectedLinkedUserId
  const effectiveDepShareId = selectedDepShareId
  const recipientLocked = editId != null || linkedUserId != null || forDepShareId != null
  const showRecipientPicker = !recipientLocked &&
    ((deps?.length ?? 0) > 0 || linkedDeps.length > 0 || viewingDeps.length > 0)

  const fromExisting = (m: NonNullable<typeof existing>): FormState => {
    const parsed = parseDosage(m.dosage)
    return {
    name: m.name,
    unit_dose_value: m.unit_dose_value != null ? fmtNum(m.unit_dose_value) : parsed.value,
    unit_dose_label: m.unit_dose_label || parsed.label,
    pack_size: m.stock_qty != null ? Math.round(m.stock_qty)
      : m.pack_size != null ? Math.round(m.pack_size) : 10,
    dose_per_intake: m.dose_per_intake != null ? fmtNum(m.dose_per_intake) : '',
    course_total: m.course_total != null ? String(m.course_total) : '',
    per_dose: m.rules.some((r) => !!r.dosage),
    meal_relation: m.meal_relation,
    times_per_day: m.times_per_day,
    rules: m.rules.length ? m.rules.map(ruleFromData) : [defaultRule()],
    dependent_id: m.dependent_id,
    }
  }

  const [form, setForm] = useState<FormState>(() =>
    existing ? fromExisting(existing) : {
      name: '',
      unit_dose_value: '',
      unit_dose_label: 'мг',
      pack_size: 10,
      dose_per_intake: '',
      course_total: '',
      per_dose: false,
      meal_relation: 'any',
      times_per_day: 1,
      rules: [defaultRule()],
      dependent_id: null,
    }
  )

  // Блок «Расписание»: при создании — свёрнут (сперва упаковка); при редактировании
  // открыт если у лекарства уже есть приёмы или пришли из «+ расписание».
  const [scheduleOn, setScheduleOn] = useState<boolean>(
    !!openSchedule || (editId != null && (existing?.rules.length ?? 0) > 0)
  )
  const [packDrumOpen, setPackDrumOpen] = useState(false)
  const [mealOpen, setMealOpen] = useState(false)
  const [timesOpen, setTimesOpen] = useState(false)
  const [errors, setErrors] = useState<Errors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [doseWarn, setDoseWarn] = useState(false)

  useEffect(() => {
    if (existing && !form.name) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setForm(fromExisting(existing))
      setScheduleOn(!!openSchedule || existing.rules.length > 0)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing?.id])

  const setTimes = (n: number) =>
    setForm((f) => ({ ...f, times_per_day: n, rules: syncRules(f.rules, n) }))

  const patchRule = (index: number, patch: Partial<RuleState>) =>
    setForm((f) => ({ ...f, rules: f.rules.map((r, i) => (i === index ? { ...r, ...patch } : r)) }))

  const isPending = createMed.isPending || updateMed.isPending

  // Авторасчёт списания: назначено / дозировка 1 ед.
  const udv = parseFloat(form.unit_dose_value)
  const dpi = parseFloat(form.dose_per_intake)
  const unitsPerDose = udv > 0 && dpi > 0 ? dpi / udv : null

  const handleSubmit = async () => {
    const errs = validate(form, scheduleOn)
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    const body = {
      name: form.name.trim(),
      dosage: buildDosage(form),
      meal_relation: form.meal_relation,
      times_per_day: form.times_per_day,
      dependent_id: (effectiveLinkedUserId || effectiveDepShareId) ? null : form.dependent_id,
      for_linked_user_id: effectiveLinkedUserId ?? null,
      for_dep_share_id: effectiveDepShareId ?? null,
      unit_dose_value: udv > 0 ? udv : null,
      unit_dose_label: form.unit_dose_label,
      dose_per_intake: dpi > 0 ? dpi : null,
      pack_size: form.pack_size,
      course_total: form.course_total.trim() ? parseInt(form.course_total, 10) : null,
      rules: scheduleOn ? form.rules.map((r) => ruleToIn(r, form.per_dose, form.unit_dose_label)) : [],
    }

    try {
      if (editId != null) await updateMed.mutateAsync({ id: editId, ...body })
      else await createMed.mutateAsync(body)
      onBack()
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Ошибка сохранения')
    }
  }

  return (
    <div className="form-page">
      <div className="form-header">
        <button className="form-back-btn" onClick={onBack} type="button">←</button>
        <h1 className="form-title">
          {editId != null ? 'Препарат' : 'Новый препарат'}
        </h1>
      </div>

      <div className="form-body">
        {showRecipientPicker && (
          <div className="form-section">
            <label className="field-label">Для кого</label>
            <select
              className="field-select"
              value={
                effectiveLinkedUserId != null ? `linked:${effectiveLinkedUserId}`
                : effectiveDepShareId != null ? `share:${effectiveDepShareId}`
                : form.dependent_id != null ? `dep:${form.dependent_id}` : ''
              }
              onChange={(e) => {
                const v = e.target.value
                setForm((f) => ({ ...f, dependent_id: v.startsWith('dep:') ? +v.slice(4) : null }))
                setSelectedLinkedUserId(v.startsWith('linked:') ? +v.slice(7) : undefined)
                setSelectedDepShareId(v.startsWith('share:') ? +v.slice(6) : undefined)
              }}
            >
              <option value="">Себе</option>
              {deps?.map((d) => (<option key={`dep:${d.id}`} value={`dep:${d.id}`}>{d.name}</option>))}
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

        {/* ── Упаковка ── */}
        <div className="form-section">
          <div className="form-section-head">📦 Упаковка</div>

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

          <div className="form-grid2">
            <div className="form-field">
              <label className="field-label">Дозировка 1 ед.</label>
              <div className="dose-row">
                <input
                  type="number"
                  inputMode="decimal"
                  min="0"
                  className={`field-input field-input--short${errors.unit_dose_value ? ' field-input--error' : ''}`}
                  placeholder="500"
                  value={form.unit_dose_value}
                  onChange={(e) => {
                    const v = e.target.value
                    setForm((f) => ({ ...f, unit_dose_value: v }))
                    if (editId != null && existing?.unit_dose_value != null &&
                        v !== fmtNum(existing.unit_dose_value)) setDoseWarn(true)
                  }}
                />
                <select
                  className="field-select field-select--unit"
                  value={form.unit_dose_label}
                  onChange={(e) => setForm((f) => ({ ...f, unit_dose_label: e.target.value }))}
                >
                  {DOSE_UNITS.map((u) => (<option key={u} value={u}>{u}</option>))}
                </select>
              </div>
              {errors.unit_dose_value && <span className="field-error">{errors.unit_dose_value}</span>}
              <span className="field-hint">Вещества в одной таблетке/капсуле.</span>
            </div>

            <div className="form-field">
              <label className="field-label">Ед. в упаковке</label>
              <span
                className={`settings-time-chip${packDrumOpen ? ' settings-time-chip--active' : ''}`}
                onClick={() => setPackDrumOpen((v) => !v)}
              >
                {form.pack_size} шт.
                <span className="settings-time-chip-chevron">{packDrumOpen ? '‹' : '›'}</span>
              </span>
              <span className="field-hint">
                {editId == null ? 'Это и есть запас.' : 'Текущий запас. Докупили — поднимите.'}
              </span>
            </div>
          </div>

          {packDrumOpen && (
            <div className="plan-time-expand">
              <NumberDrum value={form.pack_size} min={1} max={240}
                onChange={(v) => setForm((f) => ({ ...f, pack_size: v }))} />
              <button type="button" className="plan-time-done-btn" onClick={() => setPackDrumOpen(false)}>Готово</button>
            </div>
          )}
          {doseWarn && (
            <span className="field-warn">
              ⚠️ Купили упаковку с другой дозировкой? Лучше создайте новый препарат — так история и запас не смешаются.
            </span>
          )}
        </div>

        {/* ── Расписание приёма / курс ── */}
        {scheduleOn ? (
          <>
            <div className="form-section">
              <div className="form-section-head">💊 Приём и курс</div>

              <div className="form-grid2">
                <div className="form-field">
                  <label className="field-label">Назначено за приём</label>
                  <div className="dose-row">
                    <input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      className="field-input field-input--short"
                      placeholder={form.unit_dose_value || '250'}
                      value={form.dose_per_intake}
                      onChange={(e) => setForm((f) => ({ ...f, dose_per_intake: e.target.value }))}
                    />
                    <span className="field-unit">{form.unit_dose_label}</span>
                  </div>
                  {unitsPerDose != null ? (
                    <span className="field-hint">
                      ≈ {fmtNum(unitsPerDose)} ед.
                      {unitsPerDose === 0.5 ? ' (½)' : unitsPerDose === 0.25 ? ' (¼)' : ''} · списывается
                    </span>
                  ) : (
                    <span className="field-hint">Пусто = 1 ед. целиком.</span>
                  )}
                </div>

                <div className="form-field">
                  <label className="field-label">Курс — приёмов</label>
                  <div className="dose-row">
                    <input
                      type="number"
                      inputMode="numeric"
                      min="1"
                      className="field-input field-input--short"
                      placeholder="∞"
                      value={form.course_total}
                      onChange={(e) => setForm((f) => ({ ...f, course_total: e.target.value }))}
                    />
                    <span className="field-unit">раз</span>
                  </div>
                  <span className="field-hint">Всего по назначению. Пусто = бессрочно.</span>
                </div>
              </div>

              <label className="form-switch-row">
                <span className="form-switch-label">Разная доза по приёмам</span>
                <input
                  type="checkbox"
                  className="form-switch"
                  checked={form.per_dose}
                  onChange={(e) => setForm((f) => ({ ...f, per_dose: e.target.checked }))}
                />
              </label>
              {form.per_dose && (
                <span className="field-hint">У каждого приёма своя доза ниже. Пусто в приёме = общая.</span>
              )}
            </div>

            <div className="form-section">
              <div className="form-grid2">
                <div className="form-field">
                  <label className="field-label">Как принимать</label>
                  <span
                    className={`settings-time-chip${mealOpen ? ' settings-time-chip--active' : ''}`}
                    onClick={() => { setMealOpen((v) => !v); setTimesOpen(false) }}
                  >
                    {MEAL_OPTIONS.find((o) => o.value === form.meal_relation)?.label ?? form.meal_relation}
                    <span className="settings-time-chip-chevron">{mealOpen ? '‹' : '›'}</span>
                  </span>
                </div>
                <div className="form-field">
                  <label className="field-label">Приёмов в день</label>
                  <span
                    className={`settings-time-chip${timesOpen ? ' settings-time-chip--active' : ''}`}
                    onClick={() => { setTimesOpen((v) => !v); setMealOpen(false) }}
                  >
                    {form.times_per_day} {form.times_per_day === 1 ? 'раз' : 'раза'}
                    <span className="settings-time-chip-chevron">{timesOpen ? '‹' : '›'}</span>
                  </span>
                </div>
              </div>

              {mealOpen && (
                <div className="plan-time-expand">
                  <div className="seg-ctrl">
                    {MEAL_OPTIONS.map((o) => (
                      <button key={o.value} type="button"
                        className={`seg-btn${form.meal_relation === o.value ? ' seg-btn--active' : ''}`}
                        onClick={() => { setForm((f) => ({ ...f, meal_relation: o.value })); setMealOpen(false) }}
                      >{o.label}</button>
                    ))}
                  </div>
                </div>
              )}
              {timesOpen && (
                <div className="plan-time-expand">
                  <NumberDrum value={form.times_per_day} min={1} max={10} onChange={setTimes} />
                  <button type="button" className="plan-time-done-btn" onClick={() => setTimesOpen(false)}>Готово</button>
                </div>
              )}
            </div>

            {form.rules.map((rule, i) => (
              <RuleSection key={i} rule={rule} index={i} errors={errors} onChange={patchRule}
                perDose={form.per_dose} unitLabel={form.unit_dose_label} />
            ))}

            <button type="button" className="schedule-remove-btn" onClick={() => setScheduleOn(false)}>
              🗑 Удалить расписание
            </button>
            <span className="field-hint">Препарат останется без напоминаний. Расписание можно добавить снова.</span>
          </>
        ) : (
          <div className="form-section">
            <button type="button" className="schedule-add-toggle" onClick={() => setScheduleOn(true)}>
              📅 Добавить расписание приёма
            </button>
            <span className="field-hint">Можно сохранить и без расписания — напоминания добавите позже.</span>
          </div>
        )}

        {submitError && <p className="submit-error">{submitError}</p>}

        <div className="form-section form-section--actions">
          <button type="button" className="btn-primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? 'Сохранение…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
