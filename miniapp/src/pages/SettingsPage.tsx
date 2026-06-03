import { useState, useEffect, useMemo, useRef } from 'react'
import {
  useSettings, useSetReminderMode, useSetDailyPlan, useSetCaregiver,
  useDependents, useCreateDependent, useDeleteDependent,
  useSetTimezone, useSetTimezoneByLocation, useDeleteAccount, useSetStrictMode,
  useAdminStats, useRequestCaregiverLink, useConfirmCaregiverLink,
  useDeclineCaregiverLink, useDeleteCaregiverLink, useRequestLinkBreak,
  useSetDependentReminderMode, useSetDependentStrictMode,
} from '../api/hooks'

// ─── DrumPicker ───────────────────────────────────────────────────────────────
const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'))
const DRUM_ITEM_H = 44
const DRUM_PAD = 1

function DrumColumn({ items, value, onChange }: {
  items: string[]; value: string; onChange: (v: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const fromScroll = useRef(false)
  const [selIdx, setSelIdx] = useState(() => Math.max(0, items.indexOf(value)))

  useEffect(() => {
    if (fromScroll.current) { fromScroll.current = false; return }
    const idx = items.indexOf(value)
    if (idx < 0) return
    setSelIdx(idx)
    const el = ref.current
    if (!el) return
    const id = setTimeout(() => { el.scrollTop = idx * DRUM_ITEM_H }, 0)
    return () => clearTimeout(id)
  }, [value, items])

  const handleScroll = () => {
    if (!ref.current) return
    const idx = Math.max(0, Math.min(items.length - 1, Math.round(ref.current.scrollTop / DRUM_ITEM_H)))
    setSelIdx(idx)
    if (items[idx] !== value) { fromScroll.current = true; onChange(items[idx]) }
  }

  return (
    <div className="drum-col">
      <div className="drum-col-fade drum-col-fade--top" />
      <div className="drum-col-fade drum-col-fade--bot" />
      <div className="drum-col-line drum-col-line--top" />
      <div className="drum-col-line drum-col-line--bot" />
      <div className="drum-col-scroll" ref={ref} onScroll={handleScroll}>
        {Array.from({ length: DRUM_PAD }, (_, i) => <div key={`pre${i}`} className="drum-col-item" />)}
        {items.map((item, i) => (
          <div key={item} className={`drum-col-item${i === selIdx ? ' drum-col-item--sel' : ''}`}>{item}</div>
        ))}
        {Array.from({ length: DRUM_PAD }, (_, i) => <div key={`post${i}`} className="drum-col-item" />)}
      </div>
    </div>
  )
}

function TimePicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [hh, mm] = value.split(':')
  return (
    <div className="drum-picker">
      <DrumColumn items={HOURS} value={hh ?? '08'} onChange={(h) => onChange(`${h}:${mm ?? '00'}`)} />
      <span className="drum-sep">:</span>
      <DrumColumn items={MINUTES} value={mm ?? '00'} onChange={(m) => onChange(`${hh ?? '08'}:${m}`)} />
    </div>
  )
}

function InfoTip({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])
  return (
    <span ref={ref} className="info-tip" onClick={() => setOpen(v => !v)}>
      ⓘ
      {open && <span className="info-tip-popup">{text}</span>}
    </span>
  )
}

const METRIC_HINTS: Record<string, string> = {
  'PostgreSQL': 'Проверяет: SELECT 1. Ловит: сервер недоступен, ошибка соединения, пул исчерпан.',
  'Redis': 'Проверяет: PING. Ловит: Redis не запущен, неверный URL, сеть недоступна.',
  'CPU': 'cpu_percent за 0.2с + load average за 1 мин (число процессов в очереди на CPU).',
  'RAM': 'Физическая память: занято / всего. >85% — предупреждение.',
  'SWAP': 'Раздел подкачки. Активный SWAP = RAM не хватает. >50% — предупреждение.',
  'Disk': 'Корневой раздел /. Свободно / всего. >85% — предупреждение.',
  'Redis память': 'used_memory из Redis INFO — сколько RAM занимают данные в Redis (ключи rate-limit, scheduler state, ARQ очередь).',
  'Redis клиентов': 'connected_clients из Redis INFO — активные соединения к Redis.',
  'ARQ очередь': 'Длина очереди arq:queue:default. Рост означает затор отправки Telegram-сообщений (429 или worker упал).',
  'DB pool': 'psycopg_pool: свободных / всего соединений. Ожидают > 0 — запросы стоят в очереди.',
  'Bot': 'systemctl is-active medbot-bot — процесс бота (APScheduler + handlers).',
  'API': 'systemctl is-active medbot-api — FastAPI / uvicorn (Mini App backend).',
  'Worker': 'systemctl is-active medbot-worker — ARQ worker (отправка Telegram-сообщений из очереди).',
  'Caddy': 'systemctl is-active caddy — reverse proxy (HTTPS, /api → FastAPI, / → Mini App dist).',
}

