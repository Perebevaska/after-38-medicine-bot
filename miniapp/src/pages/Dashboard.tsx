import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import { Check, X } from 'lucide-react'
import { useToday, useLogIntake } from '../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { TodayItem } from '../api/types'
import { randomWish } from '../wishes'

const MEAL: Record<string, string> = {
  before: 'До еды',
  after: 'После еды',
  with: 'Во время еды',
  any: 'Не важно',
  no_meal: 'Не зависит',
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

// ── Health bar persistence ─────────────────────────────────────────────────
// health bar — оставлено для будущего
// const HP_KEY = 'wish_hp'
// const HP_TS_KEY = 'wish_hp_ts'
// const DEPLETE_PER_MS = 200 / (11 * 1000) // Шкала 0–200: 0–100 = рамка, 100–200 = текст; полный разряд за 11 с
// const loadHp = (): number => { try { const h = parseFloat(localStorage.getItem(HP_KEY) ?? '0'); const ts = parseInt(localStorage.getItem(HP_TS_KEY) ?? '0', 10); if (!ts) return Math.max(0, h); return Math.max(0, h - (Date.now() - ts) * DEPLETE_PER_MS) } catch { return 0 } }
// const saveHp = (h: number): void => { localStorage.setItem(HP_KEY, String(h)); localStorage.setItem(HP_TS_KEY, String(Date.now())) }
// ──────────────────────────────────────────────────────────────────────────

let _pid = 0

export type WishCardHandle = { celebrate: () => void; skipped: () => void }

const WishCard = forwardRef<WishCardHandle>(function WishCard(_, ref) {
  const [wish, setWish] = useState(randomWish)
  // hp и setHp отключены (заливка/рамка), оставлены для будущего
  // const [hp, setHp] = useState(loadHp)
  const [particles, setParticles] = useState<HeartParticle[]>([])
  const [shaking, setShaking] = useState(false)
  const heartRef = useRef<HTMLSpanElement>(null)

  // Обновляем hp каждые 200 мс — нужно для быстрого drain (11 с)
  // useEffect(() => {
  //   const id = setInterval(() => setHp(loadHp), 200)
  //   return () => clearInterval(id)
  // }, [])

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
    setTimeout(() => setParticles((p) => p.filter((pt) => !ids.has(pt.id))), maxDur)
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
    setTimeout(() => setParticles((p) => p.filter((pt) => !ids.has(pt.id))), maxDur)
  }

  const skipped = () => {
    setShaking(true)
    setTimeout(() => setShaking(false), 580)
    spawnBrokenHearts()
  }

  useImperativeHandle(ref, () => ({ celebrate, skipped }))

  // next (смена пожелания + hp через кнопку) — отключено; оставлено для будущего
  // const next = () => {
  //   celebrate()
  //   setHp(() => { ... })
  // }

  // Фаза 1 (0–100): рамка. Фаза 2 (100–200): текст
  // const borderPct = Math.min(hp, 100)   // отключено, оставлено для будущего
  // const textPct   = Math.max(0, hp - 100) // отключено, оставлено для будущего

  return (
    <>
      <div className="wish-card">
        {/* <span className="wish-border-top"    style={{ width: `${borderPct}%` }} /> */}
        {/* <span className="wish-border-bottom" style={{ width: `${borderPct}%` }} /> */}
        <div className="wish-text-wrap">
          <span className="wish-text">{wish}</span>
          {/* wish-text-hp (заливка текста) — отключено, оставлено для будущего
          <span
            className="wish-text wish-text-hp"
            aria-hidden="true"
            style={{ clipPath: `inset(0 ${(100 - textPct).toFixed(1)}% 0 0)` }}
          >
            {wish}
          </span>
          */}
        </div>
        <span ref={heartRef} className={`wish-heart${shaking ? ' wish-heart--shake' : ''}`} aria-hidden="true">❤️</span>
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

function isDue(reminderTime: string): boolean {
  const now = new Date()
  const [h, m] = reminderTime.split(':').map(Number)
  return now.getHours() * 60 + now.getMinutes() >= h * 60 + m
}

const itemKey = (i: TodayItem) => `${i.medication_id}-${i.reminder_time}`
const isDuePending = (i: TodayItem) => i.status === 'pending' && isDue(i.reminder_time)

function MedCard({
  item,
  exiting,
  entering,
  onTaken,
  onSkipped,
}: {
  item: TodayItem
  exiting?: boolean
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
  const extraClass = exiting ? ' mlist-card--exit' : entering ? ' mlist-card--enter' : ''

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

  // exitingMap: снапшоты due-pending элементов, пока играет exit-анимация
  const [exitingMap, setExitingMap] = useState<Map<string, TodayItem>>(new Map())
  // enteringIds: ключи элементов, только что появившихся в секции others
  const [enteringIds, setEnteringIds] = useState<Set<string>>(new Set())
  const prevDataRef = useRef<TodayItem[]>([])
  // per-item таймеры анимации: отменяем при быстром undo
  const animTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>[]>>(new Map())

  const clearAnimForKey = (k: string) => {
    animTimersRef.current.get(k)?.forEach(clearTimeout)
    animTimersRef.current.delete(k)
  }

  useEffect(() => {
    if (!data) return
    const prevData = prevDataRef.current
    const prevDueKeys = new Set(prevData.filter(isDuePending).map(itemKey))
    const currentDueKeys = new Set(data.filter(isDuePending).map(itemKey))

    // Undo: элемент вернулся в due-pending — отменяем его анимацию выхода
    setExitingMap((prev) => {
      const toCancel = [...prev.keys()].filter((k) => currentDueKeys.has(k))
      if (!toCancel.length) return prev
      toCancel.forEach(clearAnimForKey)
      const next = new Map(prev)
      toCancel.forEach((k) => next.delete(k))
      return next
    })
    setEnteringIds((prev) => {
      const toCancel = [...prev].filter((k) => currentDueKeys.has(k))
      if (!toCancel.length) return prev
      const next = new Set(prev)
      toCancel.forEach((k) => next.delete(k))
      return next
    })

    // Элементы, которые только что покинули due-pending группу
    const justLeft = prevData.filter(
      (i) => prevDueKeys.has(itemKey(i)) && !currentDueKeys.has(itemKey(i))
    )

    if (justLeft.length > 0) {
      setExitingMap((prev) => {
        const next = new Map(prev)
        justLeft.forEach((i) => next.set(itemKey(i), i))
        return next
      })

      justLeft.forEach((item) => {
        const k = itemKey(item)
        clearAnimForKey(k)

        const t1 = setTimeout(() => {
          setExitingMap((prev) => {
            const next = new Map(prev)
            next.delete(k)
            return next
          })
          setEnteringIds((prev) => new Set([...prev, k]))

          const t2 = setTimeout(() => {
            setEnteringIds((prev) => {
              const next = new Set(prev)
              next.delete(k)
              return next
            })
            animTimersRef.current.delete(k)
          }, 320)

          animTimersRef.current.set(k, [t2])
        }, 260)

        animTimersRef.current.set(k, [t1])
      })
    }

    prevDataRef.current = data
  }, [data])

  const allItems = data ?? []

  // Due-секция: дедупликация через Map (реальный элемент приоритетнее снапшота)
  const dueItemsMap = new Map<string, TodayItem>()
  allItems.filter(isDuePending).forEach((i) => dueItemsMap.set(itemKey(i), i))
  exitingMap.forEach((item, key) => { if (!dueItemsMap.has(key)) dueItemsMap.set(key, item) })
  const dueItems = [...dueItemsMap.values()].sort((a, b) => b.reminder_time.localeCompare(a.reminder_time))

  // Others-секция: не-due + не-exiting
  const otherItems = allItems.filter(
    (i) => !isDuePending(i) && !exitingMap.has(itemKey(i))
  )

  // Реальные due-pending (без снапшотов) — для кнопки и handleTakeAll
  const trueDuePending = allItems.filter(isDuePending)

  const handleTakeAll = async () => {
    if (!trueDuePending.length) return
    setTakingAll(true)
    wishRef.current?.celebrate()
    qc.setQueryData<TodayItem[]>(['today'], (old) =>
      old?.map((item) =>
        isDuePending(item) ? { ...item, status: 'taken' as const } : item
      )
    )
    try {
      await Promise.all(
        trueDuePending.map((item) =>
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
      setTakingAll(false)
    }
  }

  const hasAny = dueItems.length > 0 || otherItems.length > 0

  return (
    <div className="page">
      <WishCard ref={wishRef} />

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
                    exiting={exitingMap.has(itemKey(item))}
                    onTaken={() => wishRef.current?.celebrate()}
                    onSkipped={() => wishRef.current?.skipped()}
                  />
                ))}
              </div>
            </>
          )}

          {trueDuePending.length >= 2 && (
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
                    entering={enteringIds.has(itemKey(item))}
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
