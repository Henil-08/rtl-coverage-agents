import { motion } from 'motion/react'
import type { WaveDiagram, WaveRow } from '../lib/api'

const LABEL_W = 104
const ROW_H = 30
const HEAD_H = 26
const AMP = 9

type Cell = { ch: string; cont: boolean; label?: string }

function expand(row: WaveRow): Cell[] {
  const out: Cell[] = []
  const data = [...(row.data ?? [])]
  let prev: Cell | null = null
  for (const ch of row.wave ?? '') {
    if (ch === '.' || ch === '|') {
      if (prev) out.push({ ...prev, cont: true })
      continue
    }
    const cell: Cell = { ch, cont: false }
    if ('=23456789'.includes(ch)) cell.label = data.shift() ?? ''
    out.push(cell)
    prev = cell
  }
  return out
}

function kind(cells: Cell[]): 'clock' | 'bus' | 'bit' {
  if (cells.some((c) => 'pPnN'.includes(c.ch))) return 'clock'
  if (cells.some((c) => '=23456789'.includes(c.ch))) return 'bus'
  return 'bit'
}

function tone(name: string) {
  if (name === 'FAIL') return 'var(--red)'
  if (name.startsWith('exp_')) return 'var(--violet)'
  if (name === 'clk') return 'var(--ink-3)'
  return 'var(--teal)'
}

function bitPath(cells: Cell[], colW: number, y: number): string {
  const level = (c: Cell) => (c.ch === '1' || c.ch === 'h' || c.ch === 'H' ? y - AMP : c.ch === '0' || c.ch === 'l' || c.ch === 'L' ? y + AMP : y)
  let d = ''
  cells.forEach((c, i) => {
    const x0 = LABEL_W + i * colW
    const ly = level(c)
    if (i === 0) d += `M${x0},${ly}`
    else {
      const prev = level(cells[i - 1])
      d += prev !== ly ? ` L${x0 + 3},${ly}` : ` L${x0},${ly}`
    }
    d += ` L${x0 + colW},${ly}`
  })
  return d
}

function clockPath(n: number, colW: number, y: number): string {
  let d = `M${LABEL_W},${y + AMP}`
  for (let i = 0; i < n; i++) {
    const x = LABEL_W + i * colW
    d += ` L${x},${y - AMP} L${x + colW / 2},${y - AMP} L${x + colW / 2},${y + AMP} L${x + colW},${y + AMP}`
  }
  return d
}

export function WaveView(props: { diagram: WaveDiagram; colW?: number; animate?: boolean }) {
  const rows = props.diagram.signal ?? []
  const parsed = rows.map((r) => ({ row: r, cells: expand(r) }))
  const cols = Math.max(1, ...parsed.map((p) => p.cells.length))
  const colW = props.colW ?? Math.max(30, Math.min(54, Math.floor(860 / cols)))
  const width = LABEL_W + cols * colW + 12
  const height = HEAD_H + rows.length * ROW_H + 8
  const tick = props.diagram.head?.tick ?? 0
  const failRow = parsed.find((p) => p.row.name === 'FAIL')
  const failCols = failRow ? failRow.cells.map((c, i) => (c.ch === '1' ? i : -1)).filter((i) => i >= 0) : []
  const draw = props.animate === false ? {} : { initial: { pathLength: 0 }, animate: { pathLength: 1 }, transition: { duration: 0.7, ease: 'easeOut' as const } }

  return (
    <div className="wave-wrap">
      {props.diagram.head?.text && <div style={{ fontWeight: 500, fontSize: 13, padding: '2px 8px 6px' }}>{props.diagram.head.text}</div>}
      <svg width={width} height={height} role="img" aria-label="waveform">
        {failCols.map((i) => (
          <rect key={`f${i}`} x={LABEL_W + i * colW} y={HEAD_H - 4} width={colW} height={height - HEAD_H} fill="var(--red-soft)" />
        ))}
        {Array.from({ length: cols + 1 }, (_, i) => (
          <g key={`g${i}`}>
            <line x1={LABEL_W + i * colW} x2={LABEL_W + i * colW} y1={HEAD_H - 4} y2={height} stroke="var(--line)" strokeDasharray="2 3" />
            {i < cols && (
              <text x={LABEL_W + i * colW + colW / 2} y={14} textAnchor="middle" fontSize={10} fill="var(--ink-3)">
                {tick + i}
              </text>
            )}
          </g>
        ))}
        {parsed.map(({ row, cells }, r) => {
          const y = HEAD_H + r * ROW_H + ROW_H / 2
          if (!row.name) return null
          const color = tone(row.name)
          const k = kind(cells)
          return (
            <g key={`${row.name}-${r}`}>
              <text x={LABEL_W - 10} y={y + 4} textAnchor="end" fontSize={11.5} fill={row.name.startsWith('exp_') ? 'var(--violet)' : 'var(--ink-2)'}>
                {row.name}
              </text>
              {k === 'clock' && <motion.path d={clockPath(cells.length, colW, y)} fill="none" stroke={color} strokeWidth={1.4} {...draw} />}
              {k === 'bit' && (
                <>
                  {cells.map((c, i) =>
                    c.ch === 'x' ? (
                      <rect key={i} x={LABEL_W + i * colW} y={y - AMP} width={colW} height={AMP * 2} fill="var(--sunk)" />
                    ) : null,
                  )}
                  <motion.path d={bitPath(cells, colW, y)} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" {...draw} />
                </>
              )}
              {k === 'bus' &&
                segments(cells).map((s, i) => {
                  const x0 = LABEL_W + s.start * colW
                  const x1 = LABEL_W + s.end * colW
                  if (s.ch === 'x')
                    return <rect key={i} x={x0} y={y - AMP} width={x1 - x0} height={AMP * 2} fill="var(--sunk)" stroke="var(--line)" />
                  const d = `M${x0},${y} L${x0 + 4},${y - AMP} L${x1 - 4},${y - AMP} L${x1},${y} L${x1 - 4},${y + AMP} L${x0 + 4},${y + AMP} Z`
                  return (
                    <g key={i}>
                      <motion.path d={d} fill={row.name?.startsWith('exp_') ? 'var(--violet-soft)' : 'var(--teal-soft)'} stroke={color} strokeWidth={1.2} {...draw} />
                      {x1 - x0 > 16 && (
                        <text x={(x0 + x1) / 2} y={y + 4} textAnchor="middle" fontSize={11} fill="var(--ink)">
                          {s.label}
                        </text>
                      )}
                    </g>
                  )
                })}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function segments(cells: Cell[]) {
  const out: { start: number; end: number; ch: string; label?: string }[] = []
  cells.forEach((c, i) => {
    if (c.cont && out.length) out[out.length - 1].end = i + 1
    else out.push({ start: i, end: i + 1, ch: c.ch, label: c.label })
  })
  return out
}
