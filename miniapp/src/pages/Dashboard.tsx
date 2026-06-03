import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import { Check, X } from 'lucide-react'
import { useToday, useLogIntake, useHearts } from '../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { api, apiErrorMessage } from '../api/client'
import type { TodayItem } from '../api/types'
import { randomWish } from '../wishes'

const MEAL: Record<string, string> = {
  before: 'До еды',
  after: 'После еды',
  with: 'Во время еды',
  any: 'Не важно',
}

interface HeartParticle {
  id: number
  x: number
  y: number
  dx: number
  dy: number
  size: number
  dur: number
  emoji?: string
}

let _pid = 0

export type WishCardHandle = { celebrate: () => void; skipped: () => void }

const WishCard = forwardRef<WishCardHandle>(function WishCard(_, ref) {
  const [wish, setWish] = useState(randomWish)
  const [particles, setParticles] = useState<HeartParticle[]>([])
  const [shaking, setShaking] = useState(false)
  const heartRef = useRef<HTMLSpanElement>(null)
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => () => { timersRef.current.forEach(clearTimeout) }, [])

  const addTimer = (fn: () => void, ms: number) => {
    const id = setTimeout(fn, ms)
    timersRef.current.push(id)
    return id
  }
  // G1: счётчик сердечек рядом с ❤️
  const { data: heartsData } = useHearts()
  const hearts = heartsData?.hearts ?? 0

  const spawnHearts = () => {
    const rect = heartRef.current?.getBoundingClientRect()
    if (!rect) return
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const count = 13
    const batch: HeartParticle[] = Array.from({ length: count }, () => {
      const angle = Math.random() * Math.PI * 2
      const dist = 65 + Math.random() * 140
      return {
        id: ++_pid,
        x: cx,
        y: cy,
        dx: Math.cos(angle) * dist,
        dy: Math.sin(angle) * dist,
        size: 9 + Math.random() * 13,
        dur: 520 + Math.random() * 380,
      }
    })
    setParticles((p) => [...p, ...batch])
    const maxDur = Math.max(...batch.map((p) => p.dur)) + 60
    const ids = new Set(batch.map((p) => p.id))
    addTimer(() => setParticles((p) => p.filter((pt) => !ids.has(pt.id))), maxDur)
  }

  const celebrate = () => {
    setWish((w) => randomWish(w))
    spawnHearts()
  }

  const spawnBrokenHearts = () => {
    const rect = heartRef.current?.getBoundingClientRect()
    if (!rect) return
    const cx = rect.left + rect.width / 2
    const cy = rect.top + rect.height / 2
    const batch: HeartParticle[] = Array.from({ length: 3 }, () => ({
      id: ++_pid,
      x: cx,
      y: cy,
      dx: (Math.random() - 0.5) * 50,
      dy: 65 + Math.random() * 55,
      size: 14 + Math.random() * 6,
      dur: 480 + Math.random() * 180,
      emoji: '💔',
    }))
    setParticles((p) => [...p, ...batch])
    const maxDur = Math.max(...batch.map((p) => p.dur)) + 60
    const ids = new Set(batch.map((p) => p.id))
    addTimer(() => setParticles((p) => p.filter((pt) => !ids.has(pt.id))), maxDur)
  }

  const skipped = () => {
    setShaking(true)
    addTimer(() => setShaking(false), 580)
    spawnBrokenHearts()
  }

  useImperativeHandle(ref, () => ({ celebrate, skipped }))

  return (
    <>
      <div className="wish-card">
        <div className="wish-text-wrap">
          <span className="wish-text">{wish}</span>
        </div>
        <span className="wish-heart-wrap">
          <span ref={heartRef} className={`wish-heart${shaking ? ' wish-heart--shake' : ''}`} aria-hidden="true">❤️</span>
          <span className="wish-heart-count">{hearts}</span>
        </span>
      </div>
      {createPortal(
        <div className="hearts-overlay" aria-hidden="true">
          {particles.map((p) => (
            <span
              key={p.id}
              className="heart-particle"
              style={{
                left: p.x,
                top: p.y,
                fontSize: p.size,
                '--dx': `${p.dx}px`,
                '--dy': `${p.dy}px`,
                '--dur': `${p.dur}ms`,
              } as React.CSSProperties}
            >
              {p.emoji ?? '❤️'}
            </span>
          ))}
        </div>,
        document.body
      )}
    </>
  )
})

const itemKey = (i: TodayItem) => `${i.medication_id}-${i.reminder_time}`
// AX5: is_due приходит с сервера (TZ аккаунта), не считаем по времени браузера.
const isDuePending = (i: TodayItem) => i.status === 'pending' && i.is_due

