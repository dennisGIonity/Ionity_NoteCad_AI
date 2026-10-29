// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Microphone capture: MediaRecorder (Opus in WebM/Ogg) for the brain, an AnalyserNode for the waveform.
import { create } from 'zustand'
import { api } from './api'
import { useApp } from './store'

export type RecState = 'idle' | 'arming' | 'recording' | 'sending'

const MIN_MS = 450
const MAX_MS = 120_000
const TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4']

let stream: MediaStream | null = null
let ctx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let rec: MediaRecorder | null = null
let chunks: Blob[] = []
let maxTimer: ReturnType<typeof setTimeout> | undefined

export const getAnalyser = () => analyser

interface RecorderState {
  state: RecState
  contextNodeId: string | null
  startedAt: number
  error: string | null
  start(contextNodeId?: string | null): Promise<void>
  stop(): Promise<void>
  cancel(): void
  toggle(contextNodeId?: string | null): void
  sendText(text: string, contextNodeId?: string | null): Promise<void>
}

function release() {
  rec = null
  chunks = []
  clearTimeout(maxTimer)
  for (const t of stream?.getTracks() ?? []) t.stop()
  stream = null
  analyser = null
  ctx?.close().catch(() => undefined)
  ctx = null
}

export const useRecorder = create<RecorderState>((set, get) => ({
  state: 'idle',
  contextNodeId: null,
  startedAt: 0,
  error: null,

  async start(contextNodeId = null) {
    if (get().state !== 'idle') return
    if (!useApp.getState().ws) {
      set({ error: 'No workspace' })
      return
    }
    set({ state: 'arming', contextNodeId, error: null })
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
    } catch (e) {
      set({ state: 'idle', error: (e as Error).name === 'NotAllowedError' ? 'Microphone blocked' : 'No microphone' })
      release()
      return
    }
    if (get().state !== 'arming') {  // released before the permission prompt was answered
      release()
      return
    }
    ctx = new AudioContext()
    if (ctx.state === 'suspended') await ctx.resume().catch(() => undefined)
    analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    analyser.smoothingTimeConstant = 0.6
    ctx.createMediaStreamSource(stream).connect(analyser)
    const mimeType = TYPES.find((t) => MediaRecorder.isTypeSupported(t))
    rec = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 32000 } : undefined)
    chunks = []
    rec.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data) }
    rec.start(250)
    set({ state: 'recording', startedAt: Date.now() })
    maxTimer = setTimeout(() => get().stop(), MAX_MS)
  },

  async stop() {
    const { state, startedAt, contextNodeId } = get()
    if (state === 'arming') {
      set({ state: 'idle' })
      return
    }
    if (state !== 'recording' || !rec) return
    const r = rec
    const type = r.mimeType || 'audio/webm'
    const done = new Promise<void>((resolve) => { r.onstop = () => resolve() })
    r.stop()
    await done
    const blob = new Blob(chunks, { type: type.split(';')[0] })
    release()
    if (Date.now() - startedAt < MIN_MS || blob.size < 800) {
      set({ state: 'idle', error: 'Hold a little longer to record' })
      return
    }
    set({ state: 'sending' })
    const app = useApp.getState()
    const temp = `local-${Date.now()}`
    app.startCapture({ id: temp, kind: 'audio', contextNodeId })
    try {
      const res = await api.captureAudio(app.ws, blob, contextNodeId)
      useApp.getState().renameCapture(temp, res.capture_id)
    } catch (e) {
      useApp.getState().failCapture(temp, (e as Error).message)
    }
    set({ state: 'idle', contextNodeId: null })
  },

  cancel() {
    rec?.stop()
    release()
    set({ state: 'idle', contextNodeId: null })
  },

  toggle(contextNodeId = null) {
    const s = get().state
    if (s === 'idle') void get().start(contextNodeId)
    else if (s === 'recording' || s === 'arming') void get().stop()
  },

  async sendText(text, contextNodeId = null) {
    const t = text.trim()
    if (!t) return
    const app = useApp.getState()
    const temp = `local-${Date.now()}`
    app.startCapture({ id: temp, kind: 'text', contextNodeId })
    try {
      const res = await api.captureText(app.ws, t, contextNodeId)
      useApp.getState().renameCapture(temp, res.capture_id)
    } catch (e) {
      useApp.getState().failCapture(temp, (e as Error).message)
    }
  },
}))
