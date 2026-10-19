import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CodeView } from '../components/CodeView'
import { Markdown } from '../components/Markdown'
import { Chip, fade, Segmented, Switch, Tabs } from '../components/ui'
import { ModelPicker } from '../components/ModelPicker'
import { api, models as modelsApi, type Config, type DesignDetail, type Models } from '../lib/api'

const MODE_HELP: Record<string, string> = {
  auto: 'The agents run every step, the simulator included, and stop on their own.',
  approval: 'Pauses after the plan, the testbench, the assertions, every block of stimulus and every result for your OK.',
  manual: 'The agents write each test; you run the generated run.sh yourself and tell them when it has finished.',
}

const AGENT_ROWS: [string, string][] = [
  ['planner', 'Planner'],
  ['testbench_architect', 'Testbench architect'],
  ['assertion_writer', 'Assertion writer'],
  ['stimulus_writer', 'Stimulus writer'],
  ['coverage_analyst', 'Coverage analyst'],
  ['triage', 'Triage explanations'],
]

const STOP_HELP: Record<string, string> = {
  target_pct: 'Stop once this share of functional coverage bins is hit.',
  toggle_target: "Also require this share of the design's signal bits to toggle both ways. 0 ignores toggle coverage.",
  max_iters: 'Hard cap on test-writing rounds.',
  plateau_iters: 'How many recent rounds to look at when deciding the agents are stuck.',
  plateau_delta: 'Stop if neither coverage rose by at least this many points in each of those rounds.',
}

