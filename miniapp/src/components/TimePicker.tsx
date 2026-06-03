import { useEffect, useRef } from 'react'

// ─── DrumPicker ──────────────────────────────────────────────────────────────
// Общий компонент выбора времени (барабан HH:MM). Используется в форме
// лекарства и в настройках (повтор / строгий / план / время приёма).

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'))
const DRUM_ITEM_H = 44
const DRUM_PAD = 1

function DrumColumn({ items, value, onChange }: {
  items: string[]
  value: string
  onChange: (v: string) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const fromScroll = useRef(false)
  const selIdx = Math.max(0, items.indexOf(value))

  useEffect(() => {
    if (fromScroll.current) { fromScroll.current = false; return }
    const idx = items.indexOf(value)
    if (idx < 0) return
    const el = ref.current
    if (!el) return
    const top = idx * DRUM_ITEM_H
    const id = setTimeout(() => { el.scrollTop = top }, 0)
    return () => clearTimeout(id)
  }, [value, items])

  const handleScroll = () => {
    if (!ref.current) return
    const idx = Math.max(0, Math.min(
      items.length - 1,
      Math.round(ref.current.scrollTop / DRUM_ITEM_H)
    ))
    if (items[idx] !== value) {
      fromScroll.current = true
      onChange(items[idx])
    }
  }

  return (
    <div className="drum-col">
      <div className="drum-col-fade drum-col-fade--top" />
      <div className="drum-col-fade drum-col-fade--bot" />
      <div className="drum-col-line drum-col-line--top" />
      <div className="drum-col-line drum-col-line--bot" />
      <div className="drum-col-scroll" ref={ref} onScroll={handleScroll}>
        {Array.from({ length: DRUM_PAD }, (_, i) => (
          <div key={`pre${i}`} className="drum-col-item" />
        ))}
        {items.map((item, i) => (
          <div
            key={item}
            className={`drum-col-item${i === selIdx ? ' drum-col-item--sel' : ''}`}
          >
            {item}
          </div>
        ))}
        {Array.from({ length: DRUM_PAD }, (_, i) => (
          <div key={`post${i}`} className="drum-col-item" />
        ))}
      </div>
    </div>
  )
}

export default function TimePicker({ value, onChange }: {
  value: string
  onChange: (v: string) => void
}) {
  const [hh, mm] = value.split(':')
  return (
    <div className="drum-picker">
      <DrumColumn items={HOURS} value={hh ?? '08'} onChange={(h) => onChange(`${h}:${mm ?? '00'}`)} />
      <span className="drum-sep">:</span>
      <DrumColumn items={MINUTES} value={mm ?? '00'} onChange={(m) => onChange(`${hh ?? '08'}:${m}`)} />
    </div>
  )
}
