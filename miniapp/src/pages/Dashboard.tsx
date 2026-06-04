import { useState, useRef, useEffect, forwardRef, useImperativeHandle } from 'react'
import { createPortal } from 'react-dom'
import { Check, X } from 'lucide-react'
import { postEvent } from '@telegram-apps/sdk-react'
import { useToday, useLogIntake, useHearts, useSettings, useMedications } from '../api/hooks'
import { useQueryClient } from '@tanstack/react-query'
import { api, apiErrorMessage } from '../api/client'
import type { TodayItem } from '../api/types'
import { randomWish } from '../wishes'
import { MEAL_LABELS } from '../constants'
import DepSectionTitle from '../components/DepSectionTitle'

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

// Вибрация в конце удержания: нативный Telegram haptic (impact heavy).
// Требует web_app_ready при старте (main.tsx), иначе Android-клиент игнорит событие.
function haptic() {
  try {
    postEvent('web_app_trigger_haptic_feedback', { type: 'impact', impact_style: 'heavy' })
    return
  } catch { /* noop */ }
  // Веб-фоллбэк (вне Telegram)
  try { navigator.vibrate?.(35) } catch { /* noop */ }
}

const HOLD_MS = 600

// Кнопка подтверждения долгим нажатием: при удержании граница заполняется
// по часовой стрелке (зелёная take / красная skip); в конце — onConfirm + вибрация.
// Случайный тап не срабатывает (отпустил раньше → сброс).
function HoldButton({
  variant, onConfirm, disabled, title, children,
}: {
  variant: 'take' | 'skip'
  onConfirm: () => void
  disabled?: boolean
  title?: string
  children: React.ReactNode
}) {
  const [deg, setDeg] = useState(0)
  const rafRef = useRef<number | null>(null)
  const startRef = useRef(0)
  const doneRef = useRef(false)

  const stop = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = null
    startRef.current = 0
    setDeg(0)
  }

  useEffect(() => () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }, [])

  const tick = (t: number) => {
    if (!startRef.current) startRef.current = t
    const p = Math.min(1, (t - startRef.current) / HOLD_MS)
    setDeg(p * 360)
    if (p >= 1) {
      doneRef.current = true
      haptic()
      onConfirm()
      stop()
      return
    }
    rafRef.current = requestAnimationFrame(tick)
  }

  const start = (e: React.PointerEvent) => {
    if (disabled) return
    e.preventDefault()
    doneRef.current = false
    startRef.current = 0
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(tick)
  }

  const cancel = () => {
    if (!doneRef.current && rafRef.current) stop()
  }

  return (
    <button
      type="button"
      className={`btn-${variant} hold-btn`}
      title={title}
      disabled={disabled}
      style={{ '--hold-deg': `${deg}deg` } as React.CSSProperties}
      onPointerDown={start}
      onPointerUp={cancel}
      onPointerLeave={cancel}
      onPointerCancel={cancel}
      onContextMenu={(e) => e.preventDefault()}
    >
      {children}
    </button>
  )
}

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

  // Undo убран намеренно: отмена приёма ломала «курс завершён» (COUNT taken).
  // Приём подтверждается долгим нажатием — случайный тап не отметит.
  const log = (status: 'taken' | 'skipped') => {
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
  const statusClass = item.status === 'skipped'
    ? ' mlist-card--skipped'
    : item.status === 'taken'
    ? ' mlist-card--taken'
    : ''

  return (
    <div
      className={`mlist-card${statusClass}${due ? ' mlist-card--due' : ''}${extraClass}`}
    >
      <div className="mlist-info">
        <div className="mlist-name">
          {item.name}
        </div>
        <div className="mlist-meta">
          {item.dosage} · {MEAL_LABELS[item.meal_relation] ?? item.meal_relation}
        </div>
        <div className="mlist-schedule">{item.reminder_time}</div>
      </div>

      {item.status === 'pending' ? (
        <div className="med-actions">
          <HoldButton variant="take" onConfirm={() => log('taken')} disabled={isPending} title="Удерживайте, чтобы принять">
            <Check size={20} strokeWidth={2.5} />
          </HoldButton>
          <HoldButton variant="skip" onConfirm={() => log('skipped')} disabled={isPending} title="Удерживайте, чтобы пропустить">
            <X size={20} strokeWidth={2.5} />
          </HoldButton>
        </div>
      ) : (
        <div className="med-actions">
          <span className={`med-status med-status--${item.status}`} aria-hidden="true">
            {item.status === 'taken' ? <Check size={20} strokeWidth={2.5} /> : <X size={20} strokeWidth={2.5} />}
          </span>
        </div>
      )}
    </div>
  )
}

