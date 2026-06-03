import { useState, useRef, useEffect } from 'react'
import { Pencil, Pause, Play, Package, Trash2, Plus } from 'lucide-react'
import { useMedications, useDeleteMedication, usePauseMedication } from '../api/hooks'
import { apiErrorMessage } from '../api/client'
import type { Medication } from '../api/types'
import { StockExpanded } from './StockPage'

const MEAL: Record<string, string> = {
  before: 'До еды',
  after: 'После еды',
  with: 'Во время еды',
  any: 'Не важно',
}

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

type CardView = 'collapsed' | 'actions' | 'stock' | 'confirm-delete'

const CLOSE_MS = 220

function MedCard({ med, onEdit }: { med: Medication; onEdit: (id: number) => void }) {
  const [view, setView] = useState<CardView>('collapsed')
  const [isOpen, setIsOpen] = useState(false)
  const { mutate: del, isPending: delPending } = useDeleteMedication()
  const { mutate: pause, isPending: pausePending } = usePauseMedication()
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (closeTimerRef.current) clearTimeout(closeTimerRef.current) }, [])

  const open = () => { setView('actions'); setIsOpen(true) }
  const close = () => {
    setIsOpen(false)
    if (closeTimerRef.current) clearTimeout(closeTimerRef.current)
    closeTimerRef.current = setTimeout(() => setView('collapsed'), CLOSE_MS)
  }
  const toggle = () => (isOpen ? close() : open())

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
            {med.dependent_name && (
              <span className="mlist-dep"> · {med.dependent_name}</span>
            )}
          </div>
          <div className="mlist-meta">
            {med.rules.some((r) => r.dosage)
              ? <span className="mlist-custom-dosage">своя дозировка</span>
              : med.dosage
            } · {MEAL[med.meal_relation] ?? med.meal_relation}
            {med.stock_qty !== null && med.stock_qty !== undefined && (
              <> · 📦 {med.stock_qty} ед.</>
            )}
          </div>
          {med.rules.length > 0 && (
            <div className="mlist-schedule">{scheduleLabel(med)}</div>
          )}
        </div>
        <span className={`mlist-card-chevron${isOpen ? ' mlist-card-chevron--open' : ''}`}>›</span>
      </div>

      <div className="mlist-card-body">
        <div className="mlist-card-body-inner">
          {view === 'actions' && (
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
                className="mlist-action-btn"
                title="Запас"
                onClick={() => setView('stock')}
              >
                <Package size={18} strokeWidth={2} />
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

          {view === 'stock' && (
            <div className="mlist-stock-section">
              <StockExpanded med={med} />
              <button className="mlist-back-link" onClick={() => setView('actions')}>
                ← Назад
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface Props {
  onAdd: () => void
  onEdit: (id: number) => void
}

export default function MedicationList({ onAdd, onEdit }: Props) {
  const { data, isLoading, error } = useMedications()

  return (
    <div className="page">
      <div className="page-header">
        <span className="page-header-title">Аптечка</span>
        <button className="mlist-add-btn" onClick={onAdd} title="Добавить">
          <Plus size={22} strokeWidth={2} />
        </button>
      </div>

      {isLoading && <p className="hint">Загрузка…</p>}
      {error && <p className="hint error">{apiErrorMessage(error)}</p>}

      {data && data.length === 0 && (
        <div className="mlist-empty">
          <p className="mlist-empty-text">Аптечка пуста</p>
          <button className="btn-primary" onClick={onAdd}>
            Добавить в аптечку
          </button>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="mlist-list">
          {data.map((med) => (
            <MedCard key={med.id} med={med} onEdit={onEdit} />
          ))}
        </div>
      )}
    </div>
  )
}
