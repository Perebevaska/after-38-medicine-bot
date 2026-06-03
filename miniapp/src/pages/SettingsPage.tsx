import { useState, useEffect, useMemo, useRef } from 'react'
import {
  useSettings, useSetReminderMode, useSetDailyPlan, useSetCaregiver,
  useDependents, useCreateDependent, useDeleteDependent,
  useSetTimezone, useSetTimezoneByLocation, useDeleteAccount, useSetStrictMode,
  useAdminStats,
} from '../api/hooks'

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
  const [strictHours, setStrictHours] = useState(2)
  const [repeatHours, setRepeatHours] = useState(2)
  const [newDepName, setNewDepName] = useState('')
  const [tzEditing, setTzEditing] = useState(false)
  const [tzSearch, setTzSearch] = useState('')
  const [geoError, setGeoError] = useState('')
  const [confirmDeleteAccount, setConfirmDeleteAccount] = useState(false)
  const [deleted, setDeleted] = useState(false)

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

  useEffect(() => {
    if (!data) return
    setDailyPlanTime(data.daily_plan_time ?? '08:00')
    setStrictHours(data.strict_mode_hours ?? 2)
    setRepeatHours(data.reminder_repeat_hours ?? 2)
  }, [data])

  if (isLoading) return <div className="page"><p className="hint">Загрузка…</p></div>
  if (!data) return <div className="page"><p className="hint">Нет данных</p></div>

  const handleDailyPlanTimeBlur = () => {
    setDailyPlan.mutate({ enabled: !!data.daily_plan_enabled, time: dailyPlanTime })
  }

  const handleAddDep = () => {
    const name = newDepName.trim()
    if (!name) return
    createDep.mutate(name, { onSuccess: () => setNewDepName('') })
  }

  return (
    <div className="page">

      <h2 className="section-title">Напоминания</h2>
      <p className="section-hint">
        Если включён повтор — бот будет напоминать каждые 5 минут, пока не отметишь приём или не истечёт заданное время.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Повтор напоминаний</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={data.reminder_mode === 'repeat'}
              onChange={(e) => setMode.mutate({ mode: e.target.checked ? 'repeat' : 'once', hours: repeatHours })}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {data.reminder_mode === 'repeat' && (
          <div className="settings-row">
            <span className="settings-label">Повторять до (часов)</span>
            <input
              type="number"
              className="settings-time-input"
              min={1}
              max={12}
              value={repeatHours}
              onChange={(e) => setRepeatHours(Math.min(12, Math.max(1, +e.target.value)))}
              onBlur={() => setMode.mutate({ mode: 'repeat', hours: repeatHours })}
            />
          </div>
        )}
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
          <div className="settings-row">
            <span className="settings-label">Время отправки</span>
            <input
              type="time"
              className="settings-time-input"
              value={dailyPlanTime}
              onChange={(e) => setDailyPlanTime(e.target.value)}
              onBlur={handleDailyPlanTimeBlur}
            />
          </div>
        )}
      </div>

      <h2 className="section-title">Строгий режим</h2>
      <p className="section-hint">
        Если не отметить приём за заданное число часов после времени — он
        автоматически считается пропущенным и снимается ❤️.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Включён</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.strict_mode}
              onChange={(e) => setStrict.mutate({ enabled: e.target.checked, hours: strictHours })}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {!!data.strict_mode && (
          <div className="settings-row">
            <span className="settings-label">Через сколько часов</span>
            <input
              type="number"
              className="settings-time-input"
              min={1}
              max={24}
              value={strictHours}
              onChange={(e) => setStrictHours(Math.min(24, Math.max(1, +e.target.value)))}
              onBlur={() => setStrict.mutate({ enabled: true, hours: strictHours })}
            />
          </div>
        )}
      </div>

      <h2 className="section-title">Режим опекуна</h2>
      <p className="section-hint">
        Позволяет добавлять лекарства для членов семьи или подопечных и отслеживать
        их приёмы отдельно — всё в одном приложении.
      </p>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Включён</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.caregiver_enabled}
              onChange={(e) => setCaregiver.mutate(e.target.checked)}
            />
            <span className="toggle-track" />
          </label>
        </div>
      </div>

      {!!data.caregiver_enabled && (
        <>
          <h2 className="section-title">Подопечные</h2>
          <div className="settings-block">
            {(!deps || deps.length === 0) && (
              <div className="settings-row">
                <span className="settings-label" style={{ color: 'var(--hint)' }}>
                  Пока нет подопечных
                </span>
              </div>
            )}
            {deps?.map((d) => (
              <div key={d.id} className="settings-row">
                <span className="settings-label">{d.name}</span>
                <button
                  className="dep-delete-btn"
                  onClick={() => deleteDep.mutate(d.id)}
                  disabled={deleteDep.isPending}
                >
                  Удалить
                </button>
              </div>
            ))}
            <div className="settings-row settings-row--add">
              <input
                className="dep-name-input"
                placeholder="Имя подопечного"
                value={newDepName}
                onChange={(e) => setNewDepName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddDep()}
                maxLength={40}
              />
              <button
                className="dep-add-btn"
                onClick={handleAddDep}
                disabled={!newDepName.trim() || createDep.isPending}
              >
                Добавить
              </button>
            </div>
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
          Бот хранит только анонимный Telegram ID и список лекарств — без имени, фото и контактов.
          Если хочешь сделать перерыв, лучше поставить лекарства на паузу — данные сохранятся.
        </p>
        {deleted ? (
          <p className="account-deleted-msg">Данные удалены. До свидания 👋</p>
        ) : !confirmDeleteAccount ? (
          <button
            className="btn-delete-account"
            onClick={() => setConfirmDeleteAccount(true)}
          >
            Удалить все мои данные
          </button>
        ) : (
          <div className="account-delete-confirm">
            <p className="account-delete-warn">
              История приёмов, расписание и все лекарства исчезнут навсегда.
            </p>
            <button
              className="btn-delete-account btn-delete-account--confirm"
              disabled={deleteAccount.isPending}
              onClick={() =>
                deleteAccount.mutate(undefined, {
                  onSuccess: () => setDeleted(true),
                })
              }
            >
              Да, удалить навсегда
            </button>
            <button
              className="btn-cancel-delete"
              onClick={() => setConfirmDeleteAccount(false)}
            >
              Отмена
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
