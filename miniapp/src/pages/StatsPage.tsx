import { useState, useRef, useEffect } from 'react'
import { useAdherence, useStreak, useSendExport, useWeekStats, useSettings } from '../api/hooks'
import type { WeekStatRow, StreakItem } from '../api/types'

function pctColor(pct: number): string {
  if (pct >= 80) return '#4caf50'
  if (pct >= 50) return '#ff9800'
  return '#f44336'
}

// ─── Summary card ─────────────────────────────────────────────────────────

function skippedDaysCount(weekRows: WeekStatRow[]): number {
  return new Set(weekRows.filter((r) => r.skipped > 0).map((r) => r.day)).size
}

function SkippedBadge({ count }: { count: number }) {
  let emoji: string, text: string
  if (count === 0) { emoji = '💚'; text = 'Всё под контролем' }
  else if (count <= 2) { emoji = '😕'; text = `${count} дн. с пропусками за неделю` }
  else { emoji = '😟'; text = `${count} дн. с пропусками за неделю` }
  return (
    <div className="skipped-days-badge">
      <span className="skipped-days-emoji">{emoji}</span>
      <span className="skipped-days-text">{text}</span>
    </div>
  )
}

function SummaryCard({
  totalPct, streak, depStreaks, weekRows,
}: {
  totalPct: number | null | undefined
  streak: number
  depStreaks: StreakItem[]
  weekRows: WeekStatRow[]
}) {
  const skipped = weekRows.length ? skippedDaysCount(weekRows) : null
  return (
    <div className="stats-summary-card">
      {totalPct !== null && totalPct !== undefined && (
        <span className="summary-pct" style={{ color: pctColor(totalPct) }}>{totalPct}%</span>
      )}
      {skipped !== null && <SkippedBadge count={skipped} />}
      <div className="summary-streak">
        <span className="streak-fire">🔥</span>
        <span className="summary-streak-count">{streak}</span>
        <span className="summary-streak-label">дней подряд</span>
      </div>
      {depStreaks.map((s) => (
        <div key={s.dependent_id} className="summary-streak summary-streak--dep">
          <span className="streak-fire">🔥</span>
          <span className="summary-streak-count">{s.streak}</span>
          <span className="summary-streak-label">{s.name}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Report row ───────────────────────────────────────────────────────────

type ReportDef = { slot: string; icon: string; title: string }

const REPORTS: ReportDef[] = [
  { slot: 'plan',      icon: '📋', title: 'Расписание на неделю' },
  { slot: 'week',      icon: '📅', title: 'История за 7 дней' },
  { slot: 'adherence', icon: '📊', title: 'Мой прогресс' },
  { slot: 'doctor',    icon: '🩺', title: 'Отчёт для врача' },
]

function ReportRow({ slot, icon, title }: ReportDef) {
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
      <span className="report-row-icon">{icon}</span>
      <span className="report-row-title">{title}</span>
      <button
        className={`report-send-btn${sent ? ' report-send-btn--sent' : ''}${isError ? ' report-send-btn--err' : ''}`}
        onClick={handleSend}
        disabled={isPending}
      >
        {isPending ? '⏳' : sent ? '✅' : isError ? '⚠️' : '→ Tg'}
      </button>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────

export default function StatsPage() {
  const { data: streakData, isLoading: streakLoading } = useStreak()
  const { data: adherence, isLoading: adherenceLoading } = useAdherence()
  const { data: weekRows = [] } = useWeekStats()
  const { data: settings } = useSettings()

  const caregiverEnabled = !!settings?.caregiver_enabled
  const ownerStreak = streakData?.find((s) => s.dependent_id === null)?.streak ?? 0
  const depStreaks = caregiverEnabled
    ? (streakData?.filter((s) => s.dependent_id !== null) ?? [])
    : []
  const totalPct = adherence?.total_pct
  const allMeds = adherence?.medications ?? []
  const meds = caregiverEnabled ? allMeds : allMeds.filter((m) => !m.dependent_name)

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Прогресс</span>
      </div>

      {streakLoading && <p className="hint">Загрузка…</p>}
      {!streakLoading && (
        <SummaryCard
          totalPct={totalPct}
          streak={ownerStreak}
          depStreaks={depStreaks}
          weekRows={weekRows}
        />
      )}

      <h2 className="section-title">По препаратам</h2>
      {adherenceLoading && <p className="hint">Загрузка…</p>}
      {!adherenceLoading && meds.length === 0 && (
        <p className="hint">Начни отмечать приёмы — и здесь появится твой прогресс 💊</p>
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
