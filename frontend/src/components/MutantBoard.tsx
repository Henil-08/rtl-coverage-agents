import { motion } from 'motion/react'
import type { MutantResult } from '../lib/api'
import { Chip } from './ui'

export function MutantBoard(props: {
  mutants: { id: string; category: string; description: string }[]
  results: Record<string, MutantResult>
  running: boolean
  selected: string | null
  onSelect: (id: string) => void
}) {
  return (
    <div className="mutants">
      {props.mutants.map((m, i) => {
        const r = props.results[m.id]
        return (
          <motion.div
            key={m.id}
            className="mutant"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0, rotateY: r ? 180 : 0 }}
            transition={{ delay: r ? 0 : i * 0.03, duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => r && props.onSelect(m.id)}
          >
            <div className="mutant-face">
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <b className="mono">{m.id}</b>
                {props.running ? <span className="dot live" /> : <span className="faint" style={{ fontSize: 11 }}>not run</span>}
              </div>
              <Chip>{m.category}</Chip>
              <div className="muted" style={{ fontSize: 12.5 }}>{m.description}</div>
            </div>
            <div className={`mutant-face back ${r?.verdict ?? ''} ${props.selected === m.id ? 'selected' : ''}`}>
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <b className="mono">{m.id}</b>
                <b style={{ color: r?.verdict === 'caught' ? 'var(--green)' : r?.verdict === 'survived' ? 'var(--red)' : 'var(--ink-3)' }}>
                  {r?.verdict}
                </b>
              </div>
              <div className="muted" style={{ fontSize: 12.5 }}>{m.description}</div>
              <div className="row wrap" style={{ gap: 5, marginTop: 'auto' }}>
                {r?.by_assertion && <Chip tone="teal">assertion</Chip>}
                {r?.by_scoreboard && <Chip tone="violet">reference model</Chip>}
              </div>
            </div>
          </motion.div>
        )
      })}
    </div>
  )
}
