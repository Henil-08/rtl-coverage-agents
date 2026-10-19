import type { Models } from '../lib/api'
import { PROVIDER_LABEL } from '../lib/api'

/** Select a provider:model reference from every configured provider; empty means "use the default". */
export function ModelPicker(props: { catalog: Models | null; value: string; onChange: (v: string) => void; emptyLabel: string }) {
  const providers = props.catalog?.providers ?? []
  return (
    <select className="input" value={props.value} onChange={(e) => props.onChange(e.target.value)}>
      <option value="">{props.emptyLabel}</option>
      {providers
        .filter((p) => p.ready)
        .map((p) => {
          const names = Array.from(new Set([...p.models, ...(p.provider === 'anthropic' || p.provider === 'groq' ? p.suggested : [])]))
          return (
            <optgroup key={p.provider} label={PROVIDER_LABEL[p.provider] ?? p.provider}>
              {names.map((m) => (
                <option key={m} value={`${p.provider}:${m}`}>
                  {m}
                </option>
              ))}
            </optgroup>
          )
        })}
    </select>
  )
}
