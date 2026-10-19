import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Chip } from '../components/ui'
import { models as modelsApi, PROVIDER_LABEL, type Models, type Provider } from '../lib/api'

const HOW: Record<string, string> = {
  groq: 'Add GROQ_API_KEY to .env (console.groq.com). The free tier allows 8,000 tokens a minute; prompts are trimmed to fit.',
  anthropic: 'Add ANTHROPIC_API_KEY to .env (console.anthropic.com) to use Claude for every agent.',
  openai: 'Add OPENAI_API_KEY to .env (platform.openai.com).',
  ollama: 'Runs models on this Mac. Start it, then download a model below.',
  lmstudio: 'Open LM Studio, load a model (gpt-oss-20b is already downloaded), and start the local server on port 1234.',
  mcp: '',
}

export function ModelsPage() {
  const [catalog, setCatalog] = useState<Models | null>(null)
  const load = () => modelsApi.list().then(setCatalog).catch(() => setCatalog(null))
  useEffect(() => {
    load()
  }, [])
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Models</h1>
          <p className="lede">
            Every agent can use any of these. Pick a default per session on the design page, and give heavier agents
            (the testbench architect) a stronger model under "Per-agent models". Server default:{' '}
            <b className="mono">{catalog?.default ?? 'none'}</b> (set DEFAULT_LLM in .env to change it).
          </p>
        </div>
        <button className="btn" onClick={load}>Refresh</button>
      </div>
      <div className="design-grid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))' }}>
        {(catalog?.providers ?? []).map((p, i) => (
          <motion.div key={p.provider} className="card card-pad stack" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <h3 style={{ fontSize: 17 }}>{PROVIDER_LABEL[p.provider]}</h3>
              <Chip tone={p.ready ? 'green' : 'amber'}>
                <span className={`dot ${p.ready ? 'ok' : 'wait'}`} /> {p.ready ? 'ready' : 'not set up'}
              </Chip>
            </div>
            <div className="hint">{p.detail || HOW[p.provider]}</div>
            {p.models.length > 0 && (
              <div className="row wrap" style={{ gap: 5 }}>
                {p.models.slice(0, 18).map((m) => <Chip key={m}>{m}</Chip>)}
              </div>
            )}
            {p.ready && p.provider !== 'mcp' && <TestBox provider={p} />}
            {p.provider === 'mcp' && (
              <pre className="stream" style={{ margin: 0, fontSize: 11.5 }}>
                claude mcp add rtl-coverage -- uv run --directory /path/to/repo python -m mcp_server.server{'\n'}
                then ask Claude Code: "start an adder4 session with model mcp:claude and act as every agent"
              </pre>
            )}
            {p.provider === 'ollama' && <OllamaBox provider={p} onChange={load} />}
          </motion.div>
        ))}
      </div>
    </div>
  )
}

function TestBox(props: { provider: Provider }) {
  const options = Array.from(new Set([...props.provider.models, ...props.provider.suggested]))
  const [model, setModel] = useState(options[0] ?? '')
  const [result, setResult] = useState<string>('')
  const [busy, setBusy] = useState(false)
  const run = async () => {
    setBusy(true)
    setResult('')
    const r = await modelsApi.test(`${props.provider.provider}:${model}`)
    setResult(r.ok ? `✓ answered "${r.reply}" in ${r.seconds}s` : `✕ ${r.error}`)
    setBusy(false)
  }
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row">
        <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
          {options.map((m) => <option key={m}>{m}</option>)}
        </select>
        <button className="btn" disabled={busy || !model} onClick={run}>{busy ? 'Testing…' : 'Test'}</button>
      </div>
      {result && <div className={result.startsWith('✓') ? 'hint' : 'error'}>{result}</div>}
    </div>
  )
}

function OllamaBox(props: { provider: Provider; onChange: () => void }) {
  const running = !props.provider.detail.startsWith('not running')
  const [name, setName] = useState(props.provider.suggested[0] ?? '')
  const [progress, setProgress] = useState<{ status?: string; pct?: number; error?: string } | null>(null)
  const pull = async () => {
    setProgress({ status: 'starting' })
    await modelsApi.pull(name, (p) => {
      if (p.error) setProgress({ error: p.error })
      else setProgress({ status: p.status, pct: p.total ? (100 * (p.completed ?? 0)) / p.total : undefined })
    })
    props.onChange()
  }
  if (!running)
    return (
      <button className="btn btn-primary" onClick={async () => { await modelsApi.startOllama(); setTimeout(props.onChange, 2500) }}>
        Start Ollama
      </button>
    )
  return (
    <div className="stack" style={{ gap: 8, borderTop: '1px solid var(--line)', paddingTop: 12 }}>
      <span className="label">Download a model</span>
      <div className="row wrap" style={{ gap: 5 }}>
        {props.provider.suggested.map((s) => (
          <button key={s} className="chip" style={{ cursor: 'pointer' }} onClick={() => setName(s)}>{s}</button>
        ))}
      </div>
      <div className="row">
        <input className="input mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="qwen2.5-coder:7b" />
        <button className="btn btn-primary" disabled={!name || (progress !== null && !progress.error && progress.status !== 'success')} onClick={pull}>Download</button>
      </div>
      {progress && (
        <div className="stack" style={{ gap: 6 }}>
          {progress.error ? (
            <div className="error">{progress.error}</div>
          ) : (
            <>
              <div className="hint">{progress.status}{progress.pct !== undefined ? ` · ${progress.pct.toFixed(0)}%` : ''}</div>
              {progress.pct !== undefined && (
                <div className="bar"><motion.div animate={{ width: `${progress.pct}%` }} transition={{ duration: 0.3 }} /></div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
