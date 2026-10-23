// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The floating capture pill: mic, waveform, live status from the brain, type-instead box and the map toggle.
import { Keyboard, Loader2, Map as MapIcon, Mic, Minimize2, Send, Square, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useRecorder } from '../lib/recorder'
import { headline, summarise, useApp } from '../lib/store'
import type { CaptureView, MindMap } from '../lib/types'
import { cls } from '../lib/ui'
import { ActionToast } from './ActionToast'
import { Waveform } from './Waveform'

type Tone = 'idle' | 'live' | 'busy' | 'ok' | 'ask' | 'error'

const FRIENDLY: [RegExp, string][] = [
  [/speech-to-text|STTError/i, 'No speech-to-text on the brain yet: type the note instead'],
  [/not reachable/i, 'Brain not reachable'],
  [/415|unsupported audio/i, 'This audio format is not supported'],
]

function titleOf(map: MindMap | null, id: string | null) {
  return id ? map?.nodes.find((n) => n.id === id)?.title ?? null : null
}

export function ticker(cap: CaptureView | undefined, rec: ReturnType<typeof useRecorder.getState>, map: MindMap | null):
  { text: string; sub?: string; tone: Tone } {
  if (rec.state === 'recording') {
    const on = titleOf(map, rec.contextNodeId)
    return { text: 'Listening…', sub: on ? `on ${on}` : 'release to send', tone: 'live' }
  }
  if (rec.state === 'arming') return { text: 'Opening the mic…', tone: 'busy' }
  if (!cap) return { text: rec.error ?? 'Hold Space or click the mic to talk', tone: rec.error ? 'error' : 'idle' }
  const quoted = cap.transcript ? `“${cap.transcript}”` : ''
  switch (cap.state) {
    case 'recording':
    case 'uploading':
      return { text: 'Sending…', tone: 'busy' }
    case 'queued':
      return { text: cap.kind === 'audio' ? 'Received, waiting to transcribe…' : 'Received…', tone: 'busy' }
    case 'transcribing':
      return { text: 'Transcribing…', tone: 'busy' }
    case 'routing': {
      const sub = cap.resolving && cap.events > 1 ? `filing ${cap.resolving.idx + 1} of ${cap.events}` : 'filing…'
      return { text: quoted || `“${cap.resolving?.text ?? '…'}”`, sub, tone: 'busy' }
    }
    case 'applied':
    case 'needs_review': {
      const s = summarise(cap)
      const open = cap.inbox.filter((i) => !i.resolved && !i.dismissed).length
      if (s.count) return { text: headline(s), sub: open ? `${open} to place` : quoted, tone: open ? 'ask' : 'ok' }
      return { text: open ? 'Where should this go?' : 'Filed', sub: quoted, tone: open ? 'ask' : 'ok' }
    }
    case 'undone':
      return { text: 'Undone', sub: quoted, tone: 'idle' }
    case 'failed': {
      const f = FRIENDLY.find(([re]) => re.test(cap.error ?? ''))
      return { text: f ? f[1] : 'Could not file that note', sub: f ? undefined : cap.error, tone: 'error' }
    }
  }
}

const TONE_DOT: Record<Tone, string> = {
  idle: 'bg-slate-500', live: 'bg-rose-500 animate-pulse', busy: 'bg-sky-400 animate-pulse', ok: 'bg-emerald-400',
  ask: 'bg-amber-400 animate-pulse', error: 'bg-rose-500',
}

