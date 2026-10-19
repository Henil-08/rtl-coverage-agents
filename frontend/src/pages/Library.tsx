import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Chip } from '../components/ui'
import { api, type DesignSummary } from '../lib/api'

export function Library() {
  const [designs, setDesigns] = useState<DesignSummary[] | null>(null)
  const [uploading, setUploading] = useState(false)
  const nav = useNavigate()
  useEffect(() => {
    api.designs().then(setDesigns).catch(() => setDesigns([]))
  }, [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Design library</h1>
          <p className="lede">
            Pick a design to verify, or upload your own RTL and spec. The agents read the spec, write a plan and a
            testbench, generate tests, run Verilator, and close coverage.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setUploading(true)}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M7 2v10M2 7h10" /></svg>
          Upload a design
        </button>
      </div>
      <div className="design-grid">
        {(designs ?? []).map((d, i) => (
          <motion.div
            key={d.name}
            className="card design-card"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
            onClick={() => nav(`/designs/${d.name}`)}
          >
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <div className="design-glyph">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="4" y="4" width="12" height="12" rx="2" /><path d="M7 1v3M13 1v3M7 16v3M13 16v3M1 7h3M1 13h3M16 7h3M16 13h3" /></svg>
              </div>
              <Chip tone={d.kind === 'upload' ? 'violet' : undefined}>{d.kind === 'upload' ? 'uploaded' : 'built-in'}</Chip>
            </div>
            <div>
              <h3>{d.title}</h3>
              <div className="faint mono" style={{ fontSize: 12, marginTop: 2 }}>{d.name}</div>
            </div>
            <div className="row wrap" style={{ gap: 6, marginTop: 'auto' }}>
              <Chip>{d.mutants} mutants</Chip>
              <Chip>{d.languages.map((l) => (l === 'uvm' ? 'UVM' : 'SV')).join(' + ')}</Chip>
              <Chip tone={d.handwritten_tb ? 'blue' : 'teal'}>{d.handwritten_tb ? 'hand-written TB' : 'agent-written TB'}</Chip>
            </div>
          </motion.div>
        ))}
        <motion.button
          className="card design-card upload-card"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.15 }}
          onClick={() => setUploading(true)}
        >
          <div style={{ fontSize: 28, lineHeight: 1 }}>+</div>
          <div style={{ fontWeight: 500 }}>Upload RTL and a spec</div>
          <div className="hint">SystemVerilog or Verilog, plus a PDF, Markdown or text spec</div>
        </motion.button>
      </div>
      <AnimatePresence>{uploading && <UploadDialog onClose={() => setUploading(false)} onDone={(n) => nav(`/designs/${n}`)} />}</AnimatePresence>
    </div>
  )
}

function Drop(props: { label: string; accept: string; multiple?: boolean; files: File[]; onFiles: (f: File[]) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
    <div
      className={`drop ${over ? 'over' : ''}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        props.onFiles(Array.from(e.dataTransfer.files))
      }}
    >
      <input ref={input} type="file" hidden accept={props.accept} multiple={props.multiple} onChange={(e) => props.onFiles(Array.from(e.target.files ?? []))} />
      {props.files.length ? (
        <div className="mono" style={{ fontSize: 12.5 }}>{props.files.map((f) => f.name).join(', ')}</div>
      ) : (
        <div>{props.label}</div>
      )}
    </div>
  )
}

function UploadDialog(props: { onClose: () => void; onDone: (name: string) => void }) {
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [rtl, setRtl] = useState<File[]>([])
  const [spec, setSpec] = useState<File[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async () => {
    setBusy(true)
    setError('')
    const form = new FormData()
    form.set('name', name)
    form.set('title', title)
    rtl.forEach((f) => form.append('rtl_files', f))
    if (spec[0]) form.set('spec_file', spec[0])
    try {
      const out = await api.upload(form)
      props.onDone(out.name)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <motion.div className="overlay" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={props.onClose}>
      <motion.div
        className="card dialog stack"
        initial={{ y: 16, scale: 0.98 }}
        animate={{ y: 0, scale: 1 }}
        exit={{ y: 8, opacity: 0 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        onClick={(e) => e.stopPropagation()}
      >
        <div>
          <h2 style={{ fontSize: 20 }}>Upload a design</h2>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            The RTL is checked with Verilator, its ports are read, and ten mutants are generated. The testbench
            architect agent writes the testbench when you start a session.
          </p>
        </div>
        <div className="row" style={{ gap: 12 }}>
          <div className="field" style={{ flex: 1 }}>
            <label>Name</label>
            <input className="input mono" placeholder="sync_fifo" value={name} onChange={(e) => setName(e.target.value.toLowerCase())} />
          </div>
          <div className="field" style={{ flex: 1.4 }}>
            <label>Title</label>
            <input className="input" placeholder="Synchronous FIFO, 8 x 16" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label>RTL files</label>
          <Drop label="Drop .sv / .v files here, or click to choose" accept=".sv,.v,.svh,.vh" multiple files={rtl} onFiles={setRtl} />
        </div>
        <div className="field">
          <label>Spec</label>
          <Drop label="Drop the spec (PDF, Markdown or text)" accept=".pdf,.md,.txt" files={spec} onFiles={(f) => setSpec(f.slice(0, 1))} />
          <div className="hint">A list of numbered requirements (R1, R2, …) and corner cases gives the agents the most to work with.</div>
        </div>
        {error && <div className="error">{error}</div>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={props.onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !name || !rtl.length || !spec.length} onClick={submit}>
            {busy ? 'Checking RTL…' : 'Upload'}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
