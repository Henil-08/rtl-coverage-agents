import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { CodeView } from '../components/CodeView'
import { GateList } from '../components/GateList'
import { GatePanel } from '../components/GatePanel'
import { Markdown } from '../components/Markdown'
import { MutantBoard } from '../components/MutantBoard'
import { Pipeline } from '../components/Pipeline'
import { BinGrid, CodeBars, CoverageChart, Dial, Timeline } from '../components/Telemetry'
import { Chip, fade, pct, StatusPill, Tabs } from '../components/ui'
import { WaveView } from '../components/WaveView'
import { api, type MutantResult, type Status, type WaveView as WaveData } from '../lib/api'
import { useLive } from '../lib/live'

type View = 'plan' | 'testbench' | 'assertions' | 'stimulus' | 'simulator' | 'analysis' | 'report' | 'waves' | 'mutants'

const FOLLOW: Record<string, View> = {
  planner: 'plan',
  testbench_architect: 'testbench',
  assertion_writer: 'assertions',
  stimulus_writer: 'stimulus',
  simulator: 'simulator',
  triage: 'analysis',
  coverage_analyst: 'analysis',
}

export function SessionPage() {
  const { id = '' } = useParams()
  const live = useLive(id)
  const st = live.status
  const [view, setView] = useState<View>('plan')
  const [follow, setFollow] = useState(true)

  useEffect(() => {
    if (follow && live.activeNode && FOLLOW[live.activeNode]) setView(FOLLOW[live.activeNode])
  }, [live.activeNode, follow])
  useEffect(() => {
    if (live.mutation?.running) {
      setFollow(false)
      setView('mutants')
    }
  }, [live.mutation?.running])

  if (!st) {
    return (
      <div className="page">
        <div className="empty">{live.error ?? 'Connecting to the session…'}</div>
      </div>
    )
  }

  const generated = st.tb_source === 'generated'
  const res = st.result ?? {}
  const toggle = res.code?.toggle
  const pick = (v: View) => {
    setFollow(false)
    setView(v)
  }
  const liveBadge = (agents: string[]) =>
    live.activeNode && agents.includes(live.activeNode) ? <span className="live-badge">LIVE</span> : null

  return (
    <div className="page">
      <motion.div className="session-head" {...fade}>
        <div>
          <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
            <StatusPill running={live.running} waiting={Boolean(live.waiting)} done={st.done} issue={st.issue} />
            <Chip>{st.design}</Chip>
            <Chip tone="blue">{st.language === 'uvm' ? 'UVM' : 'SystemVerilog'}</Chip>
            <Chip tone={generated ? 'teal' : undefined}>{generated ? 'agent-written TB' : 'hand-written TB'}</Chip>
            <Chip>{st.mode} mode</Chip>
            {st.llm_model && <Chip>{st.llm_model}</Chip>}
          </div>
          <h1 style={{ fontSize: 24 }} className="mono">{st.session_id}</h1>
          <p className="lede" style={{ marginTop: 4 }}>{st.stop_reason || (live.running ? 'Agents at work.' : 'In progress.')}</p>
          {st.triage_note && st.done && <div className="error" style={{ marginTop: 8, maxWidth: 820 }}>{st.triage_note}</div>}
        </div>
        <div className="row wrap">
          <button className="btn" disabled={!st.blocks?.length || live.running} onClick={() => api.mutation(id)}>
            Run mutation testing
          </button>
          <a className="btn" href={`/api/sessions/${id}/report.md`} target="_blank" rel="noreferrer">Report</a>
          <a className="btn" href={`/api/sessions/${id}/bundle.zip`}>Download all</a>
        </div>
      </motion.div>

      <Pipeline
        trace={live.trace}
        active={live.activeNode}
        streams={live.streams}
        generated={generated}
        onPick={(a) => FOLLOW[a] && pick(FOLLOW[a])}
      />

      <div className="session-grid">
        <div className="card workbench">
          <div className="workbench-head">
            <Tabs
              value={view}
              onChange={pick}
              tabs={[
                { value: 'plan', label: 'Plan', badge: liveBadge(['planner']) },
                ...(generated ? [{ value: 'testbench' as View, label: 'Testbench', badge: liveBadge(['testbench_architect']) }] : [{ value: 'testbench' as View, label: 'Testbench' }]),
                { value: 'assertions', label: 'Assertions', badge: liveBadge(['assertion_writer']) },
                { value: 'stimulus', label: 'Stimulus', badge: liveBadge(['stimulus_writer']) },
                { value: 'simulator', label: 'Sim', badge: liveBadge(['simulator']) },
                { value: 'analysis', label: 'Analysis', badge: liveBadge(['triage', 'coverage_analyst']) },
                { value: 'waves', label: 'Waves' },
                { value: 'mutants', label: 'Mutants' },
                { value: 'report', label: 'Report' },
              ]}
            />
            <button className={`btn btn-sm ${follow ? '' : 'btn-ghost'}`} style={{ flex: 'none' }} onClick={() => setFollow(!follow)} title="Switch tabs automatically to whatever the agents are doing">
              <span className={`dot ${follow ? 'live' : ''}`} /> follow
            </button>
          </div>
          <div className="workbench-body">
            <AnimatePresence mode="wait">
              <motion.div key={view} {...fade}>
                <WorkbenchView view={view} st={st} live={live} id={id} />
              </motion.div>
            </AnimatePresence>
          </div>
          <AnimatePresence>
            {live.waiting && !live.running && (
              <GatePanel pending={live.waiting} onAnswer={async (action, feedback) => { await api.respond(id, action, feedback) }} />
            )}
          </AnimatePresence>
        </div>

        <div className="telemetry">
          <div className="dials">
            <Dial label="functional" value={res.functional_pct} color="var(--series-1)" />
            <Dial label="toggle" value={toggle?.pct} color="var(--series-2)" />
          </div>
          <div className="card card-pad">
            <div className="card-title">Code coverage</div>
            <CodeBars code={res.code} />
          </div>
          <div className="card card-pad">
            <div className="card-title">Coverage bins</div>
            <BinGrid bins={res.bins} />
          </div>
          <div className="card card-pad">
            <div className="card-title">Per iteration</div>
            <CoverageChart history={st.history ?? []} />
          </div>
          <div className="card card-pad">
            <div className="card-title">Agent timeline</div>
            <Timeline events={live.trace} />
          </div>
        </div>
      </div>
    </div>
  )
}

