import Editor, { loader, type OnMount } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/editor/editor.worker.start?worker'
import { useEffect, useRef } from 'react'
import { useIsDark } from '../lib/hooks'

self.MonacoEnvironment = { getWorker: () => new editorWorker() }
loader.config({ monaco })

monaco.editor.defineTheme('lab-light', {
  base: 'vs',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: '0F766E', fontStyle: 'bold' },
    { token: 'comment', foreground: '8F8A7F', fontStyle: 'italic' },
    { token: 'number', foreground: 'B45309' },
    { token: 'string', foreground: '6250D6' },
  ],
  colors: { 'editor.background': '#FBFAF7', 'editor.lineHighlightBackground': '#F1EFE9', 'editorLineNumber.foreground': '#B9B4A8' },
})
monaco.editor.defineTheme('lab-dark', {
  base: 'vs-dark',
  inherit: true,
  rules: [
    { token: 'keyword', foreground: '2DD4BF', fontStyle: 'bold' },
    { token: 'comment', foreground: '75726A', fontStyle: 'italic' },
    { token: 'number', foreground: 'F2A93B' },
    { token: 'string', foreground: 'A395F5' },
  ],
  colors: { 'editor.background': '#13161A', 'editor.lineHighlightBackground': '#1B1F23', 'editorLineNumber.foreground': '#4A5058' },
})

/** Read-only code view. With `follow`, it keeps the newest line in view while text streams in. */
export function CodeView(props: { value: string; language?: string; height?: number | string; follow?: boolean }) {
  const dark = useIsDark()
  const ref = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  const onMount: OnMount = (editor) => {
    ref.current = editor
  }
  useEffect(() => {
    const ed = ref.current
    if (props.follow && ed) ed.revealLine(ed.getModel()?.getLineCount() ?? 1)
  }, [props.value, props.follow])
  return (
    <div className="editor-frame">
      <Editor
        height={props.height ?? 460}
        language={props.language ?? 'systemverilog'}
        value={props.value}
        theme={dark ? 'lab-dark' : 'lab-light'}
        onMount={onMount}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          fontFamily: 'IBM Plex Mono',
          fontSize: 12.5,
          lineHeight: 20,
          scrollBeyondLastLine: false,
          renderLineHighlight: 'none',
          wordWrap: 'on',
          padding: { top: 10, bottom: 10 },
          overviewRulerLanes: 0,
          scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
        }}
      />
    </div>
  )
}
