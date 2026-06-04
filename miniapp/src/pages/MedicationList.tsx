import { useState, useRef, useEffect } from 'react'
import { Pencil, Pause, Play, Trash2, Plus, CalendarPlus } from 'lucide-react'
import { useMedications, useDeleteMedication, usePauseMedication, useContinueCourse, useSettings } from '../api/hooks'
import { apiErrorMessage } from '../api/client'
import type { Medication } from '../api/types'
import { MEAL_LABELS } from '../constants'
import DepSectionTitle from '../components/DepSectionTitle'

const FREQ: Record<string, string> = {
  daily: 'ежедневно',
  interval: 'раз в N дней',
  weekdays: 'по дням нед.',
  monthly: 'раз в месяц',
}

function scheduleLabel(med: Medication): string {
  if (!med.rules.length) return ''
  const times = med.rules
    .map((r) => (r.dosage ? `${r.reminder_time} (${r.dosage})` : r.reminder_time))
    .join(' · ')
  const freqs = [...new Set(med.rules.map((r) => FREQ[r.frequency] ?? r.frequency))]
  return `${times} (${freqs.join(', ')})`
}

type CardView = 'collapsed' | 'actions' | 'confirm-delete'

const CLOSE_MS = 220

function MedCard({
  med, onEdit, onSchedule, onOpen, forceClose,
}: {
  med: Medication
  onEdit: (id: number) => void
  onSchedule: (id: number) => void
  onOpen: () => void
  forceClose: boolean
}) {
  const [view, setView] = useState<CardView>('collapsed')
  const [isOpen, setIsOpen] = useState(false)
  const { mutate: del, isPending: delPending } = useDeleteMedication()
  const { mutate: pause, isPending: pausePending } = usePauseMedication()
  const { mutate: continueCourse, isPending: contPending } = useContinueCourse()
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const hasSchedule = med.rules.length > 0
  const courseTotal = med.course_total ?? null
  const courseDone = med.course_done ?? 0
  const courseComplete = courseTotal != null && courseDone >= courseTotal
  const hasStock = med.stock_qty !== null && med.stock_qty !== undefined
  // Низкий остаток ≈ менее 3 дней приёма (доза × приёмов/день × 3).
  const lowStock = hasStock && med.stock_qty! <= (med.units_per_dose || 1) * med.times_per_day * 3

  const open = () => { setView('actions'); setIsOpen(true); onOpen() }
  const close = () => {
    setIsOpen(false)
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current)
    closeTimerRef.current = setTimeout(() => setView('collapsed'), CLOSE_MS)
  }
  const toggle = () => (isOpen ? close() : open())

  useEffect(() => () => { if (closeTimerRef.current) clearTimeout(closeTimerRef.current) }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (forceClose && isOpen) close()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [forceClose])

  const handlePause = () => {
    pause({ id: med.id, paused: !med.paused }, { onSuccess: close })
  }

  const handleDelete = () => {
    del(med.id, { onSuccess: close })
  }

  return (
    <div className={`mlist-card mlist-card--col${isOpen ? ' mlist-card--open' : ''}`}>
      <div className="mlist-card-main mlist-card--tappable" onClick={toggle}>
        <div className="mlist-info">
          <div className="mlist-name">
            {med.name}
            {!!med.paused && <span className="mlist-badge-paused">пауза</span>}
            {courseComplete && <span className="mlist-badge-done">курс завершён</span>}
          </div>
          <div className="mlist-meta">
            {med.dosage} · {MEAL_LABELS[med.meal_relation] ?? med.meal_relation}
            {hasStock && (
              <span className={lowStock ? 'mlist-stock mlist-stock--low' : 'mlist-stock'}>
                {' '}· 📦 {med.stock_qty} ед.{lowStock ? ' · мало' : ''}
              </span>
            )}
          </div>
          {hasSchedule && (
            <div className="mlist-schedule">{scheduleLabel(med)}</div>
          )}
          {courseTotal != null && !courseComplete && (
            <div className="mlist-course">Курс: {courseDone}/{courseTotal} приёмов</div>
          )}
          {!hasSchedule && (
            <button
              className="mlist-schedule-add"
              onClick={(e) => { e.stopPropagation(); onSchedule(med.id) }}
            >
              <CalendarPlus size={15} strokeWidth={2} /> Добавить расписание
            </button>
          )}
        </div>
        <span className={`mlist-card-chevron${isOpen ? ' mlist-card-chevron--open' : ''}`}>›</span>
      </div>

      <div className="mlist-card-body">
        <div className="mlist-card-body-inner">
          {view === 'actions' && courseComplete && (
            <div className="mlist-course-done">
              <span className="mlist-course-done-text">✅ Курс пройден ({courseDone}/{courseTotal})</span>
              <div className="mlist-course-done-actions">
                <button
                  className="mlist-course-continue"
                  disabled={contPending}
                  onClick={() => continueCourse(med.id)}
                >
                  Продолжить
                </button>
                <button
                  className="mlist-course-delete"
                  disabled={delPending}
                  onClick={() => del(med.id)}
                >
                  Удалить
                </button>
              </div>
            </div>
          )}

          {view === 'actions' && !courseComplete && (
            <div className="mlist-action-row">
              <button
                className="mlist-action-btn"
                title="Редактировать"
                onClick={() => onEdit(med.id)}
              >
                <Pencil size={18} strokeWidth={2} />
              </button>
              <button
                className="mlist-action-btn"
                title={med.paused ? 'Возобновить' : 'Пауза'}
                onClick={handlePause}
                disabled={pausePending}
              >
                {med.paused ? <Play size={18} strokeWidth={2} /> : <Pause size={18} strokeWidth={2} />}
              </button>
              <button
                className="mlist-action-btn mlist-action-btn--danger"
                title="Удалить"
                onClick={() => setView('confirm-delete')}
              >
                <Trash2 size={18} strokeWidth={2} />
              </button>
            </div>
          )}

          {view === 'confirm-delete' && (
            <div className="mlist-confirm-row">
              <span className="mlist-confirm-text">Удалить «{med.name}»?</span>
              <button
                className="mlist-confirm-yes"
                onClick={handleDelete}
                disabled={delPending}
              >
                Удалить
              </button>
              <button
                className="mlist-confirm-no"
                onClick={() => setView('actions')}
              >
                Нет
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface Props {
  onAdd: (linkedUserId?: number, forDepShareId?: number) => void
  onEdit: (id: number, linkedUserId?: number, forDepShareId?: number) => void
  onSchedule: (id: number, linkedUserId?: number, forDepShareId?: number) => void
}

export default function MedicationList({ onAdd, onEdit, onSchedule }: Props) {
  const { data, isLoading, error } = useMedications()
  const { data: settings } = useSettings()
  const [openMedId, setOpenMedId] = useState<number | null>(null)

  const allMeds = data ?? []
  // Свои лекарства (без близкого)
  const selfMeds = allMeds.filter((m) => !m.linked_user_id && !m.dep_share_id && !m.dependent_id)
  // Свои локальные близкие — отдельным блоком на близкого (единообразие с F7/F8)
  const localDepGroups = allMeds
    .filter((m) => !m.linked_user_id && !m.dep_share_id && m.dependent_id)
    .reduce<Record<number, { name: string; meds: Medication[] }>>((acc, m) => {
      const did = m.dependent_id!
      if (!acc[did]) acc[did] = { name: m.dependent_name ?? `№${did}`, meds: [] }
      acc[did].meds.push(m)
      return acc
    }, {})
  // F7: group linked deps' meds by linked_user_id
  const linkedGroups = (data ?? [])
    .filter((m) => m.linked_user_id)
    .reduce<Record<number, { name: string; meds: Medication[] }>>((acc, m) => {
      const uid = m.linked_user_id!
      if (!acc[uid]) acc[uid] = { name: m.linked_user_name ?? `id${uid}`, meds: [] }
      acc[uid].meds.push(m)
      return acc
    }, {})
  // F8: shared dep sections — from viewing_deps (always show even if no meds yet)
  const viewingDeps = settings?.viewing_deps ?? []
  const sharedDepMedMap = (data ?? [])
    .filter((m) => m.dep_share_id)
    .reduce<Record<number, Medication[]>>((acc, m) => {
      const sid = m.dep_share_id!
      if (!acc[sid]) acc[sid] = []
      acc[sid].push(m)
      return acc
    }, {})
  const hasAny = selfMeds.length > 0 || Object.keys(localDepGroups).length > 0
    || Object.keys(linkedGroups).length > 0 || viewingDeps.length > 0

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Аптечка</span>
        <button className="mlist-add-btn" onClick={() => onAdd()} title="Добавить">
          <Plus size={22} strokeWidth={2} />
        </button>
      </div>

      {isLoading && <p className="hint">Загрузка…</p>}
      {error && <p className="hint error">{apiErrorMessage(error)}</p>}

      {data && !hasAny && (
        <div className="mlist-empty">
          <p className="mlist-empty-text">Здесь пока пусто</p>
          <button className="btn-primary" onClick={() => onAdd()}>
            Добавить препарат
          </button>
        </div>
      )}

      {selfMeds.length > 0 && (
        <div className="mlist-list">
          {selfMeds.map((med) => (
            <MedCard
              key={med.id}
              med={med}
              onEdit={(id) => onEdit(id)}
              onSchedule={(id) => onSchedule(id)}
              onOpen={() => setOpenMedId(med.id)}
              forceClose={openMedId !== null && openMedId !== med.id}
            />
          ))}
        </div>
      )}

      {/* Свои локальные близкие — отдельным блоком (👤 Имя) */}
      {Object.entries(localDepGroups).map(([did, group]) => (
        <div key={did}>
          <DepSectionTitle name={group.name} />
          <div className="mlist-list">
            {group.meds.map((med) => (
              <MedCard
                key={med.id}
                med={med}
                onEdit={(id) => onEdit(id)}
                onSchedule={(id) => onSchedule(id)}
                onOpen={() => setOpenMedId(med.id)}
                forceClose={openMedId !== null && openMedId !== med.id}
              />
            ))}
          </div>
        </div>
      ))}

      {/* F7: linked dependents' sections */}
      {Object.entries(linkedGroups).map(([uid, group]) => (
        <div key={uid}>
          <DepSectionTitle name={group.name} account />
          <div className="mlist-list">
            {group.meds.map((med) => (
              <MedCard
                key={med.id}
                med={med}
                onEdit={(id) => onEdit(id, med.linked_user_id)}
                onSchedule={(id) => onSchedule(id, med.linked_user_id)}
                onOpen={() => setOpenMedId(med.id)}
                forceClose={openMedId !== null && openMedId !== med.id}
              />
            ))}
          </div>
        </div>
      ))}

      {/* F8: shared dep sections (viewer has full CRUD) — always shown even if no meds */}
      {viewingDeps.map((vd) => {
        const meds = sharedDepMedMap[vd.share_id] ?? []
        return (
          <div key={vd.share_id}>
            <DepSectionTitle name={vd.dep_name} />
            {meds.length > 0 ? (
              <div className="mlist-list">
                {meds.map((med) => (
                  <MedCard
                    key={med.id}
                    med={med}
                    onEdit={(id) => onEdit(id, undefined, vd.share_id)}
                    onSchedule={(id) => onSchedule(id, undefined, vd.share_id)}
                    onOpen={() => setOpenMedId(med.id)}
                    forceClose={openMedId !== null && openMedId !== med.id}
                  />
                ))}
              </div>
            ) : (
              <p className="hint mlist-section-empty">Нет препаратов. Добавьте через «+» сверху.</p>
            )}
          </div>
        )
      })}
    </div>
  )
}
