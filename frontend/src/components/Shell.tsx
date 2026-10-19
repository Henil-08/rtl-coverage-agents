import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { api, type Config, type SessionSummary } from '../lib/api'
import { useTheme } from '../lib/hooks'
import { Segmented } from './ui'

export function Shell(props: { children: ReactNode }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [config, setConfig] = useState<Config | null>(null)
  const [theme, setTheme] = useTheme()
  const loc = useLocation()

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null))
  }, [])
  useEffect(() => {
    let alive = true
    const load = () => api.sessions().then((s) => alive && setSessions(s)).catch(() => {})
    load()
    const t = setInterval(load, 4000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [loc.pathname])

  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <div className="brand-mark">
            <svg width="18" height="18" viewBox="0 0 32 32">
              <path d="M4 22h5V10h5v12h5V10h5v12h4" fill="none" stroke="#fff" strokeWidth="3" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <div className="brand-name">RTL Coverage Agents</div>
            <div className="brand-sub">verification, closed by agents</div>
          </div>
        </div>
        <nav>
          <NavLink to="/" end className={({ isActive }) => `rail-link ${isActive ? 'active' : ''}`}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="2" y="2" width="5" height="5" rx="1.2" /><rect x="9" y="2" width="5" height="5" rx="1.2" /><rect x="2" y="9" width="5" height="5" rx="1.2" /><rect x="9" y="9" width="5" height="5" rx="1.2" /></svg>
            Designs
          </NavLink>
        </nav>
        <div>
          <div className="rail-label">Sessions</div>
          <div className="stack" style={{ gap: 2 }}>
            {sessions.length === 0 && <div className="hint" style={{ padding: '0 8px' }}>No sessions yet.</div>}
            {sessions.map((s) => (
              <NavLink key={s.session_id} to={`/sessions/${s.session_id}`} className={({ isActive }) => `rail-session ${isActive ? 'active' : ''}`}>
                <span className={`dot ${s.running ? 'live' : s.waiting ? 'wait' : s.done ? 'ok' : ''}`} />
                <span className="name">{s.session_id}</span>
                <span className="faint mono" style={{ fontSize: 11 }}>
                  {s.functional_pct !== null && s.functional_pct !== undefined ? `${Math.round(s.functional_pct)}%` : ''}
                </span>
              </NavLink>
            ))}
          </div>
        </div>
        <div className="rail-foot">
          <div className="row"><span className={`dot ${config?.llm ? 'ok' : 'wait'}`} />{config?.llm ?? 'no LLM: fallbacks only'}</div>
          <div className="row"><span className={`dot ${config?.kb ? 'ok' : 'wait'}`} />{config?.kb ? `${config.kb.documents} docs in knowledge base` : 'knowledge base not built'}</div>
          <div className="row"><span className={`dot ${config?.uvm ? 'ok' : 'wait'}`} />{config?.uvm ? 'Verilator + UVM' : 'UVM library missing'}</div>
          <Segmented
            value={theme as 'system' | 'light' | 'dark'}
            onChange={setTheme}
            options={[
              { value: 'system', label: 'Auto' },
              { value: 'light', label: 'Light' },
              { value: 'dark', label: 'Dark' },
            ]}
          />
        </div>
      </aside>
      <main className="main">{props.children}</main>
    </div>
  )
}
