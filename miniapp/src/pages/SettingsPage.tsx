import { useState, useEffect, useMemo, useRef, type ReactNode } from 'react'
import { Sun, Moon, User, Check, X, Clock, Copy, Bell, Link2, AlertTriangle, MapPin, Trophy, Languages, Search, GraduationCap } from 'lucide-react'
import {
  useSettings, useSetReminderMode, useSetDailyPlan, useSetCaregiver,
  useDependents, useCreateDependent, useDeleteDependent,
  useSetTimezone, useSetTimezoneByLocation, useDeleteAccount, useSetStrictMode,
  useAdminStats, useRequestCaregiverLink, useConfirmCaregiverLink,
  useDeclineCaregiverLink, useDeleteCaregiverLink, useRequestLinkBreak,
  useSetDependentReminderMode, useSetDependentStrictMode,
  useEnsureDepShareCode, useJoinDepShare, useConfirmDepShare, useDeclineDepShare,
  useRevokeDepShare, useLeaveDepShare, useSetWishes, useSetWishesTg,
} from '../api/hooks'
import TimePicker from '../components/TimePicker'
import { getThemePref, setThemePref, type ThemePref } from '../theme'
import { resetOnboarding } from '../components/OnboardingTour'

// Маска кода: только A-Z0-9, разбивка по 4 через «-», максимум 12 символов (XXXX-XXXX-XXXX)
function formatCodeInput(raw: string): string {
  const clean = raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12)
  return clean.match(/.{1,4}/g)?.join('-') ?? ''
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

