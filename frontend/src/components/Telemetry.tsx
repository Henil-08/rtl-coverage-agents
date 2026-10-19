import { motion } from 'motion/react'
import { useMemo } from 'react'
import type { CodeCov, HistoryRow, TraceEvent } from '../lib/api'
import { useTween } from '../lib/hooks'

export function Dial(props: { label: string; value: number | null | undefined; color: string; sub?: string }) {
  const v = useTween(props.value ?? 0)
  const r = 46
  const c = 2 * Math.PI * r
  return (
    <div className="card card-pad dial" style={{ padding: 14 }}>
      <svg width={120} height={120} viewBox="0 0 120 120">
        <circle cx={60} cy={60} r={r} fill="none" stroke="var(--sunk)" strokeWidth={9} />
        <motion.circle
          cx={60}
          cy={60}
          r={r}
          fill="none"
          stroke={props.color}
          strokeWidth={9}
          strokeLinecap="round"
          strokeDasharray={c}
          animate={{ strokeDashoffset: c * (1 - (props.value ?? 0) / 100) }}
          initial={{ strokeDashoffset: c }}
          transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
          transform="rotate(-90 60 60)"
        />
      </svg>
      <div className="dial-value">
        <div>
          <b>{props.value === null || props.value === undefined ? '–' : `${v.toFixed(1)}%`}</b>
          <span>{props.label}</span>
        </div>
      </div>
      {props.sub && <div className="hint" style={{ marginTop: 4 }}>{props.sub}</div>}
    </div>
  )
}

export function CodeBars(props: { code: Record<string, CodeCov> | undefined }) {
  const rows = Object.entries(props.code ?? {}).filter(([, c]) => c.total)
  if (!rows.length) return <div className="hint">Code coverage appears after the first simulation.</div>
  return (
    <div className="stack" style={{ gap: 9 }}>
      {rows.map(([k, c]) => (
        <div key={k} className="metric-row">
          <span className="muted">{k === 'expr' ? 'expression' : k}</span>
          <div className="bar">
            <motion.div animate={{ width: `${c.pct ?? 0}%` }} initial={{ width: 0 }} transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }} />
          </div>
          <span className="num">
            {c.hit}/{c.total}
          </span>
        </div>
      ))}
    </div>
  )
}

export function BinGrid(props: { bins: Record<string, number> | undefined }) {
  const groups = useMemo(() => {
    const g: Record<string, [string, number][]> = {}
    for (const [k, v] of Object.entries(props.bins ?? {})) {
      const [cp, ...rest] = k.split('.')
      ;(g[cp] ??= []).push([rest.join('.'), v])
    }
    return Object.entries(g)
  }, [props.bins])
  if (!groups.length) return <div className="hint">Each coverage bin lights up here when a test hits it.</div>
  return (
    <div className="bins">
      {groups.map(([cp, bins]) => (
        <div key={cp}>
          <div className="bin-group-name">
            {cp} <span className="faint">{bins.filter(([, v]) => v > 0).length}/{bins.length}</span>
          </div>
          <div className="bin-cells">
            {bins.map(([name, v]) => (
              <motion.div
                key={name}
                className={`bin ${v > 0 ? 'hit' : ''}`}
                title={`${cp}.${name}: ${v} hit${v === 1 ? '' : 's'}`}
                initial={false}
                animate={v > 0 ? { scale: [1.5, 1], opacity: Math.min(1, 0.45 + Math.log10(v + 1) / 2) } : { scale: 1, opacity: 1 }}
                transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function CoverageChart(props: { history: HistoryRow[] }) {
  const h = props.history
  if (h.length < 1) return <div className="hint">Coverage per iteration appears after the first iteration.</div>
  const W = 300
  const H = 120
  const x = (i: number) => (h.length === 1 ? W / 2 : 8 + (i * (W - 16)) / (h.length - 1))
  const y = (v: number) => H - 10 - (v / 100) * (H - 20)
  const line = (key: 'functional_pct' | 'toggle_pct') => h.map((r, i) => `${i ? 'L' : 'M'}${x(i)},${y((r[key] as number) ?? 0)}`).join(' ')
  return (
    <div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="coverage per iteration">
        {[0, 50, 100].map((g) => (
          <g key={g}>
            <line x1={0} x2={W} y1={y(g)} y2={y(g)} stroke="var(--line)" />
            <text x={W - 2} y={y(g) - 3} fontSize={9} textAnchor="end" fill="var(--ink-3)">
              {g}%
            </text>
          </g>
        ))}
        {(['functional_pct', 'toggle_pct'] as const).map((k, idx) => (
          <g key={k}>
            <motion.path d={line(k)} fill="none" stroke={idx ? 'var(--series-2)' : 'var(--series-1)'} strokeWidth={2} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.6 }} />
            {h.map((r, i) => (
              <circle key={i} cx={x(i)} cy={y((r[k] as number) ?? 0)} r={3} fill={idx ? 'var(--series-2)' : 'var(--series-1)'}>
                <title>{`iteration ${r.iteration}: ${k === 'functional_pct' ? 'functional' : 'toggle'} ${((r[k] as number) ?? 0).toFixed(1)}%`}</title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <div className="legend" style={{ marginTop: 6 }}>
        <span><i style={{ background: 'var(--series-1)' }} />functional</span>
        <span><i style={{ background: 'var(--series-2)' }} />toggle</span>
      </div>
    </div>
  )
}

const KIND_COLOR: Record<string, string> = {
  llm: 'var(--teal)',
  tool: 'var(--blue)',
  rule: 'var(--amber)',
  fallback: 'var(--amber)',
  human: 'var(--violet)',
}

export function Timeline(props: { events: TraceEvent[] }) {
  const items = [...props.events].reverse().slice(0, 60)
  if (!items.length) return <div className="hint">Agent activity shows up here.</div>
  return (
    <div className="timeline">
      {items.map((e, i) => (
        <motion.div
          key={`${props.events.length - i}`}
          className="tl-item"
          style={{ ['--tl-color' as string]: KIND_COLOR[e.kind] ?? 'var(--ink-3)' }}
          initial={i === 0 ? { opacity: 0, x: -6 } : false}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.25 }}
        >
          <div className="tl-head">
            it {e.iteration} · <b style={{ color: 'var(--ink)' }}>{e.agent}</b> · {e.kind}
          </div>
          <div>{e.summary}</div>
        </motion.div>
      ))}
    </div>
  )
}
