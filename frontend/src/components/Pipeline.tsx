import { AnimatePresence, motion } from 'motion/react'
import type { TraceEvent } from '../lib/api'

export const AGENTS = [
  { key: 'planner', title: 'Planner', kind: 'LLM agent', color: 'var(--teal)', soft: 'var(--teal-soft)' },
  { key: 'testbench_architect', title: 'Testbench', kind: 'LLM agent', color: 'var(--teal)', soft: 'var(--teal-soft)' },
  { key: 'assertion_writer', title: 'Assertions', kind: 'LLM agent', color: 'var(--teal)', soft: 'var(--teal-soft)' },
  { key: 'stimulus_writer', title: 'Stimulus', kind: 'LLM agent', color: 'var(--teal)', soft: 'var(--teal-soft)' },
  { key: 'simulator', title: 'Simulator', kind: 'Verilator', color: 'var(--blue)', soft: 'var(--blue-soft)' },
  { key: 'triage', title: 'Triage', kind: 'rules', color: 'var(--amber)', soft: 'var(--amber-soft)' },
  { key: 'coverage_analyst', title: 'Analyst', kind: 'LLM agent', color: 'var(--teal)', soft: 'var(--teal-soft)' },
]

export function Pipeline(props: {
  trace: TraceEvent[]
  active: string | null
  streams: Record<string, string>
  generated: boolean
  onPick?: (agent: string) => void
}) {
  const agents = AGENTS.filter((a) => props.generated || a.key !== 'testbench_architect')
  const last: Record<string, TraceEvent> = {}
  for (const e of props.trace) last[e.agent] = e
  return (
    <div className="pipeline" style={{ gridTemplateColumns: `repeat(${agents.length}, minmax(0, 1fr))` }}>
      {agents.map((a, i) => {
        const e = last[a.key]
        const active = props.active === a.key
        const live = active ? (props.streams[a.key] ?? '').slice(-160) : ''
        const dot = active ? 'live' : e ? (e.kind === 'fallback' ? 'wait' : 'ok') : ''
        return (
          <motion.div
            key={a.key}
            className={`stage ${active ? 'active' : ''}`}
            style={{ ['--stage-color' as string]: a.color, ['--stage-soft' as string]: a.soft, cursor: props.onPick ? 'pointer' : 'default' }}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.04, duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => props.onPick?.(a.key)}
          >
            <span className={`dot stage-dot ${dot}`} style={!dot ? { background: 'var(--line-strong)' } : undefined} />
            <div className="kind">{a.kind}</div>
            <div className="title">{a.title}</div>
            <AnimatePresence mode="wait">
              <motion.div
                key={active ? 'live' : e?.summary ?? 'idle'}
                className="note"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                style={active ? { fontFamily: 'var(--font-mono)', fontSize: 11 } : undefined}
              >
                {active ? live || 'working…' : e?.summary ?? 'waiting'}
              </motion.div>
            </AnimatePresence>
            {active && <div className="stage-glow" />}
          </motion.div>
        )
      })}
    </div>
  )
}