function Streaming(props: { text: string; on: boolean; language?: string }) {
  if (props.language) return <CodeView value={props.text} language={props.language} follow height={420} />
  return (
    <div className="stream">
      {props.text}
      {props.on && <span className="caret" />}
    </div>
  )
}

function WorkbenchView(props: { view: View; st: Status; live: ReturnType<typeof useLive>; id: string }) {
  const { view, st, live, id } = props
  const writing = (agent: string) => live.activeNode === agent && live.streaming[agent]

  if (view === 'plan') {
    if (writing('planner') || (!st.plan?.length && live.streams.planner))
      return <Streaming text={live.streams.planner ?? ''} on={Boolean(live.streaming.planner)} />
    if (!st.plan?.length) return <div className="empty">The planner reads the spec and the knowledge base first.</div>
    const refs = Object.fromEntries((st.kb_hits ?? []).map((h) => [h.ref, h]))
    return (
      <div>
        {st.plan.map((f, i) => (
          <motion.div key={i} className="feature" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
            <div className="feature-n">{i + 1}</div>
            <div className="stack" style={{ gap: 6 }}>
              <div style={{ fontWeight: 500 }}>{f.feature}</div>
              {f.risk && <div className="muted" style={{ fontSize: 13 }}>Risk: {f.risk}</div>}
              <div className="row wrap" style={{ gap: 5 }}>
                {(f.coverpoints ?? []).map((c) => <Chip key={c}>{c}</Chip>)}
                {(f.sources ?? []).map((s) => (
                  <span key={s} title={refs[s] ? `${refs[s].title}${refs[s].page ? ` p.${refs[s].page}` : ''}\n\n${refs[s].text.slice(0, 400)}…` : s}>
                    <Chip tone="violet">{s}{refs[s] ? ` · ${refs[s].title.slice(0, 28)}` : ''}</Chip>
                  </span>
                ))}
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    )
  }

  if (view === 'testbench') {
    if (st.tb_source !== 'generated') return <CodeView value={st.testbench || 'The testbench appears after the first block of stimulus.'} height={560} />
    const gates = live.gates.length ? live.gates : st.gen_tb?.gates ?? []
    const streaming = writing('testbench_architect')
    return (
      <div className="stack">
        <GateList gates={gates} />
        {streaming || !st.gen_tb?.sv ? (
          <Streaming text={live.streams.testbench_architect ?? 'The testbench architect starts after the plan.'} on={Boolean(streaming)} language="systemverilog" />
        ) : (
          <>
            {st.gen_tb.harness_doc && <div className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: 13 }}>{st.gen_tb.harness_doc}</div>}
            <CodeView value={st.language === 'uvm' && st.gen_tb.uvm ? st.gen_tb.uvm : st.gen_tb.sv ?? ''} height={520} />
          </>
        )}
      </div>
    )
  }

  if (view === 'assertions') {
    if (writing('assertion_writer')) return <Streaming text={live.streams.assertion_writer ?? ''} on />
    if (!st.assertions?.length) return <div className="empty">Assertions are written from the spec after the plan.</div>
    return (
      <div className="stack" style={{ gap: 10 }}>
        {st.assertions.map((a) => (
          <motion.div key={a.label} layout className="card" style={{ padding: 12, opacity: a.status === 'dropped' ? 0.6 : 1 }}>
            <div className="row wrap" style={{ gap: 6, marginBottom: 6 }}>
              <b className="mono">{a.label}</b>
              <Chip tone={a.status === 'active' ? 'green' : 'red'}>{a.status}</Chip>
              {Boolean(a.repairs) && <Chip tone="amber">repaired</Chip>}
            </div>
            <code className="mono" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{a.code}</code>
            {a.reason && <div className="hint" style={{ marginTop: 6 }}>{a.reason}</div>}
          </motion.div>
        ))}
      </div>
    )
  }

  if (view === 'stimulus') {
    const blocks = [...(st.blocks ?? [])].reverse()
    return (
      <div className="stack">
        {writing('stimulus_writer') && <Streaming text={live.streams.stimulus_writer ?? ''} on />}
        {!blocks.length && !writing('stimulus_writer') && <div className="empty">Stimulus appears once the testbench and assertions are ready.</div>}
        {blocks.map((b) => (
          <motion.div key={b.iteration} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="stack" style={{ gap: 8 }}>
            <div className="row wrap" style={{ gap: 6 }}>
              <Chip tone="teal">iteration {b.iteration}</Chip>
              <Chip tone={b.source === 'llm' ? 'teal' : 'amber'}>{b.source === 'llm' ? 'LLM' : 'fallback'}</Chip>
              <span className="muted">{b.focus}</span>
            </div>
            <CodeView value={b.stimulus} height={Math.min(320, 20 * b.stimulus.split('\n').length + 24)} />
          </motion.div>
        ))}
      </div>
    )
  }

  if (view === 'simulator') return <SimConsole lines={live.console} st={st} />

  if (view === 'analysis') {
    const notes = live.trace.filter((e) => e.agent === 'coverage_analyst' || e.agent === 'triage').reverse()
    return (
      <div className="stack">
        {(writing('coverage_analyst') || writing('triage')) && (
          <Streaming text={live.streams.coverage_analyst ?? live.streams.triage ?? ''} on />
        )}
        {st.analysis && !writing('coverage_analyst') && (
          <div className="card card-pad"><div className="card-title">Latest analysis</div><Markdown text={st.analysis} /></div>
        )}
        <div className="stack" style={{ gap: 8 }}>
          {notes.map((e, i) => (
            <div key={i} className="row" style={{ alignItems: 'flex-start' }}>
              <Chip tone={e.agent === 'triage' ? 'amber' : 'teal'}>it {e.iteration} · {e.agent === 'triage' ? 'triage' : 'analyst'}</Chip>
              <span className="muted" style={{ fontSize: 13 }}>{e.summary}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (view === 'waves') return <Waves st={st} id={id} />
  if (view === 'mutants') return <Mutants st={st} live={live} id={id} />
  return <ReportView id={id} tick={live.tick} />
}

function SimConsole(props: { lines: string[]; st: Status }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    box.current?.scrollTo({ top: box.current.scrollHeight })
  }, [props.lines.length])
  const r = props.st.result ?? {}
  return (
    <div className="stack">
      {r.built !== undefined && (
        <div className="row wrap" style={{ gap: 6 }}>
          <Chip tone={r.passed ? 'green' : r.built ? 'red' : 'amber'}>{r.passed ? 'PASS' : r.built ? 'FAIL' : 'build failed'}</Chip>
          <Chip>functional {pct(r.functional_pct)}</Chip>
          <Chip>{r.stimulus_count ?? 0} cycles</Chip>
          {(r.failures?.length ?? 0) > 0 && <Chip tone="red">{r.failures?.length} failures</Chip>}
        </div>
      )}
      <div className="console" ref={box}>
        {props.lines.length === 0 && <div className="dim">Verilator output streams here while it builds and runs.</div>}
        {props.lines.map((l, i) => (
          <div key={i} className={/TEST PASSED/.test(l) ? 'ok' : /CHECK_FAIL|%Error|TEST FAILED|Assertion failed/.test(l) ? 'bad' : /^(make|g\+\+|c\+\+|clang|-DVM|I\/|fno-|DVM_|- V e r i l a t i o n|rm -f|if \[)/.test(l) ? 'dim' : ''}>
            {l || ' '}
          </div>
        ))}
      </div>
    </div>
  )
}

function Waves(props: { st: Status; id: string }) {
  const runs = props.st.runs ?? []
  const failing = runs.filter((r) => r.failures?.length)
  const [run, setRun] = useState<number | undefined>((failing.at(-1) ?? runs.at(-1))?.n)
  const [start, setStart] = useState<number | undefined>(undefined)
  const [data, setData] = useState<WaveData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (run === undefined) return
    api.wave(props.id, { run, start, count: 18 }).then((d) => { setData(d); setError('') }).catch((e) => setError(e.message))
  }, [props.id, run, start])
  if (!runs.length) return <div className="empty">Waveforms appear after the first simulation.</div>
  return (
    <div className="stack">
      <div className="row wrap">
        <select className="input" style={{ width: 'auto' }} value={run} onChange={(e) => { setRun(Number(e.target.value)); setStart(undefined) }}>
          {runs.map((r) => (
            <option key={r.n} value={r.n}>
              run {r.n} · iteration {r.iteration} · {r.built ? (r.passed ? 'pass' : 'fail') : 'build failed'} · {r.failures?.length ?? 0} failures
            </option>
          ))}
        </select>
        {data?.failures.slice(0, 8).map((f, i) => (
          <button key={i} className="btn btn-sm" onClick={() => setStart(Math.max(0, (f.cycle ?? 0) - 9))}>
            <span className="dot bad" /> cycle {f.cycle}
          </button>
        ))}
        <a className="btn btn-sm btn-ghost" href={`/api/sessions/${props.id}/wave.vcd?run=${run}`}>VCD</a>
      </div>
      {data && (
        <>
          <input type="range" min={0} max={Math.max(0, data.total_cycles - 18)} value={data.start} onChange={(e) => setStart(Number(e.target.value))} />
          <WaveView key={`${run}-${data.start}`} diagram={data.diagram} />
          <div className="legend">
            <span><i style={{ background: 'var(--teal)' }} />design signals</span>
            <span><i style={{ background: 'var(--violet)' }} />reference model (exp_)</span>
            <span><i style={{ background: 'var(--red)' }} />failing cycles</span>
          </div>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  )
}

function Mutants(props: { st: Status; live: ReturnType<typeof useLive>; id: string }) {
  const { st, live, id } = props
  const report = st.mutation
  const list = live.mutation?.mutants ?? report?.results.map((r) => ({ id: r.id, category: r.category, description: r.description })) ?? []
  const results: Record<string, MutantResult> = useMemo(
    () => (live.mutation ? live.mutation.results : Object.fromEntries((report?.results ?? []).map((r) => [r.id, r]))),
    [live.mutation, report],
  )
  const [selected, setSelected] = useState<string | null>(null)
  const [data, setData] = useState<WaveData | null>(null)
  useEffect(() => {
    if (!selected) return
    api.wave(id, { mutant: selected, count: 18 }).then(setData).catch(() => setData(null))
  }, [id, selected, live.mutation?.running])
  const caught = Object.values(results).filter((r) => r.verdict === 'caught').length
  if (!list.length)
    return (
      <div className="empty stack" style={{ alignItems: 'center' }}>
        <div>Mutation testing plants ten bugs in the RTL and checks how many the suite catches.</div>
        <button className="btn btn-primary" disabled={!st.blocks?.length || live.running} onClick={() => api.mutation(id)}>Run mutation testing</button>
      </div>
    )
  return (
    <div className="stack">
      <div className="row wrap" style={{ gap: 6 }}>
        <Chip tone="green">{caught} caught</Chip>
        <Chip tone="red">{Object.values(results).filter((r) => r.verdict === 'survived').length} survived</Chip>
        <Chip>{list.length - Object.keys(results).length} pending</Chip>
        {report?.stale && <Chip tone="amber">suite changed since this run</Chip>}
      </div>
      <MutantBoard mutants={list} results={results} running={Boolean(live.mutation?.running)} selected={selected} onSelect={setSelected} />
      {selected && data && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
          <div className="card-title" style={{ marginTop: 6 }}>{selected} in the waveform</div>
          <WaveView key={selected} diagram={data.diagram} />
        </motion.div>
      )}
    </div>
  )
}

function ReportView(props: { id: string; tick: number }) {
  const [text, setText] = useState('')
  useEffect(() => {
    fetch(`/api/sessions/${props.id}/report.md`).then((r) => (r.ok ? r.text() : '')).then(setText)
  }, [props.id, props.tick])
  if (!text) return <div className="empty">The report fills in as the session runs.</div>
  return <Markdown text={text} />
}
