import { useEffect, useReducer, useRef } from 'react'
import type { Gate, MutantResult, Pending, Status, TraceEvent } from './api'

export type LiveState = {
  status: Status | null
  connected: boolean
  running: boolean
  activeNode: string | null
  streams: Record<string, string>
  streaming: Record<string, boolean>
  gates: Gate[]
  console: string[]
  trace: TraceEvent[]
  mutation: { total: number; mutants: { id: string; category: string; description: string }[]; results: Record<string, MutantResult>; running: boolean } | null
  waiting: Pending | null
  error: string | null
  tick: number
}

type Ev = { type: string; [k: string]: any }

const initial: LiveState = {
  status: null,
  connected: false,
  running: false,
  activeNode: null,
  streams: {},
  streaming: {},
  gates: [],
  console: [],
  trace: [],
  mutation: null,
  waiting: null,
  error: null,
  tick: 0,
}

const APPENDED = new Set(['history', 'events', 'runs'])

function reduce(s: LiveState, e: Ev): LiveState {
  switch (e.type) {
    case 'connected':
      return { ...s, connected: true }
    case 'disconnected':
      return { ...s, connected: false }
    case 'snapshot': {
      const st = e.status as Status
      return { ...s, status: st, trace: st.events ?? [], running: st.running, waiting: st.pending }
    }
    case 'running':
      return { ...s, running: true, waiting: null, error: null, console: e.replay ? s.console : [] }
    case 'idle':
      return { ...s, running: false, activeNode: null }
    case 'node_start':
      return { ...s, activeNode: e.node }
    case 'llm_start':
      return { ...s, streams: { ...s.streams, [e.agent]: '' }, streaming: { ...s.streaming, [e.agent]: true } }
    case 'token':
      return { ...s, streams: { ...s.streams, [e.agent]: (s.streams[e.agent] ?? '') + e.text } }
    case 'llm_end':
      return { ...s, streaming: { ...s.streaming, [e.agent]: false } }
    case 'tb_gate':
      return { ...s, gates: [...s.gates, { gate: e.gate, ok: e.ok, detail: e.detail }] }
    case 'sim_line':
      return { ...s, console: [...s.console.slice(-600), e.text] }
    case 'node_done': {
      if (!s.status) return s
      const st: any = { ...s.status }
      for (const [k, v] of Object.entries(e.update ?? {})) {
        st[k] = APPENDED.has(k) ? [...(st[k] ?? []), ...(v as unknown[])] : v
      }
      const trace = [...s.trace, ...((e.events ?? []) as TraceEvent[])]
      st.events = trace
      return { ...s, status: st, trace, tick: s.tick + 1 }
    }
    case 'mutation_start':
      return { ...s, mutation: { total: e.total, mutants: e.mutants, results: {}, running: true } }
    case 'mutant_result':
      return s.mutation
        ? { ...s, mutation: { ...s.mutation, results: { ...s.mutation.results, [e.result.id]: e.result } } }
        : s
    case 'mutation_done':
      return s.mutation ? { ...s, mutation: { ...s.mutation, running: false } } : s
    case 'waiting':
      return { ...s, waiting: e.pending, activeNode: null }
    case 'finished':
      return { ...s, activeNode: null }
    case 'error':
      return { ...s, error: e.message, running: false }
    default:
      return s
  }
}

export function useLive(sessionId: string | undefined): LiveState {
  const [state, dispatch] = useReducer(reduce, initial)
  const retry = useRef(0)

  useEffect(() => {
    if (!sessionId) return
    let ws: WebSocket | null = null
    let closed = false
    const open = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/api/sessions/${sessionId}/live`)
      ws.onopen = () => {
        retry.current = 0
        dispatch({ type: 'connected' })
      }
      ws.onmessage = (m) => dispatch(JSON.parse(m.data))
      ws.onclose = () => {
        dispatch({ type: 'disconnected' })
        if (!closed) setTimeout(open, Math.min(4000, 400 * 2 ** retry.current++))
      }
    }
    open()
    return () => {
      closed = true
      ws?.close()
    }
  }, [sessionId])

  return state
}