function PendingCard({
  user, desc, onAccept, onDecline, busy,
}: {
  user: string
  desc: string
  onAccept: () => void
  onDecline: () => void
  busy?: boolean
}) {
  return (
    <div className="pending-card">
      <span className="pending-card-icon"><User size={20} strokeWidth={2} /></span>
      <div className="pending-card-body">
        <span className="pending-card-user">{user}</span>
        <span className="pending-card-desc">{desc}</span>
      </div>
      <div className="pending-card-actions">
        <button className="pending-card-btn pending-card-btn--accept" title="Принять" onClick={onAccept} disabled={busy}><Check size={18} strokeWidth={2.5} /></button>
        <button className="pending-card-btn pending-card-btn--decline" title="Отклонить" onClick={onDecline} disabled={busy}><X size={18} strokeWidth={2.5} /></button>
      </div>
    </div>
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

export default function SettingsPage({ onReplayTour }: { onReplayTour?: () => void } = {}) {
  const { data, isLoading } = useSettings()
  const setMode = useSetReminderMode()
  const setDailyPlan = useSetDailyPlan()
  const setCaregiver = useSetCaregiver()
  const setStrict = useSetStrictMode()
  const setWishes = useSetWishes()
  const setWishesTg = useSetWishesTg()

  const { data: deps } = useDependents()
  const createDep = useCreateDependent()
  const deleteDep = useDeleteDependent()

  const setTz = useSetTimezone()
  const setTzByLocation = useSetTimezoneByLocation()

  const deleteAccount = useDeleteAccount()
  const { data: adminStats, refetch: refetchAdmin } = useAdminStats(!!data?.is_admin)
  const [theme, setTheme] = useState<ThemePref>(getThemePref())
  const [dailyPlanTime, setDailyPlanTime] = useState('08:00')
  const [planTimeEditing, setPlanTimeEditing] = useState(false)
  const [strictTime, setStrictTime] = useState('02:00')
  const [strictTimeOpen, setStrictTimeOpen] = useState(false)
  const [repeatTime, setRepeatTime] = useState('02:00')
  const [repeatTimeOpen, setRepeatTimeOpen] = useState(false)
  const [addMode, setAddMode] = useState<'none' | 'name' | 'code'>('none')
  const [nameInput, setNameInput] = useState('')
  const [codeInput, setCodeInput] = useState('')
  const [addError, setAddError] = useState('')
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

  // F8: dep shares
  const ensureDepShareCode = useEnsureDepShareCode()
  const joinDepShare = useJoinDepShare()
  const confirmDepShare = useConfirmDepShare()
  const declineDepShare = useDeclineDepShare()
  const revokeDepShare = useRevokeDepShare()
  const leaveDepShare = useLeaveDepShare()
  const [shareOpenId, setShareOpenId] = useState<number | null>(null)
  const [shareCopiedId, setShareCopiedId] = useState<number | null>(null)
  const [leaveConfirmId, setLeaveConfirmId] = useState<number | null>(null)
  const [shareCodeError, setShareCodeError] = useState<Record<number, boolean>>({})
  // WP4: сворачиваемые подсекции «Забота» (локально, без API). Default — открыты.
  const [myDepsOpen, setMyDepsOpen] = useState(true)
  const [helpingOpen, setHelpingOpen] = useState(true)
  // Подтверждение жёсткого удаления локального близкого (без viewer = удаляется из БД полностью)
  const [deleteDepConfirmId, setDeleteDepConfirmId] = useState<number | null>(null)

  const handleCopyCode = () => {
    if (!data?.caregiver_code) return
    const code = data.caregiver_code
    navigator.clipboard.writeText(code).catch(() => {})
    setCodeCopied(true)
    setTimeout(() => setCodeCopied(false), 2000)
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const tg = (window as any).Telegram?.WebApp
      tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(code)}&text=${encodeURIComponent('Мой код для подключения помощника: ' + code)}`)
    } catch { /* noop */ }
  }

  const resetAdd = () => {
    setAddMode('none'); setNameInput(''); setCodeInput(''); setAddError('')
  }

  const handleAddName = () => {
    const val = nameInput.trim()
    if (!val) return
    setAddError('')
    createDep.mutate(val, {
      onSuccess: resetAdd,
      onError: (e) => setAddError((e as Error).message),
    })
  }

  const handleAddCode = () => {
    const val = codeInput.trim().toUpperCase()
    if (!val) return
    setAddError('')
    if (/^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(val)) {
      joinDepShare.mutate(val, {
        onSuccess: resetAdd,
        onError: (e) => setAddError((e as Error).message),
      })
    } else if (/^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(val)) {
      requestLink.mutate(val, {
        onSuccess: resetAdd,
        onError: (e) => setAddError((e as Error).message),
      })
    } else {
      setAddError('Код в формате XXXX-XXXX или XXXX-XXXX-XXXX')
    }
  }

  const handleCopyDepShareCode = (depId: number, code: string) => {
    navigator.clipboard.writeText(code).catch(() => {})
    setShareCopiedId(depId)
    setTimeout(() => setShareCopiedId(null), 2000)
  }

  const handleToggleShare = (depId: number) => {
    if (shareOpenId === depId) {
      setShareOpenId(null)
      return
    }
    setShareOpenId(depId)
    const existing = data?.dep_shares?.[String(depId)]
    if (!existing?.share_code) {
      setShareCodeError((p) => ({ ...p, [depId]: false }))
      ensureDepShareCode.mutate(depId, {
        onError: () => setShareCodeError((p) => ({ ...p, [depId]: true })),
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
    /* eslint-disable react-hooks/set-state-in-effect */
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
    /* eslint-enable react-hooks/set-state-in-effect */
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

  // Все входящие запросы заботы — собраны в один блок «Запросы» сверху
  const caregiverReqs = data.pending_requests ?? []
  const depShareReqs = (deps ?? []).flatMap((d) =>
    (data.dep_shares?.[String(d.id)]?.pending_viewers ?? []).map((v) => ({ ...v, depName: d.name }))
  )

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Настройки</span>
      </div>

      <h2 className="section-title">Внешний вид</h2>
      <p className="section-hint">
        «Как в Telegram» подстраивается под тему клиента.
      </p>
      <div className="theme-seg">
        {([
          ['auto', <>Как в Telegram</>],
          ['light', <><Sun size={15} strokeWidth={2} /> Светлая</>],
          ['dark', <><Moon size={15} strokeWidth={2} /> Тёмная</>],
        ] as [ThemePref, ReactNode][]).map(([val, label]) => (
          <button
            key={val}
            type="button"
            className={`seg-btn${theme === val ? ' seg-btn--active' : ''}`}
            onClick={() => { setTheme(val); setThemePref(val) }}
          >
            {label}
          </button>
        ))}
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

      <div id="tour-care-section">
      <h2 className="section-title">Забота</h2>
      <p className="section-hint">
        Следите за приёмами близких и управляйте их аптечкой прямо из приложения. Другой пользователь бота может стать вашим помощником или взять заботу о конкретном близком.
      </p>

      {isDependent ? (
        /* ── Вид подопечного ── */
        <>
          {data.pending_requests && data.pending_requests.length > 0 && (
            <div className="settings-block settings-block--pending">
              {data.pending_requests.map((req) => (
                <PendingCard
                  key={req.id}
                  user={`@${req.caregiver_username ?? `id${req.caregiver_telegram_id}`}`}
                  desc="хочет стать вашим помощником"
                  onAccept={() => confirmLink.mutate(req.id)}
                  onDecline={() => declineLink.mutate(req.id)}
                  busy={confirmLink.isPending || declineLink.isPending}
                />
              ))}
            </div>
          )}
          <div className="settings-block">
            <div className="settings-row">
              <span className="settings-label">Режим заботы</span>
              <label className="toggle-switch toggle-switch--locked">
                <input type="checkbox" checked disabled />
                <span className="toggle-track" />
              </label>
            </div>
            <div className="settings-row">
              <span className="settings-label--hint caregiver-block-hint">
                Включается автоматически, пока есть связь с помощником
              </span>
            </div>
            <div className="settings-row settings-row--divided">
              <span className="settings-label">Мой помощник</span>
              <span className="caregiver-username">
                @{data.active_caregiver!.caregiver_username ?? `id${data.active_caregiver!.caregiver_telegram_id}`}
              </span>
            </div>
            {data.active_caregiver!.break_requested ? (
              <div className="settings-row">
                <span className="settings-label settings-label--hint-sm">
                  <Clock size={14} strokeWidth={2} className="ic" /> Запрос на отключение отправлен
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
          {/* Все входящие запросы — один блок сверху */}
          {(caregiverReqs.length > 0 || depShareReqs.length > 0) && (
            <div className="settings-block settings-block--pending">
              {caregiverReqs.map((req) => (
                <PendingCard
                  key={`cl${req.id}`}
                  user={`@${req.caregiver_username ?? `id${req.caregiver_telegram_id}`}`}
                  desc="хочет стать вашим помощником"
                  onAccept={() => confirmLink.mutate(req.id)}
                  onDecline={() => declineLink.mutate(req.id)}
                  busy={confirmLink.isPending || declineLink.isPending}
                />
              ))}
              {depShareReqs.map((v) => (
                <PendingCard
                  key={`ds${v.share_id}`}
                  user={`@${v.username}`}
                  desc={`хочет помогать с «${v.depName}»`}
                  onAccept={() => confirmDepShare.mutate(v.share_id)}
                  onDecline={() => declineDepShare.mutate(v.share_id)}
                  busy={confirmDepShare.isPending || declineDepShare.isPending}
                />
              ))}
            </div>
          )}

          {/* Тогл + Мой код */}
          <div className="settings-block">
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
            <div className="settings-row">
              <span className="settings-label--hint caregiver-block-hint">
                Создаёт ваш код-приглашение и показывает близких и подопечных в приложении. Выключение скрывает их и уведомления — связи при этом сохраняются.
              </span>
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
                <div className="settings-row">
                  <span className="settings-label">Мой код</span>
                  <button className="caregiver-code-chip" onClick={handleCopyCode} title="Скопировать и поделиться">
                    <span className="caregiver-code-text">{data.caregiver_code ?? '…'}</span>
                    <span className="caregiver-code-icon">{codeCopied ? <Check size={15} strokeWidth={2.5} /> : <Copy size={15} strokeWidth={2} />}</span>
                  </button>
                </div>
                <div className="settings-row">
                  <span className="settings-label--hint caregiver-block-hint">
                    Дайте этот код тому, кто хочет стать вашим помощником
                  </span>
                </div>
              </>
            )}
          </div>

          {!!data.caregiver_enabled && (
            <>
              {/* Мои близкие */}
              <div className="settings-block">
                <button
                  className="settings-row care-section-toggle"
                  onClick={() => setMyDepsOpen((v) => !v)}
                  aria-expanded={myDepsOpen}
                >
                  <span className="settings-label caregiver-block-label">Мои близкие</span>
                  <span className="care-section-chevron">{myDepsOpen ? '⌄' : '›'}</span>
                </button>

                {myDepsOpen && <>
                {deps?.map((d) => {
                  const share = data.dep_shares?.[String(d.id)]
                  const isShareOpen = shareOpenId === d.id
                  const shareCode = share?.share_code
                  const hasViewer = !!share?.active_viewer
                  const hasPending = !!share?.pending_viewers?.length
                  return (
                    <div key={d.id}>
                      <div className="settings-row caregiver-dep-row">
                        <span className="settings-label">{d.name}</span>
                        <div className="dep-row-actions">
                          <button
                            className={`btn-dep-share${isShareOpen ? ' btn-dep-share--active' : ''}${hasPending ? ' btn-dep-share--notify' : ''}`}
                            onClick={() => handleToggleShare(d.id)}
                            title={hasViewer ? 'Управление доступом' : `Дать доступ к ${d.name}`}
                          >
                            {hasPending ? <Bell size={16} strokeWidth={2} /> : hasViewer ? <User size={16} strokeWidth={2} /> : <Link2 size={16} strokeWidth={2} />}
                          </button>
                          <button
                            className={`btn-detach${!hasViewer && deleteDepConfirmId === d.id ? ' btn-detach--armed' : ''}`}
                            onClick={() => {
                              if (hasViewer) { deleteDep.mutate(d.id); return }
                              // 2-тапа по одной кнопке: 1-й → предупреждение, 2-й → удаление
                              if (deleteDepConfirmId === d.id) {
                                deleteDep.mutate(d.id)
                                setDeleteDepConfirmId(null)
                              } else {
                                setDeleteDepConfirmId(d.id)
                              }
                            }}
                            disabled={deleteDep.isPending}
                          >
                            {hasViewer ? 'Отвязать' : deleteDepConfirmId === d.id ? 'Точно удалить' : 'Удалить'}
                          </button>
                        </div>
                      </div>
                      {deleteDepConfirmId === d.id && (
                        <div className="inline-confirm">
                          <p className="inline-confirm-text">
                            «{d.name}» и все его препараты будут удалены <b>полностью и безвозвратно</b>. Нажмите «Точно удалить» ещё раз для подтверждения.
                          </p>
                        </div>
                      )}
                      {isShareOpen && (
                        <div className="dep-share-panel">
                          <p className="dep-share-hint">
                            {hasViewer
                              ? `@${share!.active_viewer!.username} имеет доступ к «${d.name}» и может управлять его препаратами`
                              : `Передайте код тому, кто хочет помогать с «${d.name}» — он сможет добавлять и редактировать препараты`}
                          </p>
                          {share?.active_viewer && (
                            <div className="settings-row">
                              <span className="settings-label settings-label--hint">Помогает</span>
                              <button className="btn-detach" onClick={() => revokeDepShare.mutate(share.active_viewer!.share_id)} disabled={revokeDepShare.isPending}>
                                Отозвать доступ
                              </button>
                            </div>
                          )}
                          <div className="settings-row">
                            <span className="settings-label settings-label--hint">Код доступа</span>
                            {shareCode ? (
                              <button className="caregiver-code-chip" onClick={() => handleCopyDepShareCode(d.id, shareCode)} title="Скопировать">
                                <span className="caregiver-code-text">{shareCode}</span>
                                <span className="caregiver-code-icon">{shareCopiedId === d.id ? <Check size={15} strokeWidth={2.5} /> : <Copy size={15} strokeWidth={2} />}</span>
                              </button>
                            ) : shareCodeError[d.id] ? (
                              <button className="dep-add-btn" onClick={() => {
                                setShareCodeError((p) => ({ ...p, [d.id]: false }))
                                ensureDepShareCode.mutate(d.id, {
                                  onError: () => setShareCodeError((p) => ({ ...p, [d.id]: true })),
                                })
                              }}>Повторить</button>
                            ) : (
                              <span className="settings-label--hint">генерация…</span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}

                {data.active_dependents?.map((dep) => (
                  <div key={dep.id}>
                    <div className="settings-row caregiver-dep-row">
                      <span className="settings-label">
                        @{dep.dependent_username ?? `id${dep.dependent_telegram_id}`}
                        {!!dep.break_requested && <span className="caregiver-break-badge"> <AlertTriangle size={13} strokeWidth={2} className="ic" /></span>}
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
                    <span className="settings-label settings-label--hint">
                      @{dep.dependent_username ?? `id${dep.dependent_telegram_id}`}
                    </span>
                    <span className="caregiver-status-badge pending">ожидает</span>
                  </div>
                ))}

                {!deps?.length && !data.active_dependents?.length && !data.pending_sent?.length && (
                  <div className="settings-row caregiver-empty-row">
                    <span className="settings-label--hint caregiver-block-hint">
                      Пока никого нет. Добавьте близкого или подключитесь по коду.
                    </span>
                  </div>
                )}

                <div className="caregiver-divider" />

                {addMode === 'none' && (
                  <div className="caregiver-add-actions">
                    <button className="caregiver-add-btn" onClick={() => { setAddMode('name'); setAddError('') }}>
                      + Близкий
                    </button>
                    <button className="caregiver-add-btn caregiver-add-btn--ghost" onClick={() => { setAddMode('code'); setAddError('') }}>
                      У меня есть код
                    </button>
                  </div>
                )}

                {addMode === 'name' && (
                  <div className="caregiver-add-expand">
                    <p className="caregiver-input-hint">Создать профиль близкого, за которым вы ухаживаете.</p>
                    <input
                      className="dep-name-input caregiver-add-input"
                      placeholder="Имя близкого"
                      value={nameInput}
                      autoFocus
                      onChange={(e) => setNameInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleAddName()}
                      maxLength={40}
                    />
                    {addError && <p className="hint error dep-input-error">{addError}</p>}
                    <div className="caregiver-add-btn-row">
                      <button className="caregiver-add-cancel-btn" onClick={resetAdd}>Отмена</button>
                      <button className="caregiver-add-done-btn" onClick={handleAddName} disabled={!nameInput.trim() || createDep.isPending}>
                        Добавить
                      </button>
                    </div>
                  </div>
                )}

                {addMode === 'code' && (
                  <div className="caregiver-add-expand">
                    <input
                      className="dep-name-input caregiver-add-input dep-code-input"
                      placeholder="XXXX-XXXX"
                      value={codeInput}
                      autoFocus
                      onChange={(e) => setCodeInput(formatCodeInput(e.target.value))}
                      onKeyDown={(e) => e.key === 'Enter' && handleAddCode()}
                      maxLength={14}
                      inputMode="text"
                    />
                    <p className="caregiver-input-hint caregiver-input-hint--codes">
                      <span><b>XXXX-XXXX</b> — стать помощником пользователя</span>
                      <span><b>XXXX-XXXX-XXXX</b> — подключиться к профилю близкого с другого устройства</span>
                    </p>
                    {addError && <p className="hint error dep-input-error">{addError}</p>}
                    <div className="caregiver-add-btn-row">
                      <button className="caregiver-add-cancel-btn" onClick={resetAdd}>Отмена</button>
                      <button className="caregiver-add-done-btn" onClick={handleAddCode} disabled={!codeInput.trim() || requestLink.isPending || joinDepShare.isPending}>
                        Подключить
                      </button>
                    </div>
                  </div>
                )}
                </>}
              </div>

              {/* Помогаю (viewer side) */}
              {(!!data.viewing_deps?.length || !!data.pending_viewing_deps?.length) && (
                <div className="settings-block">
                  <button
                    className="settings-row care-section-toggle"
                    onClick={() => setHelpingOpen((v) => !v)}
                    aria-expanded={helpingOpen}
                  >
                    <span className="settings-label caregiver-block-label">Помогаю</span>
                    <span className="care-section-chevron">{helpingOpen ? '⌄' : '›'}</span>
                  </button>
                  {helpingOpen && <>
                  <div className="settings-row">
                    <span className="settings-label--hint caregiver-block-hint">
                      Близкие других пользователей, к которым вы подключились по коду доступа
                    </span>
                  </div>
                  {data.pending_viewing_deps?.map((v) => (
                    <div key={v.share_id} className="settings-row caregiver-dep-row">
                      <span className="settings-label">
                        {v.dep_name}
                        <span className="settings-label--hint"> · @{v.owner_username}</span>
                      </span>
                      <div className="dep-row-actions">
                        <span className="caregiver-status-badge pending">ожидает</span>
                        <button className="btn-detach" onClick={() => leaveDepShare.mutate(v.share_id)} disabled={leaveDepShare.isPending}>
                          Отменить
                        </button>
                      </div>
                    </div>
                  ))}
                  {data.viewing_deps.map((v) => (
                    <div key={v.share_id}>
                      <div className="settings-row caregiver-dep-row">
                        <span className="settings-label">
                          {v.dep_name}
                          <span className="settings-label--hint"> · @{v.owner_username}</span>
                        </span>
                        <div className="dep-row-actions">
                          <span className="caregiver-status-badge active">подключено</span>
                          {leaveConfirmId !== v.share_id ? (
                            <button className="btn-detach" onClick={() => setLeaveConfirmId(v.share_id)}>
                              Отписаться
                            </button>
                          ) : null}
                        </div>
                      </div>
                      {leaveConfirmId === v.share_id && (
                        <div className="inline-confirm">
                          <p className="inline-confirm-text">Вы перестанете видеть «{v.dep_name}» в приложении.</p>
                          <div className="inline-confirm-actions">
                            <button className="inline-confirm-btn inline-confirm-btn--cancel" onClick={() => setLeaveConfirmId(null)}>Отмена</button>
                            <button
                              className="inline-confirm-btn inline-confirm-btn--danger"
                              onClick={() => { leaveDepShare.mutate(v.share_id); setLeaveConfirmId(null) }}
                              disabled={leaveDepShare.isPending}
                            >
                              Отписаться
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                  </>}
                </div>
              )}
            </>
          )}
        </>
      )}
      </div>

      <h2 className="section-title">Часовой пояс</h2>
      <p className="section-hint">
        Используется для точного расчёта времени напоминаний о приёме препаратов.
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
              {setTzByLocation.isPending ? 'Определяю…' : <><MapPin size={15} strokeWidth={2} className="ic" /> По геолокации</>}
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
                <span className="settings-label settings-label--hint">Загрузка…</span>
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
                  <span className="settings-label">Препаратов активных</span>
                  <span className="admin-stat-val">{adminStats.total_meds}</span>
                </div>
                <div className="settings-row">
                  <span className="settings-label">Активных сегодня</span>
                  <span className="admin-stat-val">{adminStats.active_today}</span>
                </div>

                <div className="settings-row settings-row--center">
                  <button className="tz-change-btn" onClick={() => refetchAdmin()}>
                    Обновить
                  </button>
                </div>
              </>
            )}
          </div>
        </>
      )}

      <h2 className="section-title">
        Слова поддержки <span className="settings-test-badge">тест</span>
      </h2>
      <p className="section-hint">
        Передавай тёплые пожелания случайным людям и получай их сам — полностью
        анонимно. Это тестовая функция: включи, чтобы попробовать.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Участвовать</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.wishes_enabled}
              onChange={(e) => setWishes.mutate(e.target.checked)}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {!!data.wishes_enabled && (
          <div className="settings-row">
            <span className="settings-label">
              Уведомлять в Telegram
              <span className="settings-sublabel">сводка откликов раз в день; в приложении видно всегда</span>
            </span>
            <label className="toggle-switch">
              <input
                type="checkbox"
                checked={!!data.wishes_tg_notify}
                onChange={(e) => setWishesTg.mutate(e.target.checked)}
              />
              <span className="toggle-track" />
            </label>
          </div>
        )}
      </div>

      <h2 className="section-title">Обучение</h2>
      <button type="button" className="replay-tour-btn" onClick={() => onReplayTour?.()}>
        <GraduationCap size={18} strokeWidth={2} className="ic" />
        Пройти обучение заново
      </button>

      <h2 className="section-title">В планах</h2>
      <div className="roadmap-card">
        <div className="roadmap-item">
          <span className="roadmap-icon"><Trophy size={18} strokeWidth={2} /></span>
          <div className="roadmap-body">
            <span className="roadmap-title">Достижения по уровням</span>
            <span className="roadmap-desc">Один бейдж растёт по ступеням с прогрессом до следующей</span>
          </div>
        </div>
        <div className="roadmap-item">
          <span className="roadmap-icon"><Languages size={18} strokeWidth={2} /></span>
          <div className="roadmap-body">
            <span className="roadmap-title">English / Русский</span>
            <span className="roadmap-desc">Выбор языка приложения и напоминаний</span>
          </div>
        </div>
        <div className="roadmap-item">
          <span className="roadmap-icon"><Search size={18} strokeWidth={2} /></span>
          <div className="roadmap-body">
            <span className="roadmap-title">Справочник препаратов</span>
            <span className="roadmap-desc">Подсказка названий и мягкое предупреждение о сочетаниях</span>
          </div>
        </div>
      </div>

      <div className="account-delete-section">
        <p className="account-delete-note">
          Мы храним твой Telegram ID, никнейм и список препаратов.
          Хочешь сделать перерыв — лучше поставь препараты на паузу, данные сохранятся.
        </p>
        {deleted ? (
          <p className="account-deleted-msg">Данные удалены. До свидания 👋</p>
        ) : deleteBlockedByCaregiver ? (
          <div className="account-delete-confirm">
            <p className="account-delete-warn account-delete-warn--muted">
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
              Препараты, история приёмов и расписание исчезнут навсегда.
            </p>
            {deleteAccount.isError && (
              <p className="hint error hint-error--inline">
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
                    onSuccess: () => { resetOnboarding(); setDeleted(true) },
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
