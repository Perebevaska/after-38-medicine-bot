import { useState, useRef, useEffect } from 'react'
import { Send, Flame, Trophy, Clock, Lock, Check, ClipboardList, Calendar, Stethoscope, Loader2, AlertTriangle, Pill, Target, Handshake, type LucideIcon } from 'lucide-react'
import { useAdherence, useStreak, useSendExport, useStatsOverview, useSettings } from '../api/hooks'
import type { StreakItem, StatsOverview, WeeklyAdherence, AchievementsBlock } from '../api/types'

// Коды, по которым тост уже показан в этой сессии — защита от повтора при
// ремаунте вкладки с кэш-ответом (newly остаётся в кэше React Query).
const _toasted = new Set<string>()

function pctColor(pct: number): string {
  if (pct >= 80) return '#4caf50'
  if (pct >= 50) return '#ff9800'
  return '#f44336'
}

function pluralDays(n: number): string {
  const n10 = n % 10, n100 = n % 100
  if (n10 === 1 && n100 !== 11) return 'день'
  if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return 'дня'
  return 'дней'
}

function pluralMeds(n: number): string {
  const n10 = n % 10, n100 = n % 100
  if (n10 === 1 && n100 !== 11) return 'препарат'
  if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return 'препарата'
  return 'препаратов'
}

// ─── Нагрузка по терапии ──────────────────────────────────────────────────

function LoadCard({ load }: { load: StatsOverview['load'] }) {
  if (load.meds === 0) return null
  return (
    <div className="stats-card load-card">
      <div className="load-item">
        <span className="load-num">{load.meds}</span>
        <span className="load-label">{pluralMeds(load.meds)}</span>
      </div>
      <div className="load-item">
        <span className="load-num">{load.intakes_per_day}</span>
        <span className="load-label">приёмов в день</span>
      </div>
      <div className="load-item">
        <span className="load-num">{load.units_per_week}</span>
        <span className="load-label">единиц в неделю</span>
      </div>
    </div>
  )
}

// ─── Серии ────────────────────────────────────────────────────────────────

function StreakCard({
  current, best, depStreaks,
}: {
  current: number
  best: number
  depStreaks: StreakItem[]
}) {
  return (
    <div className="stats-card streak-card">
      <div className="streak-main">
        <span className="streak-fire"><Flame size={20} strokeWidth={2} /></span>
        <span className="streak-big">{current}</span>
        <span className="streak-unit">{pluralDays(current)} подряд</span>
      </div>
      <div className="streak-best"><Trophy size={14} strokeWidth={2} className="ic" /> Лучший результат — {best} {pluralDays(best)}</div>
      {depStreaks.map((s) => (
        <div key={s.dependent_id} className="streak-dep">
          <Flame size={13} strokeWidth={2} className="ic" /> {s.streak} · {s.name}
        </div>
      ))}
    </div>
  )
}

// ─── Соблюдение: окна 7/30/90 + график по дням ────────────────────────────

function shortDate(iso: string): string {
  const [, m, d] = iso.split('-')
  return `${Number(d)}.${m}`
}

function WeeklyGraph({ weekly }: { weekly: WeeklyAdherence[] }) {
  const last = weekly.length - 1
  return (
    <div className="adh-week">
      <div className="adh-week-title">Соблюдение по неделям</div>
      <div className="adh-week-bars" role="img" aria-label="Соблюдение по неделям">
        {weekly.map((w, i) => (
          <div key={w.start} className="adh-week-col" title={`${shortDate(w.start)}–${shortDate(w.end)}: ${w.pct === null ? 'нет приёмов' : w.pct + '%'}`}>
            <span className="adh-week-pct">{w.pct === null ? '' : `${w.pct}%`}</span>
            <div className="adh-week-track">
              {w.pct === null
                ? <div className="adh-week-fill adh-week-fill--empty" />
                : <div className="adh-week-fill" style={{ height: `${Math.max(w.pct, 4)}%`, background: pctColor(w.pct) }} />}
            </div>
            <span className="adh-week-x">{i === 0 ? shortDate(w.start) : i === last ? 'тек.' : ''}</span>
          </div>
        ))}
      </div>
      <div className="adh-legend">
        <span><i className="lg-dot" style={{ background: '#4caf50' }} />≥80%</span>
        <span><i className="lg-dot" style={{ background: '#ff9800' }} />50–79%</span>
        <span><i className="lg-dot" style={{ background: '#f44336' }} />&lt;50%</span>
      </div>
    </div>
  )
}

function WinCell({ label, pct }: { label: string; pct: number | null }) {
  return (
    <div className="win-cell">
      <span className="win-label">{label}</span>
      {pct === null
        ? <span className="win-pct win-pct--empty">—</span>
        : <span className="win-pct" style={{ color: pctColor(pct) }}>{pct}%</span>}
    </div>
  )
}

