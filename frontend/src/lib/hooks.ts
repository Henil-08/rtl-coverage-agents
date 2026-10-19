import { useEffect, useRef, useState } from 'react'

/** Animate a number towards its target, for counters that should glide rather than jump. */
export function useTween(target: number, ms = 700): number {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const start = performance.now()
    const a = from.current
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || a === target) {
      from.current = target
      setValue(target)
      return
    }
    let raf = 0
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      const eased = 1 - Math.pow(1 - t, 3)
      const v = a + (target - a) * eased
      setValue(v)
      from.current = v
      if (t < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return value
}

export function useTheme(): [string, (t: string) => void] {
  const [theme, setTheme] = useState(() => localStorageGet('theme') ?? 'system')
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    localStorageSet('theme', theme)
  }, [theme])
  return [theme, setTheme]
}

export function useIsDark(): boolean {
  const get = () => {
    const attr = document.documentElement.getAttribute('data-theme')
    return attr ? attr === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  }
  const [dark, setDark] = useState(get)
  useEffect(() => {
    const mq = matchMedia('(prefers-color-scheme: dark)')
    const update = () => setDark(get())
    const obs = new MutationObserver(update)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    mq.addEventListener('change', update)
    return () => {
      obs.disconnect()
      mq.removeEventListener('change', update)
    }
  }, [])
  return dark
}

function localStorageGet(k: string): string | null {
  try {
    return localStorage.getItem(k)
  } catch {
    return null
  }
}

function localStorageSet(k: string, v: string) {
  try {
    localStorage.setItem(k, v)
  } catch {
    /* storage unavailable */
  }
}