const TIMEZONES: { value: string; label: string }[] = [
  { value: 'Europe/Kaliningrad', label: 'Калининград UTC+2' },
  { value: 'Europe/Moscow', label: 'Москва, Петербург UTC+3' },
  { value: 'Europe/Samara', label: 'Самара, Ижевск UTC+4' },
  { value: 'Asia/Yekaterinburg', label: 'Екатеринбург UTC+5' },
  { value: 'Asia/Omsk', label: 'Омск UTC+6' },
  { value: 'Asia/Krasnoyarsk', label: 'Красноярск UTC+7' },
  { value: 'Asia/Irkutsk', label: 'Иркутск UTC+8' },
  { value: 'Asia/Yakutsk', label: 'Якутск UTC+9' },
  { value: 'Asia/Vladivostok', label: 'Владивосток UTC+10' },
  { value: 'Asia/Magadan', label: 'Магадан UTC+11' },
  { value: 'Asia/Kamchatka', label: 'Камчатка UTC+12' },
  { value: 'Europe/Minsk', label: 'Минск UTC+3' },
  { value: 'Europe/Kyiv', label: 'Киев UTC+2/3' },
  { value: 'Asia/Almaty', label: 'Алматы UTC+5' },
  { value: 'Asia/Tashkent', label: 'Ташкент UTC+5' },
  { value: 'Asia/Bishkek', label: 'Бишкек UTC+6' },
  { value: 'Asia/Tbilisi', label: 'Тбилиси UTC+4' },
  { value: 'Asia/Yerevan', label: 'Ереван UTC+4' },
  { value: 'Asia/Baku', label: 'Баку UTC+4' },
  { value: 'Europe/London', label: 'Лондон UTC+0/1' },
  { value: 'Europe/Paris', label: 'Париж, Берлин UTC+1/2' },
  { value: 'Europe/Helsinki', label: 'Хельсинки UTC+2/3' },
  { value: 'Europe/Istanbul', label: 'Стамбул UTC+3' },
  { value: 'Asia/Dubai', label: 'Дубай UTC+4' },
  { value: 'Asia/Karachi', label: 'Пакистан UTC+5' },
  { value: 'Asia/Kolkata', label: 'Индия UTC+5:30' },
  { value: 'Asia/Bangkok', label: 'Бангкок UTC+7' },
  { value: 'Asia/Singapore', label: 'Сингапур UTC+8' },
  { value: 'Asia/Shanghai', label: 'Китай UTC+8' },
  { value: 'Asia/Tokyo', label: 'Токио UTC+9' },
  { value: 'America/New_York', label: 'Нью-Йорк UTC-5/-4' },
  { value: 'America/Chicago', label: 'Чикаго UTC-6/-5' },
  { value: 'America/Los_Angeles', label: 'Лос-Анджелес UTC-8/-7' },
  { value: 'America/Sao_Paulo', label: 'Сан-Паулу UTC-3' },
  { value: 'Australia/Sydney', label: 'Сидней UTC+10/11' },
]