function AdherenceCard({ adherence }: { adherence: StatsOverview['adherence'] }) {
  const { windows, weekly } = adherence
  const hasData = weekly.some((w) => w.due > 0)
  return (
    <div className="stats-card adh-card">
      <h3 className="adh-title">Соблюдение приёма</h3>
      <p className="adh-sub">Доля вовремя принятых препаратов от запланированных</p>
      <div className="win-row">
        <WinCell label="7 дней" pct={windows['7']} />
        <WinCell label="30 дней" pct={windows['30']} />
        <WinCell label="90 дней" pct={windows['90']} />
      </div>
      {hasData
        ? <WeeklyGraph weekly={weekly} />
        : <p className="hint">Начни отмечать приёмы — здесь появится график</p>}
    </div>
  )
}

// ─── Пунктуальность отметок ───────────────────────────────────────────────

function DistRow({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="dist-row">
      <span className="dist-label">{label}</span>
      <div className="dist-track">
        <div className="dist-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="dist-pct">{pct}%</span>
    </div>
  )
}

function PunctualityCard({ punct }: { punct: StatsOverview['punctuality'] }) {
  const hasWorst = punct.worst_hour !== null
  const hasDist = punct.ontime_pct !== null
  if (!hasWorst && !hasDist) return null
  const hh = (h: number) => `${String(h).padStart(2, '0')}:00`
  return (
    <div className="stats-card punct-card">
      <h3 className="punct-title">Пунктуальность отметок</h3>
      {hasDist ? (
        <>
          <p className="punct-sub">Когда отмечаешь приём относительно плана:</p>
          <DistRow label="Вовремя" pct={punct.ontime_pct!} color="#4caf50" />
          <DistRow label="Позже" pct={punct.late_pct!} color="#ff9800" />
          <p className="punct-hint">«Вовремя» — в течение 30 мин после напоминания; «Позже» — спустя 30 мин</p>
        </>
      ) : (
        <p className="punct-sub">Пока мало отметок для распределения</p>
      )}
      {hasWorst && (
        <div className="punct-worst">
          <Clock size={14} strokeWidth={2} className="ic" /> Самый проблемный час — <b>{hh(punct.worst_hour!)}</b> ({punct.worst_hour_skip_pct}% пропусков)
        </div>
      )}
      <p className="punct-note">Учитывается время нажатия отметки, не реального приёма</p>
    </div>
  )
}

// ─── Достижения (F12a) ────────────────────────────────────────────────────

// Ф18: медальон вместо эмодзи. code → {глиф группы, уровень-градиент}.
// Уровни по сложности: bronze→silver→gold→diamond; забота — бренд-бирюза.
const ACH_VISUAL: Record<string, { tier: string; Icon: LucideIcon }> = {
  intake_10:  { tier: 'bronze',  Icon: Pill },
  intake_100: { tier: 'silver',  Icon: Pill },
  intake_500: { tier: 'gold',    Icon: Pill },
  streak_7:   { tier: 'bronze',  Icon: Flame },
  streak_30:  { tier: 'silver',  Icon: Flame },
  streak_100: { tier: 'diamond', Icon: Flame },
  adh_30:     { tier: 'silver',  Icon: Target },
  adh_90:     { tier: 'gold',    Icon: Target },
  care_first: { tier: 'care',    Icon: Handshake },
}

function AchMedal({ code, locked, large }: { code: string; locked: boolean; large?: boolean }) {
  const v = ACH_VISUAL[code]
  const cls = `ach-medal${large ? ' ach-medal--lg' : ''}`
  const sz = large ? 26 : 22
  if (locked || !v) {
    return <span className={`${cls} ach-medal--locked`}><Lock size={sz} strokeWidth={2} /></span>
  }
  const { tier, Icon } = v
  return <span className={`${cls} ach-medal--${tier}`}><Icon size={sz} strokeWidth={2} /></span>
}

