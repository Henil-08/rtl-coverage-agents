import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { WaveDiagram } from '../lib/api'
import { WaveView } from './WaveView'

/** Markdown with ```wavedrom blocks drawn as waveforms, for spec sheets and reports. */
export function Markdown(props: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children }) {
            const text = String(children)
            if (className === 'language-wavedrom') {
              try {
                return <WaveView diagram={JSON.parse(text) as WaveDiagram} colW={56} />
              } catch {
                /* fall through to plain code */
              }
            }
            return <code className={className}>{children}</code>
          },
          pre({ children }) {
            const child = Array.isArray(children) ? children[0] : children
            if ((child as { props?: { className?: string } })?.props?.className === 'language-wavedrom') return <>{children}</>
            return <pre>{children}</pre>
          },
        }}
      >
        {props.text}
      </ReactMarkdown>
    </div>
  )
}
