import { useState } from 'react'
import { useToday, useLogIntake } from '../api/hooks'
import type { TodayItem } from '../api/types'
import { randomWish } from '../wishes'

const MEAL: Record<string, string> = {
  before: 'До еды',
  after: 'После еды',
  with: 'Во время еды',
  any: 'Не важно',
  no_meal: 'Не зависит',
}

function WishCard() {
  const [wish, setWish] = useState(randomWish)
  const [spinning, setSpinning] = useState(false)

  const next = () => {
    setSpinning(true)
    setWish((w) => randomWish(w))
    setTimeout(() => setSpinning(false), 400)
  }

  return (
    <div className="wish-card">
      <span className="wish-text">{wish}</span>
      <button
        className={`wish-refresh${spinning ? ' wish-refresh--spin' : ''}`}
        onClick={next}
        aria-label="Другое пожелание"
      >
        🔄
      </button>
    </div>
  )
}

function MedCard({ item }: { item: TodayItem }) {
  const { mutate, isPending } = useLogIntake()

  const log = (status: 'taken' | 'skipped') => {
    mutate({
      medication_id: item.medication_id,
      scheduled_time: item.reminder_time,
      status,
    })
  }

  return (
    <div className={`mlist-card${item.status !== 'pending' ? ' mlist-card--paused' : ''}`}>
      <div className="mlist-info">
        <div className="mlist-name">
          {item.name}
          {item.dependent_name && (
            <span className="mlist-dep"> · {item.dependent_name}</span>
          )}
        </div>
        <div className="mlist-meta">
          {item.dosage} · {MEAL[item.meal_relation] ?? item.meal_relation}
        </div>
        <div className="mlist-schedule">{item.reminder_time}</div>
      </div>

      {item.status === 'pending' ? (
        <div className="med-actions">
          <button className="btn-take" onClick={() => log('taken')} disabled={isPending}>✅</button>
          <button className="btn-skip" onClick={() => log('skipped')} disabled={isPending}>❌</button>
        </div>
      ) : (
        <div className="med-status-badge">
          {item.status === 'taken' ? '✅' : '❌'}
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { data, isLoading, error } = useToday()

  return (
    <div className="page">
      <WishCard />

      <h2 className="section-title">Сегодня</h2>

      {isLoading && <p className="hint">Загрузка…</p>}

      {error && (
        <p className="hint error">
          {error.message.includes('401')
            ? 'Откройте приложение через Telegram'
            : error.message}
        </p>
      )}

      {data && data.length === 0 && (
        <p className="hint">На сегодня нет приёмов</p>
      )}

      {data && data.length > 0 && (
        <div className="mlist-list">
          {data.map((item) => (
            <MedCard
              key={`${item.medication_id}-${item.reminder_time}`}
              item={item}
            />
          ))}
        </div>
      )}
    </div>
  )
}
