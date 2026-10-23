// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// 60 fps waveform on a canvas: the live microphone while recording, a slow breathing line while idle, a moving
// shimmer while the brain works. Drawn with requestAnimationFrame; no React renders per frame.
import { useEffect, useRef } from 'react'
import { getAnalyser } from '../lib/recorder'

type Mode = 'idle' | 'live' | 'busy'

export function Waveform({ mode, className = '' }: { mode: Mode; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null)
  const modeRef = useRef<Mode>(mode)
  modeRef.current = mode

  useEffect(() => {
    const canvas = ref.current!
    const g = canvas.getContext('2d')!
    let raf = 0
    let level = 0
    const bars = 48
    const heights = new Float32Array(bars)
    let buf: Uint8Array<ArrayBuffer> | null = null
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    const draw = (t: number) => {
      const dpr = window.devicePixelRatio || 1
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr)
        canvas.height = Math.round(h * dpr)
      }
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      g.clearRect(0, 0, w, h)
      const m = modeRef.current
      const an = m === 'live' ? getAnalyser() : null
      if (an) {
        if (!buf || buf.length !== an.fftSize) buf = new Uint8Array(new ArrayBuffer(an.fftSize))
        an.getByteTimeDomainData(buf)
      }
      const gap = w / bars
      const grad = g.createLinearGradient(0, 0, w, 0)
      grad.addColorStop(0, '#38bdf8')
      grad.addColorStop(0.5, '#a78bfa')
      grad.addColorStop(1, '#34d399')
      let peak = 0
      for (let i = 0; i < bars; i++) {
        let target: number
        if (an && buf) {
          const seg = Math.floor(buf.length / bars)
          let sum = 0
          for (let j = i * seg; j < (i + 1) * seg; j++) sum += Math.abs(buf[j] - 128)
          target = Math.min(1, (sum / seg / 128) * 5.5)
          peak = Math.max(peak, target)
        } else if (m === 'busy' && !reduced) {
          const x = i / bars
          target = 0.18 + 0.32 * Math.max(0, Math.sin(x * Math.PI * 3 - t / 160)) ** 3
        } else {
          target = 0.06 + (reduced ? 0 : 0.04 * Math.sin(t / 900 + i / 4))
        }
        heights[i] += (target - heights[i]) * 0.35
        const bh = Math.max(2, heights[i] * (h - 4))
        const x = i * gap + gap * 0.2
        g.fillStyle = grad
        g.globalAlpha = m === 'idle' ? 0.45 : 0.95
        g.beginPath()
        g.roundRect(x, (h - bh) / 2, Math.max(1.5, gap * 0.6), bh, 2)
        g.fill()
      }
      level += (peak - level) * 0.2
      canvas.style.setProperty('--level', level.toFixed(3))
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  return <canvas ref={ref} className={className} aria-hidden="true" />
}
