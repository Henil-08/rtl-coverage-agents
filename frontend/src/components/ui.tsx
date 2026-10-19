import { motion } from 'motion/react'
import { useId, type ReactNode } from 'react'

export function Segmented<T extends string>(props: {
  value: T
  options: { value: T; label: string; disabled?: boolean }[]
  onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <div className="seg" role="group">
      {props.options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={props.value === o.value}
          disabled={o.disabled}
          onClick={() => props.onChange(o.value)}
        >
          {props.value === o.value && (
            <motion.span layoutId={`seg-${id}`} className="seg-thumb" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />
          )}
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Switch(props: { on: boolean; onChange: (v: boolean) => void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className="switch" style={{ opacity: props.disabled ? 0.5 : 1 }}>
      <span
        className={`switch-track ${props.on ? 'on' : ''}`}
        role="switch"
        aria-checked={props.on}
        tabIndex={0}
        onClick={() => !props.disabled && props.onChange(!props.on)}
        onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && !props.disabled && props.onChange(!props.on)}
      >
        <motion.span
          className="switch-knob"
          style={{ display: 'block' }}
          animate={{ x: props.on ? 15 : 0 }}
          transition={{ type: 'spring', stiffness: 600, damping: 35 }}
        />
      </span>
      <span>{props.label}</span>
    </label>
  )
}

export function Tabs<T extends string>(props: {
  value: T
  tabs: { value: T; label: ReactNode; badge?: ReactNode }[]
  onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <div className="tabs" role="tablist">
      {props.tabs.map((t) => (
        <button key={t.value} role="tab" className="tab" aria-selected={props.value === t.value} onClick={() => props.onChange(t.value)}>
          {t.label}
          {t.badge}
          {props.value === t.value && <motion.span layoutId={`tab-${id}`} className="tab-underline" />}
        </button>
      ))}
    </div>
  )
}

export function Chip(props: { tone?: 'teal' | 'blue' | 'amber' | 'violet' | 'green' | 'red'; children: ReactNode; title?: string }) {
  return (
    <span className={`chip ${props.tone ? `chip-${props.tone}` : ''}`} title={props.title}>
      {props.children}
    </span>
  )
}

export function StatusPill(props: { running: boolean; waiting: boolean; done: boolean; issue?: string }) {
  if (props.running)
    return (
      <Chip tone="teal">
        <span className="dot live" /> running
      </Chip>
    )
  if (props.waiting)
    return (
      <Chip tone="amber">
        <span className="dot wait" /> waiting for you
      </Chip>
    )
  if (props.done)
    return props.issue === 'design_mismatch' || props.issue === 'tb_failed' ? (
      <Chip tone="red">
        <span className="dot bad" /> stopped
      </Chip>
    ) : (
      <Chip tone="green">
        <span className="dot ok" /> done
      </Chip>
    )
  return <Chip>idle</Chip>
}

export const fade = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] as const },
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '–' : `${v.toFixed(digits)}%`
}