function AchievementsCard({ block }: { block: AchievementsBlock }) {
  const [selected, setSelected] = useState<string | null>(null)
  const unlocked = new Set(block.unlocked)
  const got = unlocked.size
  const total = block.catalog.length
  const sel = selected ? block.catalog.find((a) => a.code === selected) : null
  const selOn = sel ? unlocked.has(sel.code) : false
  return (
    <div className="stats-card ach-card">
      <h3 className="ach-title">Достижения <span className="ach-count">{got} / {total}</span></h3>
      <div className="ach-grid">
        {block.catalog.map((a) => {
          const on = unlocked.has(a.code)
          return (
            <button
              key={a.code}
              type="button"
              className={`ach-badge${on ? '' : ' ach-badge--locked'}${selected === a.code ? ' ach-badge--sel' : ''}`}
              onClick={() => setSelected((c) => (c === a.code ? null : a.code))}
            >
              <AchMedal code={a.code} locked={!on} />
              <span className="ach-name">{a.title}</span>
            </button>
          )
        })}
      </div>
      {sel && (
        <div className="ach-hint">
          <AchMedal code={sel.code} locked={!selOn} large />
          <div className="ach-hint-body">
            <span className="ach-hint-title">{sel.title}</span>
            <span className="ach-hint-desc">{sel.desc}</span>
            <span className={`ach-hint-state${selOn ? ' ach-hint-state--on' : ''}`}>
              {selOn ? <><Check size={13} strokeWidth={2.5} className="ic" /> Получено</> : 'Ещё не получено'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function AchievementToast({ block }: { block: AchievementsBlock }) {
  const [shown, setShown] = useState<{ code: string; title: string; extra: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const fresh = block.newly.filter((c) => !_toasted.has(c))
    if (fresh.length === 0) return
    fresh.forEach((c) => _toasted.add(c))
    const first = block.catalog.find((a) => a.code === fresh[0])
    if (!first) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShown({ code: first.code, title: first.title, extra: fresh.length - 1 })
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setShown(null), 4500)
  }, [block.newly, block.catalog])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  if (!shown) return null
  return (
    <div className="ach-toast" role="status">
      <span className="ach-toast-icon"><AchMedal code={shown.code} locked={false} /></span>
      <div className="ach-toast-body">
        <span className="ach-toast-head">Новое достижение!</span>
        <span className="ach-toast-title">
          {shown.title}{shown.extra > 0 && ` +${shown.extra}`}
        </span>
      </div>
    </div>
  )
}

// ─── Report row ───────────────────────────────────────────────────────────

type ReportDef = { slot: string; icon: LucideIcon; title: string }

const REPORTS: ReportDef[] = [
  { slot: 'plan',      icon: ClipboardList, title: 'Расписание на неделю' },
  { slot: 'week',      icon: Calendar,      title: 'История за 7 дней' },
  { slot: 'doctor',    icon: Stethoscope,   title: 'Отчёт для врача' },
]

function ReportRow({ slot, icon: Icon, title }: ReportDef) {
  const { mutate, isPending, isError, reset } = useSendExport()
  const [sent, setSent] = useState(false)
  const sentTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (sentTimerRef.current) clearTimeout(sentTimerRef.current) }, [])

  const handleSend = () => {
    mutate(slot, {
      onSuccess: () => {
        setSent(true)
        if (sentTimerRef.current) clearTimeout(sentTimerRef.current)
        sentTimerRef.current = setTimeout(() => { setSent(false); reset() }, 3000)
      },
    })
  }

  return (
    <div className="report-row">
      <span className="report-row-icon"><Icon size={18} strokeWidth={2} /></span>
      <span className="report-row-title">{title}</span>
      <button
        className={`report-send-btn${sent ? ' report-send-btn--sent' : ''}${isError ? ' report-send-btn--err' : ''}`}
        onClick={handleSend}
        disabled={isPending}
      >
        {isPending ? <Loader2 size={15} strokeWidth={2} className="spin" /> : sent ? <Check size={15} strokeWidth={2.5} /> : isError ? <AlertTriangle size={15} strokeWidth={2} /> : <Send size={15} strokeWidth={2} />}
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────

export default function StatsPage() {
  const { data: overview, isLoading: overviewLoading } = useStatsOverview()
  const { data: streakData } = useStreak()
  const { data: adherence, isLoading: adherenceLoading } = useAdherence()
  const { data: settings } = useSettings()

  const caregiverEnabled = !!settings?.caregiver_enabled
  const depStreaks = caregiverEnabled
    ? (streakData?.filter((s) => s.dependent_id !== null) ?? [])
    : []
  const allMeds = adherence?.medications ?? []
  const meds = caregiverEnabled ? allMeds : allMeds.filter((m) => !m.dependent_name)

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Прогресс</span>
      </div>

      {overviewLoading && <p className="hint">Загрузка…</p>}
      {!overviewLoading && overview && (
        <>
          <StreakCard
            current={overview.streak.current}
            best={overview.streak.best}
            depStreaks={depStreaks}
          />
          <LoadCard load={overview.load} />
          <AdherenceCard adherence={overview.adherence} />
          <PunctualityCard punct={overview.punctuality} />
          {overview.achievements && (
            <>
              <AchievementsCard block={overview.achievements} />
              <AchievementToast block={overview.achievements} />
            </>
          )}
        </>
      )}

      <h2 className="section-title">По препаратам</h2>
      {adherenceLoading && <p className="hint">Загрузка…</p>}
      {!adherenceLoading && meds.length === 0 && (
        <p className="hint">Начни отмечать приёмы — и здесь появится твой прогресс</p>
      )}
      {!adherenceLoading && meds.length > 0 && (
        <div className="stats-adh-block">
          {meds.map((m) => (
            <div key={m.medication_id} className="adh-row">
              <div className="adh-row-header">
                <span className="adh-name">
                  {m.name}
                  {m.dependent_name && <span className="adh-dep"> · {m.dependent_name}</span>}
                </span>
                <span className="adh-pct" style={{ color: pctColor(m.pct) }}>{m.pct}%</span>
              </div>
              <div className="adh-bar-bg">
                <div className="adh-bar-fill" style={{ width: `${m.pct}%`, background: pctColor(m.pct) }} />
              </div>
              <span className="adh-counts">{m.taken} из {m.due}</span>
            </div>
          ))}
        </div>
      )}

      <h2 className="section-title">Отчёты</h2>
      <p className="section-hint">Файл придёт прямо в чат с ботом</p>
      <div className="reports-list">
        {REPORTS.map((r) => (
          <ReportRow key={r.slot} {...r} />
        ))}
      </div>
    </div>
  )
}