export function DesignPage() {
  const { name = '' } = useParams()
  const nav = useNavigate()
  const [d, setD] = useState<DesignDetail | null>(null)
  const [config, setConfig] = useState<Config | null>(null)
  const [tab, setTab] = useState<'spec' | 'rtl' | 'ports' | 'mutants'>('spec')
  const [error, setError] = useState('')
  const [lang, setLang] = useState<'sv' | 'uvm'>('sv')
  const [source, setSource] = useState<'handwritten' | 'generated'>('handwritten')
  const [mode, setMode] = useState<'auto' | 'approval' | 'manual'>('auto')
  const [useKb, setUseKb] = useState(true)
  const [stop, setStop] = useState<Record<string, number>>({})
  const [showStop, setShowStop] = useState(false)
  const [busy, setBusy] = useState(false)
  const [catalog, setCatalog] = useState<Models | null>(null)
  const [model, setModel] = useState('')
  const [agentModels, setAgentModels] = useState<Record<string, string>>({})
  const [showAgents, setShowAgents] = useState(false)

  useEffect(() => {
    api.design(name).then((x) => {
      setD(x)
      if (!x.handwritten_tb) setSource('generated')
    }).catch((e) => setError(e.message))
    modelsApi.list().then(setCatalog).catch(() => setCatalog(null))
    api.config().then((c) => {
      setConfig(c)
      setStop(Object.fromEntries(Object.entries(c.defaults).filter(([, v]) => typeof v === 'number')) as Record<string, number>)
      setUseKb(Boolean(c.kb))
    })
  }, [name])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const { session_id } = await api.start({
        design: name, mode, language: lang, tb_source: source, use_kb: useKb, model: model || null,
        agent_models: Object.fromEntries(Object.entries(agentModels).filter(([, v]) => v)), ...stop,
      })
      nav(`/sessions/${session_id}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy(false)
    }
  }

  if (error && !d) return <div className="page"><div className="error">{error}</div></div>
  if (!d) return <div className="page"><div className="empty">Loading…</div></div>
  const needsLlm = source === 'generated' && !config?.llm && !model && !agentModels.testbench_architect

  return (
    <div className="page">
      <motion.div className="page-head" {...fade}>
        <div>
          <div className="row" style={{ gap: 8, marginBottom: 6 }}>
            <Chip tone={d.kind === 'upload' ? 'violet' : undefined}>{d.kind === 'upload' ? 'uploaded' : 'built-in'}</Chip>
            <Chip>{d.ports.top}</Chip>
            {d.ports.clock ? <Chip>clock: {d.ports.clock}</Chip> : <Chip>combinational</Chip>}
            {d.ports.reset && <Chip>reset: {d.ports.reset}</Chip>}
          </div>
          <h1>{d.title}</h1>
        </div>
      </motion.div>

      <div className="design-layout">
        <div className="card">
          <div style={{ padding: '0 14px' }}>
            <Tabs
              value={tab}
              onChange={setTab}
              tabs={[
                { value: 'spec', label: 'Spec sheet' },
                { value: 'rtl', label: 'RTL' },
                { value: 'ports', label: `Ports (${d.ports.ports?.length ?? 0})` },
                { value: 'mutants', label: `Mutants (${d.mutants.length})` },
              ]}
            />
          </div>
          <div className="card-pad" style={{ padding: '20px 24px' }}>
            <AnimatePresence mode="wait">
              <motion.div key={tab} {...fade}>
                {tab === 'spec' && <Markdown text={d.spec} />}
                {tab === 'rtl' && (
                  <div className="stack">
                    {Object.entries(d.rtl).map(([file, text]) => (
                      <div key={file}>
                        <div className="mono faint" style={{ fontSize: 12, marginBottom: 6 }}>{file}</div>
                        <CodeView value={text} height={Math.min(620, 22 * text.split('\n').length + 24)} />
                      </div>
                    ))}
                  </div>
                )}
                {tab === 'ports' && (
                  <table className="table">
                    <thead><tr><th>Port</th><th>Direction</th><th>Width</th></tr></thead>
                    <tbody>
                      {d.ports.ports?.map((p) => (
                        <tr key={p.name}><td className="mono">{p.name}</td><td>{p.dir}</td><td className="mono">{p.width}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {tab === 'mutants' && (
                  <table className="table">
                    <thead><tr><th>ID</th><th>Fault</th><th>What changes</th></tr></thead>
                    <tbody>
                      {d.mutants.map((m) => (
                        <tr key={m.id}><td className="mono">{m.id}</td><td><Chip>{m.category}</Chip></td><td>{m.description}</td></tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        </div>

        <motion.div className="card card-pad sticky stack" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} transition={{ duration: 0.3 }}>
          <h3 style={{ fontSize: 17 }}>Run verification</h3>
          <div className="field">
            <span className="label">Testbench</span>
            <Segmented
              value={source}
              onChange={setSource}
              options={[
                { value: 'handwritten', label: 'Hand-written', disabled: !d.handwritten_tb },
                { value: 'generated', label: 'Agent-written' },
              ]}
            />
            <span className="hint">
              {source === 'generated'
                ? 'The testbench architect writes the drivers, reference model and covergroup from the spec, then must pass five gates before tests are built on it.'
                : 'Uses the testbench a person wrote for this design.'}
            </span>
          </div>
          <div className="field">
            <span className="label">Language</span>
            <Segmented value={lang} onChange={setLang} options={[{ value: 'sv', label: 'SystemVerilog' }, { value: 'uvm', label: 'UVM', disabled: !config?.uvm }]} />
            <span className="hint">{lang === 'uvm' ? 'Full UVM bench: about 20 s per build on Verilator.' : 'Module-based bench: about 2 s per build.'}</span>
          </div>
          <div className="field">
            <span className="label">Mode</span>
            <Segmented value={mode} onChange={setMode} options={[{ value: 'auto', label: 'Auto' }, { value: 'approval', label: 'Approval' }, { value: 'manual', label: 'Manual' }]} />
            <span className="hint">{MODE_HELP[mode]}</span>
          </div>
          <div className="field">
            <span className="label">Model</span>
            <ModelPicker catalog={catalog} value={model} onChange={setModel} emptyLabel={`Server default (${config?.llm ?? 'none'})`} />
            <button className="btn btn-ghost btn-sm" onClick={() => setShowAgents(!showAgents)} style={{ paddingLeft: 0, alignSelf: 'flex-start' }}>
              {showAgents ? '▾' : '▸'} Per-agent models
            </button>
            <AnimatePresence>
              {showAgents && (
                <motion.div className="stack" style={{ gap: 8, overflow: 'hidden' }} initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                  <span className="hint">A small model is often enough for stimulus and analysis; give the testbench architect your strongest one.</span>
                  {AGENT_ROWS.map(([key, label]) => (
                    <div key={key} className="field">
                      <label>{label}</label>
                      <ModelPicker catalog={catalog} value={agentModels[key] ?? ''} onChange={(v) => setAgentModels({ ...agentModels, [key]: v })} emptyLabel="Session model" />
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <Switch
            on={useKb}
            onChange={setUseKb}
            disabled={!config?.kb}
            label={<span>Planner reads the knowledge base {config?.kb && <span className="faint">({config.kb.documents} docs)</span>}</span>}
          />
          <div>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowStop(!showStop)} style={{ paddingLeft: 0 }}>
              {showStop ? '▾' : '▸'} When to stop
            </button>
            <AnimatePresence>
              {showStop && (
                <motion.div className="stack" style={{ gap: 10, overflow: 'hidden' }} initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                  {Object.keys(STOP_HELP).map((k) => (
                    <div key={k} className="field">
                      <label>{k.replace('_', ' ').replace('pct', '%').replace('iters', 'iterations')}</label>
                      <input className="input mono" type="number" value={stop[k] ?? ''} onChange={(e) => setStop({ ...stop, [k]: Number(e.target.value) })} />
                      <span className="hint">{STOP_HELP[k]}</span>
                    </div>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          {needsLlm && <div className="error">An agent-written testbench needs an LLM. Set GROQ_API_KEY and restart the server.</div>}
          {error && <div className="error">{error}</div>}
          <button className="btn btn-primary" style={{ justifyContent: 'center', padding: '11px 14px' }} disabled={busy || needsLlm} onClick={start}>
            {busy ? 'Starting…' : 'Start session'}
          </button>
        </motion.div>
      </div>
    </div>
  )
}
