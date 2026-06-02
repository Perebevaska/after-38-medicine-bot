import { useState, useEffect } from 'react'
import { useSettings, useSetReminderMode, useSetPreset, useSetDailyPlan, useSetCaregiver } from '../api/hooks'

const PRESET_SLOTS = [
  { slot: 'morning', label: 'Утро', field: 'time_morning' as const },
  { slot: 'lunch',   label: 'День',  field: 'time_lunch'   as const },
  { slot: 'evening', label: 'Вечер', field: 'time_evening' as const },
  { slot: 'night',   label: 'Ночь',  field: 'time_night'   as const },
]

export default function SettingsPage() {
  const { data, isLoading } = useSettings()
  const setMode = useSetReminderMode()
  const setPreset = useSetPreset()
  const setDailyPlan = useSetDailyPlan()
  const setCaregiver = useSetCaregiver()

  const [presets, setPresets] = useState<Record<string, string>>({})
  const [dailyPlanTime, setDailyPlanTime] = useState('08:00')

  useEffect(() => {
    if (!data) return
    setPresets({
      morning: data.time_morning,
      lunch:   data.time_lunch,
      evening: data.time_evening,
      night:   data.time_night,
    })
    setDailyPlanTime(data.daily_plan_time ?? '08:00')
  }, [data])

  if (isLoading) return <div className="page"><p className="hint">Загрузка…</p></div>
  if (!data) return <div className="page"><p className="hint">Нет данных</p></div>

  const handlePresetBlur = (slot: string) => {
    const time = presets[slot]
    if (time) setPreset.mutate({ slot, time })
  }

  const handleDailyPlanTimeBlur = () => {
    setDailyPlan.mutate({ enabled: !!data.daily_plan_enabled, time: dailyPlanTime })
  }

  return (
    <div className="page">
      <h2 className="section-title">Пресеты времени</h2>
      <div className="settings-block">
        {PRESET_SLOTS.map(({ slot, label }) => (
          <div key={slot} className="settings-row">
            <span className="settings-label">{label}</span>
            <input
              type="time"
              className="settings-time-input"
              value={presets[slot] ?? ''}
              onChange={(e) => setPresets((p) => ({ ...p, [slot]: e.target.value }))}
              onBlur={() => handlePresetBlur(slot)}
            />
          </div>
        ))}
      </div>

      <h2 className="section-title">Напоминания</h2>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Режим</span>
          <div className="toggle-group">
            <button
              className={`toggle-btn${data.reminder_mode === 'once' ? ' toggle-btn--active' : ''}`}
              onClick={() => setMode.mutate('once')}
            >
              Однократно
            </button>
            <button
              className={`toggle-btn${data.reminder_mode === 'repeat' ? ' toggle-btn--active' : ''}`}
              onClick={() => setMode.mutate('repeat')}
            >
              Повтор
            </button>
          </div>
        </div>
      </div>

      <h2 className="section-title">Ежедневный план</h2>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Включён</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.daily_plan_enabled}
              onChange={(e) => setDailyPlan.mutate({ enabled: e.target.checked, time: dailyPlanTime })}
            />
            <span className="toggle-track" />
          </label>
        </div>
        {!!data.daily_plan_enabled && (
          <div className="settings-row">
            <span className="settings-label">Время плана</span>
            <input
              type="time"
              className="settings-time-input"
              value={dailyPlanTime}
              onChange={(e) => setDailyPlanTime(e.target.value)}
              onBlur={handleDailyPlanTimeBlur}
            />
          </div>
        )}
      </div>

      <h2 className="section-title">Режим опекуна</h2>
      <div className="settings-block">
        <div className="settings-row">
          <span className="settings-label">Управление подопечными</span>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={!!data.caregiver_enabled}
              onChange={(e) => setCaregiver.mutate(e.target.checked)}
            />
            <span className="toggle-track" />
          </label>
        </div>
      </div>

      <div className="settings-footer">
        <span className="hint">Часовой пояс: {data.timezone}</span>
      </div>
    </div>
  )
}
