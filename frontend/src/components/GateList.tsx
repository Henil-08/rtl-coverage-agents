import { AnimatePresence, motion } from 'motion/react'
import type { Gate } from '../lib/api'

const NAMES: Record<string, string> = {
  structure: 'Structure',
  compile: 'Compiles',
  golden_run: 'Golden run (random stimulus)',
  coverage_reachable: 'Every coverpoint reachable',
  mutant_smoke: 'Catches planted bugs',
  uvm_structure: 'UVM structure',
  uvm_compile: 'UVM compiles',
  uvm_golden_run: 'UVM golden run',
  uvm_matches_sv: 'UVM matches SV coverage',
  uvm: 'UVM testbench',
}

export function GateList(props: { gates: Gate[] }) {
  if (!props.gates.length) return <div className="hint">Gates appear here as the testbench is checked.</div>
  return (
    <div className="gates">
      <AnimatePresence initial={false}>
        {props.gates.map((g, i) => (
          <motion.div key={i} className="gate" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.25 }}>
            <motion.span
              initial={{ scale: 0.4 }}
              animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 500, damping: 20 }}
              style={{ color: g.ok ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}
            >
              {g.ok ? '✓' : '✕'}
            </motion.span>
            <div>
              <div style={{ fontWeight: 500 }}>{NAMES[g.gate] ?? g.gate}</div>
              {g.detail && <div className="gate-detail">{g.detail}</div>}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
