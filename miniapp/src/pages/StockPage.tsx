import { useRef, useState, useEffect } from 'react'
import {
  useStock,
  useSetStock,
  useAddStock,
  useSetStockUnits,
  useSetStockThreshold,
  useDisableStock,
} from '../api/hooks'
import type { Medication } from '../api/types'

function daysClass(daysLeft: number, threshold: number): string {
  if (daysLeft <= Math.max(1, Math.floor(threshold / 2))) return 'stock-status--critical'
  if (daysLeft <= threshold) return 'stock-status--low'
  return 'stock-status--ok'
}

function daysLabel(n: number): string {
  if (n === 1) return '1 день'
  if (n >= 2 && n <= 4) return `${n} дня`
  return `${n} дней`
}

export function StockExpanded({ med }: { med: Medication }) {
  const { data, isLoading } = useStock(med.id)
  const mutSet = useSetStock()
  const mutAdd = useAddStock()
  const mutUnits = useSetStockUnits()
  const mutThreshold = useSetStockThreshold()
  const mutDisable = useDisableStock()

  const [addAmt, setAddAmt] = useState('')
  const [stockQty, setStockQty] = useState('')
  const [unitsVal, setUnitsVal] = useState('')
  const [threshVal, setThreshVal] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const initialized = useRef(false)

  useEffect(() => {
    if (!data || initialized.current) return
    initialized.current = true
    /* eslint-disable react-hooks/set-state-in-effect */
    if (data.stock_qty !== null && data.stock_qty !== undefined) {
      setStockQty(String(data.stock_qty))
    }
    setUnitsVal(String(data.units_per_dose ?? 1))
    setThreshVal(String(data.low_stock_days ?? 5))
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [data])

  if (isLoading) return <p className="stock-loading">Загрузка…</p>

  const hasStock = data?.stock_qty !== null && data?.stock_qty !== undefined
  const daysLeft = data?.days_left
  const threshold = data?.low_stock_days ?? 5
  const isSaving = mutSet.isPending || mutUnits.isPending || mutThreshold.isPending

  const handleSave = () => {
    const qty = parseFloat(stockQty)
    if (!isNaN(qty) && qty >= 0) mutSet.mutate({ medId: med.id, qty })
    const u = parseFloat(unitsVal)
    if (!isNaN(u) && u > 0) mutUnits.mutate({ medId: med.id, units: u })
    const t = parseInt(threshVal, 10)
    if (!isNaN(t) && t > 0) mutThreshold.mutate({ medId: med.id, days: t })
  }

  const handleToggle = () => {
    if (hasStock) {
      mutDisable.mutate(med.id)
      setSettingsOpen(false)
    } else {
      initialized.current = false
      mutSet.mutate({ medId: med.id, qty: 0 })
    }
  }

  return (
    <div className="stock-expanded">
      {/* Тоггл — всегда виден */}
      <div className="stock-toggle-row">
        <span className="stock-toggle-label">Учёт запаса</span>
        <button
          className={`stock-toggle ${hasStock ? 'stock-toggle--on' : 'stock-toggle--off'}`}
          disabled={mutDisable.isPending || mutSet.isPending}
          onClick={handleToggle}
        />
      </div>

      {/* Основное содержимое — только когда включён */}
      {hasStock && (
        <>
          {daysLeft !== null && daysLeft !== undefined && (
            <div className={`stock-days-badge ${daysClass(daysLeft, threshold)}`}>
              ~{daysLabel(daysLeft)} осталось
            </div>
          )}

          <div className="stock-row">
            <span className="stock-row-label">Докупил(а)</span>
            <input
              className="field-input field-input--short"
              type="number"
              inputMode="decimal"
              min="0"
              value={addAmt}
              onChange={(e) => setAddAmt(e.target.value)}
              placeholder="0"
            />
            <button
              className="stock-btn"
              disabled={mutAdd.isPending || addAmt === ''}
              onClick={() => {
                const amount = parseFloat(addAmt)
                if (!isNaN(amount) && amount > 0) {
                  mutAdd.mutate({ medId: med.id, amount }, { onSuccess: () => setAddAmt('') })
                }
              }}
            >
              +
            </button>
          </div>

          {/* Скрытые настройки */}
          <button
            className="stock-settings-toggle"
            onClick={() => setSettingsOpen((v) => !v)}
          >
            <span>Настройки</span>
            <span className={`stock-settings-chevron${settingsOpen ? ' stock-settings-chevron--open' : ''}`}>›</span>
          </button>

          {settingsOpen && (
            <div className="stock-settings">
              <div className="stock-row">
                <span className="stock-row-label">Запас (ед.)</span>
                <input
                  className="field-input field-input--short"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  value={stockQty}
                  onChange={(e) => setStockQty(e.target.value)}
                  placeholder="—"
                />
              </div>
              <div className="stock-row">
                <span className="stock-row-label">Ед. за приём</span>
                <input
                  className="field-input field-input--short"
                  type="number"
                  inputMode="decimal"
                  min="0.1"
                  step="0.5"
                  value={unitsVal}
                  onChange={(e) => setUnitsVal(e.target.value)}
                />
              </div>
              <div className="stock-row">
                <span className="stock-row-label">
                  Предупредить за
                  <span className="stock-row-sublabel"> (дней до конца)</span>
                </span>
                <input
                  className="field-input field-input--short"
                  type="number"
                  inputMode="numeric"
                  min="1"
                  value={threshVal}
                  onChange={(e) => setThreshVal(e.target.value)}
                />
              </div>
              <button className="btn-primary" disabled={isSaving} onClick={handleSave}>
                Сохранить
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

