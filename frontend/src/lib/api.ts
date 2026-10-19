export type Port = { name: string; dir: string; width: number }
export type DesignSummary = {
  name: string
  title: string
  kind: 'builtin' | 'upload'
  mutants: number
  languages: string[]
  handwritten_tb: boolean
}
export type DesignDetail = DesignSummary & {
  spec: string
  rtl: Record<string, string>
  ports: { top: string; ports: Port[]; clock: string | null; reset: string | null; error?: string }
  covergroup: string
  mutants: { id: string; category: string; description: string }[]
}
export type TraceEvent = { agent: string; kind: string; summary: string; iteration: number; t?: number }
export type Gate = { gate: string; ok: boolean; detail: string }
export type KbHit = { ref?: string; title: string; page: number | null; url: string; text: string; query: string; doc: string }
export type PlanItem = { feature: string; coverpoints?: string[]; risk?: string; sources?: string[] }
export type Assertion = { label: string; code: string; status: string; reason?: string; repairs?: number }
export type Block = { iteration: number; focus: string; stimulus: string; source: string }
export type CodeCov = { hit: number; total: number; pct: number | null; missed: string[] }
export type Failure = { kind: string; time: number; label: string; text: string; cycle?: number }
export type SimResult = {
  built?: boolean
  passed?: boolean | null
  functional_pct?: number | null
  point_pct?: Record<string, number>
  bins?: Record<string, number>
  code?: Record<string, CodeCov>
  failures?: Failure[]
  compile_errors?: string[]
  check_failures?: string[]
  assertion_failures?: string[]
  stimulus_count?: number | null
}
export type HistoryRow = {
  iteration: number
  focus: string
  functional_pct: number
  toggle_pct?: number | null
  branch_pct?: number | null
  expr_pct?: number | null
  newly_covered?: string[]
}
export type Run = { n: number; iteration: number; built: boolean; passed: boolean | null; failures: Failure[]; wave: string }
export type MutantResult = {
  id: string
  category: string
  description: string
  verdict: 'caught' | 'survived' | 'invalid'
  by_assertion: boolean
  by_scoreboard: boolean
  failures?: Failure[]
}
export type MutationReport = {
  golden_ok: boolean
  caught: number
  total: number
  caught_by_assertions: number
  survived: string[]
  results: MutantResult[]
  stale?: boolean
  golden_errors?: string[]
}
export type GenTb = {
  ok?: boolean
  sv?: string
  uvm?: string
  gates?: Gate[]
  drivers?: { name: string; args: { name: string; width: number }[] }[]
  harness_doc?: string
  reason?: string
}
export type Pending = { step: string; iteration: number; [k: string]: unknown }
export type Status = {
  session_id: string
  exists: boolean
  running: boolean
  design: string
  language: string
  tb_source: string
  mode: string
  iteration: number
  done: boolean
  stop_reason: string
  issue: string
  triage_note: string
  analysis: string
  plan: PlanItem[]
  kb_hits: KbHit[]
  assertions: Assertion[]
  blocks: Block[]
  testbench: string
  result: SimResult
  history: HistoryRow[]
  events: TraceEvent[]
  runs: Run[]
  gen_tb: GenTb
  pending: Pending | null
  settings: Record<string, number | string | boolean>
  llm_model: string
  mutation: MutationReport | null
}
export type SessionSummary = {
  session_id: string
  design: string
  mode: string
  language: string
  tb_source: string
  iteration: number
  done: boolean
  stop_reason: string
  functional_pct: number | null
  waiting: boolean
  running: boolean
}
export type Config = {
  llm: string | null
  verilator: boolean
  uvm: boolean
  kb: { passages: number; documents: number; embeddings: boolean } | null
  defaults: Record<string, number | string | boolean>
}
export type WaveView = {
  total_cycles: number
  start: number
  signals: string[]
  available: string[]
  failures: Failure[]
  diagram: WaveDiagram
}
export type WaveRow = { name?: string; wave?: string; data?: string[] }
export type WaveDiagram = { signal: WaveRow[]; head?: { text?: string; tick?: number } }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep the status text */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  config: () => call<Config>('/api/config'),
  designs: () => call<DesignSummary[]>('/api/designs'),
  design: (name: string) => call<DesignDetail>(`/api/designs/${name}`),
  upload: (form: FormData) => call<{ name: string }>('/api/designs', { method: 'POST', body: form }),
  deleteDesign: (name: string) => call(`/api/designs/${name}`, { method: 'DELETE' }),
  sessions: () => call<SessionSummary[]>('/api/sessions'),
  session: (id: string) => call<Status>(`/api/sessions/${id}`),
  start: (body: Record<string, unknown>) => call<{ session_id: string }>('/api/sessions', json(body)),
  respond: (id: string, action: string, feedback = '') => call(`/api/sessions/${id}/respond`, json({ action, feedback })),
  mutation: (id: string) => call(`/api/sessions/${id}/mutation`, { method: 'POST' }),
  wave: (id: string, q: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams()
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== '' && params.set(k, String(v)))
    return call<WaveView>(`/api/sessions/${id}/wave?${params}`)
  },
  kbSearch: (q: string) => call<KbHit[]>(`/api/kb/search?q=${encodeURIComponent(q)}`),
}