function MedCard({
  item,
  entering,
  onTaken,
  onSkipped,
}: {
  item: TodayItem
  entering?: boolean
  onTaken?: () => void
  onSkipped?: () => void
}) {
  const { mutate, isPending } = useLogIntake()

  const log = (status: 'taken' | 'skipped' | 'pending') => {
    if (status === 'taken') onTaken?.()
    if (status === 'skipped') onSkipped?.()
    mutate({
      medication_id: item.medication_id,
      scheduled_time: item.reminder_time,
      status,
    })
  }

  const due = isDuePending(item)
  const extraClass = entering ? ' mlist-card--enter' : ''

  return (
    <div
      className={`mlist-card${item.status !== 'pending' ? ' mlist-card--paused' : ''}${due ? ' mlist-card--due' : ''}${extraClass}`}
    >
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
          <button className="btn-take" onClick={() => log('taken')} disabled={isPending}><Check size={18} strokeWidth={2.5} /></button>
          <button className="btn-skip" onClick={() => log('skipped')} disabled={isPending}><X size={18} strokeWidth={2.5} /></button>
        </div>
      ) : (
        <div className="med-actions">
          <button
            className="btn-undo"
            onClick={() => log('pending')}
            disabled={isPending}
            title="Отменить отметку"
          >
            {item.status === 'taken' ? <Check size={18} strokeWidth={2.5} /> : <X size={18} strokeWidth={2.5} />}
          </button>
        </div>
      )}
    </div>
  )
}

export default function Dashboard() {
  const { data, isLoading, error } = useToday()
  const qc = useQueryClient()
  const [takingAll, setTakingAll] = useState(false)
  const wishRef = useRef<WishCardHandle>(null)

  // Render полностью из data — без снапшотов/таймеров анимации (источник
  // дублирования карточек). Переход due→others анимируется CSS на mount
  // карточки в секции «Сегодня» (mlist-card--enter, играет один раз).
  const allItems = data ?? []
  const dueItems = allItems
    .filter(isDuePending)
    .sort((a, b) => b.reminder_time.localeCompare(a.reminder_time))
  const otherItems = allItems.filter((i) => !isDuePending(i))

  const handleTakeAll = async () => {
    if (!dueItems.length) return
    setTakingAll(true)
    wishRef.current?.celebrate()
    qc.setQueryData<TodayItem[]>(['today'], (old) =>
      old?.map((item) =>
        isDuePending(item) ? { ...item, status: 'taken' as const } : item
      )
    )
    try {
      await Promise.all(
        dueItems.map((item) =>
          api.post('/today/intake', {
            medication_id: item.medication_id,
            scheduled_time: item.reminder_time,
            status: 'taken',
          })
        )
      )
    } finally {
      await qc.invalidateQueries({ queryKey: ['today'] })
      await qc.invalidateQueries({ queryKey: ['streak'] })
      await qc.invalidateQueries({ queryKey: ['adherence'] })
      await qc.invalidateQueries({ queryKey: ['hearts'] })
      setTakingAll(false)
    }
  }

  const hasAny = dueItems.length > 0 || otherItems.length > 0

  return (
    <div className="page">
      <WishCard ref={wishRef} />

      {isLoading && <p className="hint">Загрузка…</p>}

      {error && <p className="hint error">{apiErrorMessage(error)}</p>}

      {data && data.length === 0 && (
        <p className="hint">На сегодня нет приёмов</p>
      )}

      {data && hasAny && (
        <>
          {dueItems.length > 0 && (
            <>
              <h2 className="section-title">Сейчас</h2>
              <div className="mlist-list">
                {dueItems.map((item) => (
                  <MedCard
                    key={itemKey(item)}
                    item={item}
                    onTaken={() => wishRef.current?.celebrate()}
                    onSkipped={() => wishRef.current?.skipped()}
                  />
                ))}
              </div>
            </>
          )}

          {dueItems.length >= 2 && (
            <div className="take-all-row">
              <button
                className="btn-take-all"
                onClick={handleTakeAll}
                disabled={takingAll}
              >
                💊 Выпил всё
              </button>
            </div>
          )}

          {otherItems.length > 0 && (
            <>
              <h2 className="section-title">Сегодня</h2>
              <div className="mlist-list">
                {otherItems.map((item) => (
                  <MedCard
                    key={itemKey(item)}
                    item={item}
                    entering
                    onTaken={() => wishRef.current?.celebrate()}
                    onSkipped={() => wishRef.current?.skipped()}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
