import { useAdherence, useStreak } from '../api/hooks'
import { getInitDataRaw } from '../api/client'

const SLOT_LABEL: Record<string, string> = {
  plan: 'Расписание',
  week: 'Неделя',
  adherence: 'Соблюдение',
  doctor: 'Для врача',
}

function pctColor(pct: number): string {
  if (pct >= 80) return '#4caf50'
  if (pct >= 50) return '#ff9800'
  return '#f44336'
}

async function downloadPdf(slot: string) {
  const raw = getInitDataRaw()
  if (!raw) return
  const url = `/api/export/${slot}`
  const res = await fetch(url, {
    headers: { Authorization: `tma ${encodeURIComponent(raw)}` },
  })
  if (!res.ok) return
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${slot}.pdf`
  a.click()
  URL.revokeObjectURL(a.href)
}

export default function StatsPage() {
  const { data: streakData, isLoading: streakLoading } = useStreak()
  const { data: adherence, isLoading: adherenceLoading } = useAdherence()

  const ownerStreak = streakData?.find((s) => s.dependent_id === null)?.streak ?? 0
  const depStreaks = streakData?.filter((s) => s.dependent_id !== null) ?? []
  const totalPct = adherence?.total_pct
  const meds = adherence?.medications ?? []

  return (
    <div className="page">
      <h2 className="section-title">Серия</h2>

      {streakLoading && <p className="hint">Загрузка…</p>}
      {!streakLoading && (
        <div className="stats-streak-block">
          <div className="streak-row">
            <span className="streak-fire">🔥</span>
            <span className="streak-count">{ownerStreak}</span>
            <span className="streak-label">дней подряд</span>
          </div>
          {depStreaks.map((s) => (
            <div key={s.dependent_id} className="streak-row streak-row--dep">
              <span className="streak-fire">🔥</span>
              <span className="streak-count">{s.streak}</span>
              <span className="streak-label">{s.name}</span>
            </div>
          ))}
        </div>
      )}

      <h2 className="section-title">Соблюдение (30 дней)</h2>

      {adherenceLoading && <p className="hint">Загрузка…</p>}
      {!adherenceLoading && meds.length === 0 && (
        <p className="hint">Нет данных</p>
      )}
      {!adherenceLoading && meds.length > 0 && (
        <div className="stats-adh-block">
          {totalPct !== null && totalPct !== undefined && (
            <div className="adh-total">
              <span className="adh-total-label">Всего</span>
              <span className="adh-total-pct" style={{ color: pctColor(totalPct) }}>
                {totalPct}%
              </span>
            </div>
          )}
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
                <div
                  className="adh-bar-fill"
                  style={{ width: `${m.pct}%`, background: pctColor(m.pct) }}
                />
              </div>
              <span className="adh-counts">{m.taken} из {m.due}</span>
            </div>
          ))}
        </div>
      )}

      <h2 className="section-title">Отчёты PDF</h2>
      <div className="pdf-buttons">
        {Object.entries(SLOT_LABEL).map(([slot, label]) => (
          <button
            key={slot}
            className="btn-pdf"
            onClick={() => downloadPdf(slot)}
          >
            📄 {label}
          </button>
        ))}
      </div>
    </div>
  )
}