export default function SettingsPage() {
  const { data, isLoading } = useSettings()
  const setMode = useSetReminderMode()
  const setDailyPlan = useSetDailyPlan()
  const setCaregiver = useSetCaregiver()
  const setStrict = useSetStrictMode()

  const { data: deps } = useDependents()
  const createDep = useCreateDependent()
  const deleteDep = useDeleteDependent()

  const setTz = useSetTimezone()
  const setTzByLocation = useSetTimezoneByLocation()

  const deleteAccount = useDeleteAccount()
  const { data: adminStats, refetch: refetchAdmin } = useAdminStats(!!data?.is_admin)
  const [dailyPlanTime, setDailyPlanTime] = useState('08:00')
  const [planTimeEditing, setPlanTimeEditing] = useState(false)
  const [strictTime, setStrictTime] = useState('02:00')
  const [strictTimeOpen, setStrictTimeOpen] = useState(false)
  const [repeatTime, setRepeatTime] = useState('02:00')
  const [repeatTimeOpen, setRepeatTimeOpen] = useState(false)
  const [newDepInput, setNewDepInput] = useState('')
  const [depInputError, setDepInputError] = useState('')
  const [caregiverOffConfirm, setCaregiverOffConfirm] = useState(false)
  const [tzEditing, setTzEditing] = useState(false)
  const [tzSearch, setTzSearch] = useState('')
  const [geoError, setGeoError] = useState('')
  const [confirmDeleteAccount, setConfirmDeleteAccount] = useState(false)
  const [deleteBlockedByCaregiver, setDeleteBlockedByCaregiver] = useState(false)
  const [deleted, setDeleted] = useState(false)

  const setDepRepeatMode = useSetDependentReminderMode()
  const setDepStrictMode = useSetDependentStrictMode()
  const [depRepeatTimes, setDepRepeatTimes] = useState<Record<number, string>>({})
  const [depStrictTimes, setDepStrictTimes] = useState<Record<number, string>>({})
  const [depRepeatOpen, setDepRepeatOpen] = useState<Record<number, boolean>>({})
  const [depStrictOpen, setDepStrictOpen] = useState<Record<number, boolean>>({})
  const dpTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // F7: caregiver links
  const requestLink = useRequestCaregiverLink()
  const confirmLink = useConfirmCaregiverLink()
  const declineLink = useDeclineCaregiverLink()
  const requestBreak = useRequestLinkBreak()
  const deleteLink = useDeleteCaregiverLink()
  const [codeCopied, setCodeCopied] = useState(false)
  const [detachConfirmId, setDetachConfirmId] = useState<number | null>(null)

  const handleCopyCode = () => {
    if (!data?.caregiver_code) return
    const code = data.caregiver_code
    navigator.clipboard.writeText(code).catch(() => {})
    setCodeCopied(true)
    setTimeout(() => setCodeCopied(false), 2000)
    try {
      const tg = (window as any).Telegram?.WebApp
      tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(code)}&text=${encodeURIComponent('Мой код для подключения помощника: ' + code)}`)
    } catch {}
  }

  const handleAddDepOrLink = () => {
    const val = newDepInput.trim()
    if (!val) return
    setDepInputError('')
    if (/^[A-Z0-9]{4}-[A-Z0-9]{4}$/i.test(val)) {
      requestLink.mutate(val.toUpperCase(), {
        onSuccess: () => setNewDepInput(''),
        onError: (e) => setDepInputError((e as any).message),
      })
    } else {
      createDep.mutate(val, {
        onSuccess: () => setNewDepInput(''),
        onError: (e) => setDepInputError((e as any).message),
      })
    }
  }

  const filteredZones = useMemo(() => {
    const q = tzSearch.toLowerCase()
    if (!q) return TIMEZONES
    return TIMEZONES.filter(
      (z) => z.label.toLowerCase().includes(q) || z.value.toLowerCase().includes(q)
    )
  }, [tzSearch])

  const handleSelectTz = (tz: string) => {
    setTz.mutate(tz, { onSuccess: () => { setTzEditing(false); setTzSearch('') } })
  }

  const handleGeolocate = () => {
    setGeoError('')
    if (!navigator.geolocation) {
      setGeoError('Геолокация не поддерживается браузером')
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setTzByLocation.mutate(
          { lat: pos.coords.latitude, lng: pos.coords.longitude },
          {
            onSuccess: () => { setTzEditing(false); setTzSearch('') },
            onError: () => setGeoError('Не удалось определить часовой пояс'),
          }
        )
      },
      () => setGeoError('Нет доступа к геолокации')
    )
  }

  const toTime = (h: number, m: number) =>
    `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  const parseTime = (t: string) => {
    const [hh, mm] = t.split(':').map(Number)
    return { hours: hh || 0, minutes: mm || 0 }
  }

  useEffect(() => {
    if (!data) return
    setDailyPlanTime(data.daily_plan_time ?? '08:00')
    setStrictTime(toTime(data.strict_mode_hours ?? 2, data.strict_mode_minutes ?? 0))
    setRepeatTime(toTime(data.reminder_repeat_hours ?? 2, data.reminder_repeat_minutes ?? 0))
    const rt: Record<number, string> = {}
    const st: Record<number, string> = {}
    data.active_dependents?.forEach((dep) => {
      rt[dep.id] = toTime(dep.reminder_repeat_hours ?? 2, dep.reminder_repeat_minutes ?? 0)
      st[dep.id] = toTime(dep.strict_mode_hours ?? 2, dep.strict_mode_minutes ?? 0)
    })
    setDepRepeatTimes(rt)
    setDepStrictTimes(st)
  }, [data])

  if (isLoading) return <div className="page"><p className="hint">Загрузка…</p></div>
  if (!data) return <div className="page"><p className="hint">Нет данных</p></div>

  const handleDailyPlanTimeChange = (v: string) => {
    setDailyPlanTime(v)
    if (dpTimerRef.current) clearTimeout(dpTimerRef.current)
    dpTimerRef.current = setTimeout(() => {
      setDailyPlan.mutate({ enabled: !!data.daily_plan_enabled, time: v })
    }, 700)
  }

  // F7-3.1: подопечный не может менять повтор и строгий режим
  const isDependent = !!data.active_caregiver

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Настройки</span>
      </div>

      <h2 className="section-title">Напоминания</h2>
      <p className="section-hint">
        Если включён повтор — бот будет напоминать каждые 5 минут, пока не отметишь приём или не истечёт заданное время.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Повтор напоминаний</span>
          <label className={`toggle-switch${isDependent ? ' toggle-switch--locked' : ''}`}>
            <input
              type="checkbox"
              checked={data.reminder_mode === 'repeat'}
              disabled={isDependent}
              onChange={(e) => {
                const { hours, minutes } = parseTime(repeatTime)
                setMode.mutate({ mode: e.target.checked ? 'repeat' : 'once', hours, minutes })
              }}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {data.reminder_mode === 'repeat' && (
          <>
            <div
              className={`settings-row${!isDependent ? ' settings-row--tappable' : ''}`}
              onClick={!isDependent ? () => setRepeatTimeOpen((v) => !v) : undefined}
            >
              <span className="settings-label">Повторять до</span>
              {isDependent ? (
                <span className="settings-locked-row-right">
                  <span className="settings-time-chip settings-time-chip--locked">{repeatTime}</span>
                  <span className="caregiver-locked-hint">управляется помощником</span>
                </span>
              ) : (
                <span className={`settings-time-chip${repeatTimeOpen ? ' settings-time-chip--active' : ''}`}>
                  {repeatTime}
                  <span className="settings-time-chip-chevron">{repeatTimeOpen ? '‹' : '›'}</span>
                </span>
              )}
            </div>
            {!isDependent && repeatTimeOpen && (
              <div className="plan-time-expand">
                <TimePicker
                  value={repeatTime}
                  onChange={(v) => {
                    setRepeatTime(v)
                    const { hours, minutes } = parseTime(v)
                    setMode.mutate({ mode: 'repeat', hours, minutes })
                  }}
                />
                <button className="plan-time-done-btn" onClick={() => setRepeatTimeOpen(false)}>Готово</button>
              </div>
            )}
          </>
        )}
        {!isDependent && data.active_dependents?.map((dep) => (
          <div key={dep.id}>
            <div className="settings-row settings-caregiver-dep-setting">
              <span className="settings-label">Близкий</span>
              <span
                className={`settings-time-chip${depRepeatOpen[dep.id] ? ' settings-time-chip--active' : ''}`}
                onClick={() => setDepRepeatOpen((p) => ({ ...p, [dep.id]: !p[dep.id] }))}
              >
                {depRepeatTimes[dep.id] ?? '02:00'}
                <span className="settings-time-chip-chevron">{depRepeatOpen[dep.id] ? '‹' : '›'}</span>
              </span>
            </div>
            {depRepeatOpen[dep.id] && (
              <div className="plan-time-expand">
                <TimePicker
                  value={depRepeatTimes[dep.id] ?? '02:00'}
                  onChange={(v) => {
                    setDepRepeatTimes((p) => ({ ...p, [dep.id]: v }))
                    const { hours, minutes } = parseTime(v)
                    setDepRepeatMode.mutate({ link_id: dep.id, mode: 'repeat', hours, minutes })
                  }}
                />
                <button className="plan-time-done-btn" onClick={() => setDepRepeatOpen((p) => ({ ...p, [dep.id]: false }))}>Готово</button>
              </div>
            )}
          </div>
        ))}
      </div>

      <h2 className="section-title">Ежедневный план</h2>
      <p className="section-hint">
        Каждое утро бот будет присылать список всех запланированных на сегодня приёмов.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Включён</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.daily_plan_enabled}
              onChange={(e) => setDailyPlan.mutate({ enabled: e.target.checked, time: dailyPlanTime })}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {!!data.daily_plan_enabled && (
          <>
            <div className="settings-row settings-row--tappable" onClick={() => setPlanTimeEditing((v) => !v)}>
              <span className="settings-label">Время отправки</span>
              <span className={`settings-time-chip${planTimeEditing ? ' settings-time-chip--active' : ''}`}>
                {dailyPlanTime}
                <span className="settings-time-chip-chevron">{planTimeEditing ? '‹' : '›'}</span>
              </span>
            </div>
            {planTimeEditing && (
              <div className="plan-time-expand">
                <TimePicker value={dailyPlanTime} onChange={handleDailyPlanTimeChange} />
                <button className="plan-time-done-btn" onClick={() => setPlanTimeEditing(false)}>Готово</button>
              </div>
            )}
          </>
        )}
      </div>

      <h2 className="section-title">Без пропусков</h2>
      <p className="section-hint">
        Если не отметить приём за заданное число часов после времени — он
        автоматически считается пропущенным и снимается ❤️.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Включён</span>
          <label className={`toggle-switch${isDependent ? ' toggle-switch--locked' : ''}`}>
            <input
              type="checkbox"
              checked={!!data.strict_mode}
              disabled={isDependent}
              onChange={(e) => {
                const { hours, minutes } = parseTime(strictTime)
                setStrict.mutate({ enabled: e.target.checked, hours, minutes })
              }}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {!!data.strict_mode && (
          <>
            <div
              className={`settings-row${!isDependent ? ' settings-row--tappable' : ''}`}
              onClick={!isDependent ? () => setStrictTimeOpen((v) => !v) : undefined}
            >
              <span className="settings-label">Через сколько</span>
              {isDependent ? (
                <span className="settings-locked-row-right">
                  <span className="settings-time-chip settings-time-chip--locked">{strictTime}</span>
                  <span className="caregiver-locked-hint">управляется помощником</span>
                </span>
              ) : (
                <span className={`settings-time-chip${strictTimeOpen ? ' settings-time-chip--active' : ''}`}>
                  {strictTime}
                  <span className="settings-time-chip-chevron">{strictTimeOpen ? '‹' : '›'}</span>
                </span>
              )}
            </div>
            {!isDependent && strictTimeOpen && (
              <div className="plan-time-expand">
                <TimePicker
                  value={strictTime}
                  onChange={(v) => {
                    setStrictTime(v)
                    const { hours, minutes } = parseTime(v)
                    setStrict.mutate({ enabled: true, hours, minutes })
                  }}
                />
                <button className="plan-time-done-btn" onClick={() => setStrictTimeOpen(false)}>Готово</button>
              </div>
            )}
          </>
        )}
        {!isDependent && data.active_dependents?.map((dep) => (
          <div key={dep.id}>
            <div className="settings-row settings-caregiver-dep-setting">
              <span className="settings-label">Близкий</span>
              <span
                className={`settings-time-chip${depStrictOpen[dep.id] ? ' settings-time-chip--active' : ''}`}
                onClick={() => setDepStrictOpen((p) => ({ ...p, [dep.id]: !p[dep.id] }))}
              >
                {depStrictTimes[dep.id] ?? '02:00'}
                <span className="settings-time-chip-chevron">{depStrictOpen[dep.id] ? '‹' : '›'}</span>
              </span>
            </div>
            {depStrictOpen[dep.id] && (
              <div className="plan-time-expand">
                <TimePicker
                  value={depStrictTimes[dep.id] ?? '02:00'}
                  onChange={(v) => {
                    setDepStrictTimes((p) => ({ ...p, [dep.id]: v }))
                    const { hours, minutes } = parseTime(v)
                    setDepStrictMode.mutate({ link_id: dep.id, enabled: true, hours, minutes })
                  }}
                />
                <button className="plan-time-done-btn" onClick={() => setDepStrictOpen((p) => ({ ...p, [dep.id]: false }))}>Готово</button>
              </div>
            )}
          </div>
        ))}
      </div>

      <h2 className="section-title">Забота</h2>
      <p className="section-hint">
        Позволяет близкому человеку следить за приёмами и управлять аптечкой.
      </p>

      {isDependent ? (
        /* ── Вид подопечного ── */
        <>
          {/* Входящие запросы */}
          {data.pending_requests && data.pending_requests.length > 0 && (
            <div className="settings-block">
              {data.pending_requests.map((req) => (
                <div key={req.id} className="settings-row caregiver-request-row">
                  <span className="settings-label">
                    Запрос от @{req.caregiver_username ?? `id${req.caregiver_telegram_id}`}
                  </span>
                  <button className="dep-add-btn" onClick={() => confirmLink.mutate(req.id)} disabled={confirmLink.isPending}>
                    Принять
                  </button>
                  <button className="dep-delete-btn" onClick={() => declineLink.mutate(req.id)} disabled={declineLink.isPending}>
                    Отклонить
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="settings-block">
            {/* Режим заботы — заблокирован, ПЕРВЫМ */}
            <div className="settings-row">
              <span className="settings-label">Режим заботы</span>
              <label className="toggle-switch toggle-switch--locked">
                <input type="checkbox" checked disabled />
                <span className="toggle-track" />
              </label>
              <span className="caregiver-locked-hint">вкл. автоматически</span>
            </div>
            {/* Мой опекун */}
            <div className="settings-row" style={{ borderTop: '1px solid var(--secondary-bg)', paddingTop: 10, marginTop: 2 }}>
              <span className="settings-label">Мой помощник</span>
              <span className="caregiver-username">
                @{data.active_caregiver!.caregiver_username ?? `id${data.active_caregiver!.caregiver_telegram_id}`}
              </span>
            </div>
            {/* Кнопка отключения */}
            {data.active_caregiver!.break_requested ? (
              <div className="settings-row">
                <span className="settings-label" style={{ color: 'var(--hint)', fontSize: '0.85em' }}>
                  ⏳ Запрос на отключение отправлен
                </span>
              </div>
            ) : (
              <div className="settings-row">
                <button
                  className="btn-caregiver-break"
                  onClick={() => requestBreak.mutate(data.active_caregiver!.id)}
                  disabled={requestBreak.isPending}
                >
                  Отключиться от помощника
                </button>
              </div>
            )}
          </div>
        </>
      ) : (
        /* ── Вид опекуна / независимого ── */
        <>
          {/* Входящие запросы */}
          {data.pending_requests && data.pending_requests.length > 0 && (
            <div className="settings-block">
              {data.pending_requests.map((req) => (
                <div key={req.id} className="settings-row caregiver-request-row">
                  <span className="settings-label">
                    Запрос от @{req.caregiver_username ?? `id${req.caregiver_telegram_id}`}
                  </span>
                  <button className="dep-add-btn" onClick={() => confirmLink.mutate(req.id)} disabled={confirmLink.isPending}>
                    Принять
                  </button>
                  <button className="dep-delete-btn" onClick={() => declineLink.mutate(req.id)} disabled={declineLink.isPending}>
                    Отклонить
                  </button>
                </div>
              ))}
            </div>
          )}
          <div className="settings-block">
            {/* 1. Тогл */}
            <div className="settings-row">
              <span className="settings-label">Режим заботы</span>
              <label className="toggle-switch">
                <input
                  type="checkbox"
                  checked={!!data.caregiver_enabled}
                  onChange={(e) => {
                    const turning_off = !e.target.checked
                    if (turning_off && data.active_dependents?.length) {
                      setCaregiverOffConfirm(true)
                    } else {
                      setCaregiver.mutate(e.target.checked)
                    }
                  }}
                />
                <span className="toggle-track" />
              </label>
            </div>

            {caregiverOffConfirm && (
              <div className="inline-confirm">
                <p className="inline-confirm-text">
                  Связь с близкими <b>не удаляется</b> — отключается только наблюдение в приложении и уведомления.
                </p>
                <div className="inline-confirm-actions">
                  <button
                    className="inline-confirm-btn inline-confirm-btn--cancel"
                    onClick={() => setCaregiverOffConfirm(false)}
                    disabled={setCaregiver.isPending}
                  >
                    Отмена
                  </button>
                  <button
                    className="inline-confirm-btn inline-confirm-btn--primary"
                    onClick={() => { setCaregiver.mutate(false); setCaregiverOffConfirm(false) }}
                    disabled={setCaregiver.isPending}
                  >
                    Отключить
                  </button>
                </div>
              </div>
            )}

            {!!data.caregiver_enabled && (
              <>
                {/* 2. Мой код — сразу после тогла */}
                <div className="settings-row">
                  <span className="settings-label">Мой код</span>
                  <button className="caregiver-code-chip" onClick={handleCopyCode} title="Скопировать и поделиться">
                    <span className="caregiver-code-text">{data.caregiver_code ?? '…'}</span>
                    <span className="caregiver-code-icon">{codeCopied ? '✓' : '⎘'}</span>
                  </button>
                </div>

                {/* 3. Список подопечных */}
                <div className="caregiver-divider" />

                {deps?.map((d) => (
                  <div key={d.id} className="settings-row">
                    <span className="settings-label">{d.name}</span>
                    <button className="dep-delete-btn" onClick={() => deleteDep.mutate(d.id)} disabled={deleteDep.isPending}>
                      Удалить
                    </button>
                  </div>
                ))}

                {data.active_dependents?.map((dep) => (
                  <div key={dep.id}>
                    <div className="settings-row caregiver-dep-row">
                      <span className="settings-label">
                        @{dep.dependent_username ?? `id${dep.dependent_telegram_id}`}
                        {!!dep.break_requested && <span className="caregiver-break-badge"> ⚠️</span>}
                      </span>
                      {dep.break_requested ? (
                        <button
                          className="dep-add-btn"
                          onClick={() => deleteLink.mutate(dep.id)}
                          disabled={deleteLink.isPending}
                        >
                          Подтвердить отключение
                        </button>
                      ) : detachConfirmId === dep.id ? null : (
                        <button
                          className="btn-detach"
                          onClick={() => setDetachConfirmId(dep.id)}
                        >
                          Отвязать
                        </button>
                      )}
                    </div>
                    {detachConfirmId === dep.id && (
                      <div className="inline-confirm">
                        <p className="inline-confirm-text">
                          Близкий потеряет доступ к управлению своими настройками через помощника.
                        </p>
                        <div className="inline-confirm-actions">
                          <button className="inline-confirm-btn inline-confirm-btn--cancel" onClick={() => setDetachConfirmId(null)} disabled={deleteLink.isPending}>
                            Отмена
                          </button>
                          <button
                            className="inline-confirm-btn inline-confirm-btn--danger"
                            onClick={() => { deleteLink.mutate(dep.id); setDetachConfirmId(null) }}
                            disabled={deleteLink.isPending}
                          >
                            Отвязать
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}

                {data.pending_sent?.map((dep) => (
                  <div key={dep.id} className="settings-row caregiver-dep-row">
                    <span className="settings-label" style={{ color: 'var(--hint)' }}>
                      @{dep.dependent_username ?? `id${dep.dependent_telegram_id}`}
                    </span>
                    <span className="caregiver-status-badge pending">ожидает</span>
                  </div>
                ))}

                {(!deps?.length && !data.active_dependents?.length && !data.pending_sent?.length) && (
                  <div className="settings-row">
                    <span className="settings-label" style={{ color: 'var(--hint)' }}>Пока нет близких</span>
                  </div>
                )}

                {/* 4. Добавить */}
                <div className="caregiver-divider" />

                <div className="settings-row settings-row--add">
                  <input
                    className="dep-name-input"
                    placeholder="Имя или код XXXX-XXXX"
                    value={newDepInput}
                    onChange={(e) => setNewDepInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddDepOrLink()}
                    maxLength={40}
                  />
                  <button className="dep-add-btn" onClick={handleAddDepOrLink} disabled={!newDepInput.trim() || createDep.isPending || requestLink.isPending}>
                    Добавить
                  </button>
                </div>
                {depInputError && <p className="hint error" style={{ margin: '4px 0 0' }}>{depInputError}</p>}
              </>
            )}
          </div>
        </>
      )}

      <h2 className="section-title">Часовой пояс</h2>
      <p className="section-hint">
        Используется для точного расчёта времени напоминаний о приёме лекарств.
        Укажи свой город или выбери по геолокации.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Текущий</span>
          <span className="tz-current">{data.timezone}</span>
          {!tzEditing && (
            <button className="tz-change-btn" onClick={() => setTzEditing(true)}>
              Изменить
            </button>
          )}
        </div>
        {tzEditing && (
          <div className="tz-picker">
            <button
              className="tz-geo-btn"
              onClick={handleGeolocate}
              disabled={setTzByLocation.isPending}
            >
              {setTzByLocation.isPending ? 'Определяю…' : '📍 По геолокации'}
            </button>
            {geoError && <p className="tz-error">{geoError}</p>}
            <input
              className="tz-search-input"
              placeholder="Москва, Moscow, UTC+3…"
              value={tzSearch}
              onChange={(e) => setTzSearch(e.target.value)}
              autoFocus
            />
            <div className="tz-list">
              {filteredZones.map((z) => (
                <div
                  key={z.value}
                  className={`tz-list-item${z.value === data.timezone ? ' tz-list-item--active' : ''}`}
                  onClick={() => handleSelectTz(z.value)}
                >
                  <span className="tz-item-label">{z.label}</span>
                  <span className="tz-item-value">{z.value}</span>
                </div>
              ))}
              {filteredZones.length === 0 && (
                <p className="tz-empty">Ничего не найдено</p>
              )}
            </div>
            <button className="tz-cancel-btn" onClick={() => { setTzEditing(false); setTzSearch(''); setGeoError('') }}>
              Отмена
            </button>
          </div>
        )}
      </div>

      {!!data.is_admin && (
        <>
          <h2 className="section-title">Админ-панель</h2>
          <div className="settings-block admin-panel">
            {!adminStats ? (
              <div className="settings-row">
                <span className="settings-label" style={{ color: 'var(--hint)' }}>Загрузка…</span>
              </div>
            ) : (
              <>
                <div className="admin-section-label">Сервисы</div>
                {adminStats.services?.map((svc) => (
                  <div key={svc.unit} className="settings-row">
                    <span className="settings-label">{svc.name}{METRIC_HINTS[svc.name] && <InfoTip text={METRIC_HINTS[svc.name]} />}</span>
                    <span className={`admin-status ${svc.status === 'active' ? 'admin-status--ok' : 'admin-status--err'}`}>
                      ● {svc.status}
                    </span>
                  </div>
                ))}

                <div className="admin-section-label">CPU / RAM / Disk</div>
                <div className="settings-row">
                  <span className="settings-label">CPU<InfoTip text={METRIC_HINTS['CPU']} /></span>
                  <span className={`admin-stat-val${adminStats.cpu_pct > 80 || adminStats.load_1m > adminStats.cpu_count ? ' admin-stat--warn' : ''}`}>
                    {adminStats.cpu_pct}% · load {adminStats.load_1m}
                  </span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">RAM<InfoTip text={METRIC_HINTS['RAM']} /></span>
                  <span className={`admin-stat-val${adminStats.ram_pct > 85 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.ram_pct}% · {adminStats.ram_used_mb} / {adminStats.ram_total_mb} МБ
                  </span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">SWAP<InfoTip text={METRIC_HINTS['SWAP']} /></span>
                  <span className={`admin-stat-val${adminStats.swap_pct > 50 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.swap_total_mb > 0
                      ? `${adminStats.swap_pct}% · ${adminStats.swap_used_mb} / ${adminStats.swap_total_mb} МБ`
                      : 'не настроен'}
                  </span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Disk<InfoTip text={METRIC_HINTS['Disk']} /></span>
                  <span className={`admin-stat-val${adminStats.disk_pct > 85 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.disk_pct}% · {adminStats.disk_free_gb} ГБ своб. / {adminStats.disk_total_gb} ГБ
                  </span>
                </div>

                <div className="admin-section-label">Redis</div>
                <div className="settings-row">
                  <span className="settings-label">Redis память<InfoTip text={METRIC_HINTS['Redis память']} /></span>
                  <span className="admin-stat-val">{adminStats.redis_mem ?? '—'}</span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Redis клиентов<InfoTip text={METRIC_HINTS['Redis клиентов']} /></span>
                  <span className={`admin-stat-val${(adminStats.redis_clients ?? 0) > 20 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.redis_clients ?? '—'}
                  </span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">ARQ очередь<InfoTip text={METRIC_HINTS['ARQ очередь']} /></span>
                  <span className={`admin-stat-val${(adminStats.arq_queue ?? 0) > 50 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.arq_queue ?? '—'}
                  </span>
                </div>

                <div className="admin-section-label">DB pool</div>
                <div className="settings-row">
                  <span className="settings-label">Соединений<InfoTip text={METRIC_HINTS['DB pool']} /></span>
                  <span className={`admin-stat-val${(adminStats.db_pool_available ?? 99) < 2 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.db_pool_available ?? '—'} / {adminStats.db_pool_size ?? '—'} свободно
                  </span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Ожидают<InfoTip text={METRIC_HINTS['DB pool']} /></span>
                  <span className={`admin-stat-val${(adminStats.db_pool_requests ?? 0) > 0 ? ' admin-stat--warn' : ''}`}>
                    {adminStats.db_pool_requests ?? '—'}
                  </span>
                </div>

                <div className="admin-section-label">Пользователи</div>
                <div className="settings-row">
                  <span className="settings-label">Всего</span>
                  <span className="admin-stat-val">{adminStats.total_users}</span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Лекарств активных</span>
                  <span className="admin-stat-val">{adminStats.total_meds}</span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Активных сегодня</span>
                  <span className="admin-stat-val">{adminStats.active_today}</span>
                </div>

                <div className="settings-row" style={{ justifyContent: 'center', paddingTop: 4 }}>
                  <button className="tz-change-btn" onClick={() => refetchAdmin()}>
                    Обновить
                  </button>
                </div>
              </>
            )}
          </div>
        </>
      )}

      <div className="account-delete-section">
        <p className="account-delete-note">
          Мы храним твой Telegram ID, никнейм и список лекарств.
          Хочешь сделать перерыв — лучше поставь лекарства на паузу, данные сохранятся.
        </p>
        {deleted ? (
          <p className="account-deleted-msg">Данные удалены. До свидания 👋</p>
        ) : deleteBlockedByCaregiver ? (
          <div className="account-delete-confirm">
            <p className="account-delete-warn" style={{ color: 'var(--hint)' }}>
              Удаление невозможно, пока есть связь с помощником.
              Сначала отключись от помощника в блоке «Забота» выше.
            </p>
            <button className="btn-cancel-delete" onClick={() => setDeleteBlockedByCaregiver(false)}>
              Понятно
            </button>
          </div>
        ) : !confirmDeleteAccount ? (
          <button
            className="btn-delete-account"
            onClick={() => {
              if (isDependent) { setDeleteBlockedByCaregiver(true); return }
              setConfirmDeleteAccount(true)
            }}
          >
            Удалить все мои данные
          </button>
        ) : (
          <div className="account-delete-confirm">
            <p className="account-delete-warn">
              Лекарства, история приёмов и расписание исчезнут навсегда.
            </p>
            {deleteAccount.isError && (
              <p className="hint error" style={{ fontSize: '13px', margin: 0 }}>
                Не удалось удалить данные. Попробуй ещё раз.
              </p>
            )}
            <div className="account-delete-actions">
              <button
                className="account-delete-cancel-btn"
                onClick={() => { setConfirmDeleteAccount(false); deleteAccount.reset() }}
                disabled={deleteAccount.isPending}
              >
                Отмена
              </button>
              <button
                className="account-delete-confirm-btn"
                disabled={deleteAccount.isPending}
                onClick={() =>
                  deleteAccount.mutate(undefined, {
                    onSuccess: () => setDeleted(true),
                  })
                }
              >
                {deleteAccount.isPending ? '…' : 'Удалить'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