export function RecorderHUD({ docked = false }: { docked?: boolean }) {
  const rec = useRecorder()
  const { view, setView, map, captures, activeCapture, live } = useApp()
  const cap = activeCapture ? captures[activeCapture] : undefined
  const t = ticker(cap, rec, map)
  const [typing, setTyping] = useState(false)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const recording = rec.state === 'recording' || rec.state === 'arming'
  const working = !!cap && !cap.finishedAt && cap.state !== 'failed'
  const waveMode = recording ? 'live' : working ? 'busy' : 'idle'

  useEffect(() => { if (typing) input.current?.focus() }, [typing])

  const ctxTitle = useMemo(() => titleOf(map, rec.contextNodeId), [map, rec.contextNodeId])

  const send = () => {
    if (!text.trim()) return
    void rec.sendText(text)
    setText('')
    setTyping(false)
  }

  return (
    <div className={cls('pointer-events-none flex w-full flex-col items-center gap-2', docked ? 'px-4 pb-4' : 'px-3')}>
      <ActionToast />
      <div
        data-tauri-drag-region
        className={cls(
          'nc-glass pointer-events-auto flex w-full max-w-[680px] items-center gap-3 rounded-full py-2 pl-2 pr-2 shadow-2xl shadow-black/40 transition-all duration-300',
          recording && 'ring-2 ring-rose-500/60',
        )}
      >
        <button
          type="button"
          aria-label={recording ? 'Stop and send' : 'Record a voice note'}
          title={recording ? 'Release Space or click to send' : 'Click, or hold Space, to talk'}
          onClick={() => rec.toggle(null)}
          className={cls(
            'relative grid size-11 shrink-0 place-items-center rounded-full transition-all duration-200 focus-visible:outline-2 focus-visible:outline-sky-400',
            recording ? 'bg-rose-500 text-white shadow-lg shadow-rose-500/40' : 'bg-white/10 text-slate-100 hover:bg-white/20',
          )}
        >
          {recording && <span className="absolute inset-0 animate-ping rounded-full bg-rose-500/40" />}
          {rec.state === 'arming' ? <Loader2 className="size-5 animate-spin" /> : recording ? <Square className="relative size-4 fill-current" /> : <Mic className="size-5" />}
        </button>

        {typing ? (
          <form className="flex min-w-0 flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input
              ref={input}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Escape') setTyping(false) }}
              placeholder="Type a note, e.g. John Deere one needs a wheel change"
              className="min-w-0 flex-1 bg-transparent text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none"
              aria-label="Type a note"
            />
            <button type="submit" aria-label="Send note" className="grid size-8 place-items-center rounded-full bg-sky-500/80 text-white hover:bg-sky-400">
              <Send className="size-4" />
            </button>
            <button type="button" aria-label="Close" onClick={() => setTyping(false)} className="grid size-8 place-items-center rounded-full text-slate-400 hover:bg-white/10">
              <X className="size-4" />
            </button>
          </form>
        ) : (
          <>
            <Waveform mode={waveMode} className="h-9 w-14 shrink-0 sm:w-40" />
            <div className="min-w-0 flex-1" aria-live="polite">
              <div key={t.text} className="nc-tick flex items-center gap-2">
                <span className={cls('size-1.5 shrink-0 rounded-full', TONE_DOT[t.tone])} />
                <span className={cls('truncate text-sm font-medium', t.tone === 'error' ? 'text-rose-300' : 'text-slate-100')}>{t.text}</span>
              </div>
              <div className="truncate pl-3.5 text-[11px] text-slate-400">
                {t.sub ?? (ctxTitle ? `on ${ctxTitle}` : live === 'live' ? 'Brain live' : live === 'reconnecting' ? 'Reconnecting to the brain…' : 'Connecting…')}
              </div>
            </div>
            <button type="button" aria-label="Type instead" title="Type instead" onClick={() => setTyping(true)}
              className="grid size-9 shrink-0 place-items-center rounded-full text-slate-300 hover:bg-white/10">
              <Keyboard className="size-4" />
            </button>
          </>
        )}

        <button
          type="button"
          onClick={() => setView(view === 'map' ? 'hud' : 'map')}
          aria-label={view === 'map' ? 'Back to the recorder' : 'Open the mind map'}
          title={view === 'map' ? 'Back to the recorder (M)' : 'Open the mind map (M)'}
          className={cls('grid size-9 shrink-0 place-items-center rounded-full transition-colors',
            view === 'map' ? 'bg-sky-500/20 text-sky-300 hover:bg-sky-500/30' : 'text-slate-300 hover:bg-white/10')}
        >
          {view === 'map' ? <Minimize2 className="size-4" /> : <MapIcon className="size-4" />}
        </button>
      </div>
    </div>
  )
}