export default function Dashboard({ onNavigate }: { onNavigate?: (p: 'medications') => void }) {
  const { data, isLoading, error } = useToday()
  const { data: meds } = useMedications()
  const { data: settings } = useSettings()
  const qc = useQueryClient()
  const [takingAll, setTakingAll] = useState(false)
  const [tzBannerDismissed, setTzBannerDismissed] = useState(false)
  const wishRef = useRef<WishCardHandle>(null)

  const allItems = data ?? []
  // F7: separate own items from linked dependents' items
  const ownItems = allItems.filter((i) => !i.linked_user_id && !i.dep_share_id && !i.dependent_id)
  // Свои локальные близкие — отдельным блоком (как F7/F8)
  const localDepItems = allItems.filter((i) => !i.linked_user_id && !i.dep_share_id && !!i.dependent_id)
  const linkedItems = allItems.filter((i) => !!i.linked_user_id)
  const sharedDepItems = allItems.filter((i) => !!i.dep_share_id)

  // Группировка своих локальных близких по dependent_id
  const localDepGroups = localDepItems.reduce<Record<number, { name: string; items: TodayItem[] }>>((acc, item) => {
    const did = item.dependent_id!
    if (!acc[did]) acc[did] = { name: item.dependent_name ?? `№${did}`, items: [] }
    acc[did].items.push(item)
    return acc
  }, {})

  // Group linked items by linked_user_id
  const linkedGroups = linkedItems.reduce<Record<number, { name: string; items: TodayItem[] }>>((acc, item) => {
    const uid = item.linked_user_id!
    if (!acc[uid]) acc[uid] = { name: item.linked_user_name ?? `id${uid}`, items: [] }
    acc[uid].items.push(item)
    return acc
  }, {})

  // F8: group shared dep items by dep_share_id
  const sharedDepGroups = sharedDepItems.reduce<Record<number, { name: string; items: TodayItem[] }>>((acc, item) => {
    const did = item.dep_share_id!
    if (!acc[did]) acc[did] = { name: item.dep_share_name ?? `dep${did}`, items: [] }
    acc[did].items.push(item)
    return acc
  }, {})

  const dueItems = ownItems
    .filter(isDuePending)
    .sort((a, b) => b.reminder_time.localeCompare(a.reminder_time))
  const otherItems = ownItems.filter((i) => !isDuePending(i))

  const handleTakeAll = async () => {
    if (!dueItems.length) return
    setTakingAll(true)
    wishRef.current?.celebrate()
    const prev = qc.getQueryData<TodayItem[]>(['today'])
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
    } catch {
      if (prev) qc.setQueryData(['today'], prev)
    } finally {
      await qc.invalidateQueries({ queryKey: ['today'] })
      await qc.invalidateQueries({ queryKey: ['streak'] })
      await qc.invalidateQueries({ queryKey: ['adherence'] })
      await qc.invalidateQueries({ queryKey: ['hearts'] })
      setTakingAll(false)
    }
  }

  const hasAny = dueItems.length > 0 || otherItems.length > 0
  const hasLinked = linkedItems.length > 0
  const hasSharedDeps = sharedDepItems.length > 0

  const showTzBanner = !tzBannerDismissed && settings?.timezone === 'UTC'

  return (
    <div className="page">
      {showTzBanner && (
        <div className="tz-banner">
          <span className="tz-banner-text">
            🌍 Похоже, часовой пояс не задан — напоминания могут приходить не вовремя.
            Зайди в <b>Настройки</b> и выбери свой город 🕐
          </span>
          <button className="tz-banner-close" onClick={() => setTzBannerDismissed(true)} aria-label="Закрыть">
            <X size={16} strokeWidth={2.5} />
          </button>
        </div>
      )}
      <WishCard ref={wishRef} />

      {isLoading && <p className="hint">Загрузка…</p>}

      {error && <p className="hint error">{apiErrorMessage(error)}</p>}

      {data && data.length === 0 && (() => {
        const ownMeds = (meds ?? []).filter((m) => !m.linked_user_id && !m.dep_share_id)
        if (ownMeds.length === 0) {
          return (
            <div className="empty-state">
              <p className="empty-state-title">💊 Пока нет препаратов</p>
              <p className="empty-state-text">Добавьте первый — и я напомню о приёмах вовремя.</p>
              <button type="button" className="empty-state-link" onClick={() => onNavigate?.('medications')}>
                В Аптечку →
              </button>
            </div>
          )
        }
        if (ownMeds.every((m) => m.paused)) {
          return (
            <div className="empty-state">
              <p className="empty-state-title">⏸️ Все препараты на паузе</p>
              <p className="empty-state-text">Напоминания не приходят. Снимите паузу, когда будете готовы.</p>
              <button type="button" className="empty-state-link" onClick={() => onNavigate?.('medications')}>
                В Аптечку →
              </button>
            </div>
          )
        }
        return <p className="hint">На сегодня нет приёмов</p>
      })()}

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
                💊 Принять всё
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

      {/* Свои локальные близкие — активные карточки (владелец отмечает приём) */}
      {Object.entries(localDepGroups).map(([did, group]) => (
        <div key={did}>
          <DepSectionTitle name={group.name} />
          <div className="mlist-list">
            {group.items.map((item) => (
              <MedCard
                key={itemKey(item)}
                item={item}
                onTaken={() => wishRef.current?.celebrate()}
                onSkipped={() => wishRef.current?.skipped()}
              />
            ))}
          </div>
        </div>
      ))}

      {/* F7: read-only sections for linked dependents */}
      {hasLinked && Object.entries(linkedGroups).map(([uid, group]) => (
        <div key={uid}>
          <DepSectionTitle name={group.name} account />
          <div className="mlist-list">
            {group.items.map((item) => (
              <div
                key={itemKey(item)}
                className={`mlist-card${item.status === 'skipped' ? ' mlist-card--skipped' : item.status === 'taken' ? ' mlist-card--taken' : ''}${item.is_due && item.status === 'pending' ? ' mlist-card--due' : ''}`}
              >
                <div className="mlist-info">
                  <div className="mlist-name">{item.name}</div>
                  <div className="mlist-meta">
                    {item.dosage}
                  </div>
                  <div className="mlist-schedule">{item.reminder_time}</div>
                </div>
                <div className="med-actions">
                  {item.status === 'pending' ? (
                    <>
                      <button className="btn-take" disabled><Check size={18} strokeWidth={2.5} /></button>
                      <button className="btn-skip" disabled><X size={18} strokeWidth={2.5} /></button>
                    </>
                  ) : (
                    <button className="btn-undo" disabled>
                      {item.status === 'taken' ? <Check size={18} strokeWidth={2.5} /> : <X size={18} strokeWidth={2.5} />}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* F8: shared local dependents — помощник №2 отмечает приёмы (CRUD-доступ) */}
      {hasSharedDeps && Object.entries(sharedDepGroups).map(([did, group]) => (
        <div key={did}>
          <DepSectionTitle name={group.name} />
          <div className="mlist-list">
            {group.items.map((item) => (
              <MedCard
                key={itemKey(item)}
                item={item}
                onTaken={() => wishRef.current?.celebrate()}
                onSkipped={() => wishRef.current?.skipped()}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
