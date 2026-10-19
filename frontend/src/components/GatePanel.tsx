import { motion } from 'motion/react'
import { useState } from 'react'
import type { Assertion, Gate, Pending, PlanItem } from '../lib/api'
import { CodeView } from './CodeView'
import { GateList } from './GateList'

const TITLES: Record<string, string> = {
  plan: 'Review the verification plan',
  tb_design: 'Review the generated testbench',
  assertions: 'Review the assertions',
  testbench: 'Review the next block of stimulus',
  results: 'Review the results',
  run_simulation: 'Your turn: run the simulation',
  llm_task: 'Waiting for Claude Code',
}

export function GatePanel(props: { pending: Pending; onAnswer: (action: string, feedback: string) => Promise<void> }) {
  const p = props.pending
  const [feedback, setFeedback] = useState('')
  const [busy, setBusy] = useState(false)
  const answer = async (action: string) => {
    setBusy(true)
    try {
      await props.onAnswer(action, feedback)
      setFeedback('')
    } finally {
      setBusy(false)
    }
  }
  return (
    <motion.div className="gate-panel" initial={{ y: 24, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: 10 }}>
        <h3 style={{ fontSize: 16 }}>
          {TITLES[p.step] ?? p.step}
          {p.step === 'llm_task' && <span className="faint" style={{ fontWeight: 400 }}> · {String(p.agent).replace('_', ' ')}</span>}
        </h3>
        <span className="faint mono" style={{ fontSize: 12 }}>iteration {p.iteration}</span>
      </div>
      <div style={{ maxHeight: 360, overflowY: 'auto', marginBottom: 12 }}>
        {p.step === 'plan' && (
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            {(p.plan as PlanItem[]).map((f, i) => (
              <li key={i} style={{ marginBottom: 4 }}>{f.feature}</li>
            ))}
          </ol>
        )}
        {p.step === 'tb_design' && (
          <div className="stack">
            <GateList gates={(p.gates as Gate[]) ?? []} />
            <CodeView value={String(p.sv ?? '')} height={280} />
          </div>
        )}
        {p.step === 'assertions' && <CodeView value={(p.assertions as Assertion[]).map((a) => a.code).join('\n')} height={200} />}
        {p.step === 'testbench' && (
          <div className="stack">
            <div><b>Focus:</b> {String(p.focus ?? '')}</div>
            <CodeView value={String(p.stimulus ?? '')} height={220} />
          </div>
        )}
        {p.step === 'results' && (
          <div className="stack">
            <div className="muted">{String(p.analysis ?? '')}</div>
            {Boolean(p.done) && <div className="hint">The analyst wants to stop: {String(p.stop_reason)}</div>}
          </div>
        )}
        {p.step === 'llm_task' && (
          <div className="stack">
            <div className="muted">
              This session uses <b>mcp:claude</b>: Claude Code answers each agent step through the <code>next_task</code> and{' '}
              <code>answer_task</code> MCP tools. You can also answer as the agent yourself below.
            </div>
            <details>
              <summary className="hint" style={{ cursor: 'pointer' }}>What the agent was asked</summary>
              <pre className="stream" style={{ margin: '8px 0 0', maxHeight: 260 }}>{String(p.prompt ?? '')}</pre>
            </details>
          </div>
        )}
        {p.step === 'run_simulation' && (
          <div className="stack">
            <div className="muted">Run this in a terminal, then continue:</div>
            <pre className="stream" style={{ margin: 0 }}>{String(p.command ?? '')}</pre>
          </div>
        )}
      </div>
      {p.step !== 'run_simulation' && (
        <textarea
          className="textarea"
          placeholder={p.step === 'llm_task' ? 'Answer as this agent, in the format its request asks for' : 'Feedback: why you reject, or guidance for the next step'}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          style={{ marginBottom: 10, minHeight: p.step === 'llm_task' ? 140 : 80 }}
        />
      )}
      <div className="row">
        {p.step === 'llm_task' ? (
          <button className="btn btn-primary" disabled={busy || !feedback.trim()} onClick={() => answer('answer')}>Send answer</button>
        ) : (
          <button className="btn btn-primary" disabled={busy} onClick={() => answer('approve')}>
            {p.step === 'run_simulation' ? 'I ran it' : 'Approve'}
          </button>
        )}
        {p.step !== 'results' && p.step !== 'run_simulation' && p.step !== 'llm_task' && (
          <button className="btn" disabled={busy} onClick={() => answer('reject')}>
            Reject and redo
          </button>
        )}
        {p.step === 'results' && (
          <button className="btn" disabled={busy} onClick={() => answer('stop')}>
            Stop here
          </button>
        )}
      </div>
    </motion.div>
  )
}
