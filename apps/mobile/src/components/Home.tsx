// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, CircleDot, CloudOff, Keyboard, ListTodo, Loader2, LogOut, MessageCircle, Mic,
  RefreshCw, Send, Square, Trash2, Undo2, Wifi, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Native, platform } from '../lib/native'
import type { NativeItem } from '../lib/native'
import type { OutboxItem } from '../lib/outbox'
import * as F from '@notecad/core/fold'
import { usePhone } from '../lib/phone'
import { useShallow } from 'zustand/react/shallow'

const STATE: Record<string, { label: string; tone: string }> = {
  saved: { label: 'Saved on phone', tone: 'text-slate-300 bg-white/10' },
  uploading: { label: 'Sending', tone: 'text-sky-200 bg-sky-500/20' },
  uploaded: { label: 'With the brain', tone: 'text-sky-200 bg-sky-500/20' },
  transcribing: { label: 'Transcribing', tone: 'text-violet-200 bg-violet-500/20' },
  routing: { label: 'Filing', tone: 'text-violet-200 bg-violet-500/20' },
  applied: { label: 'Filed', tone: 'text-emerald-200 bg-emerald-500/20' },
  needs_review: { label: 'Needs a pick', tone: 'text-amber-100 bg-amber-400/20' },
  failed: { label: 'Waiting to retry', tone: 'text-amber-100 bg-amber-400/20' },
  undone: { label: 'Undone', tone: 'text-slate-400 bg-white/5' },
}
const STATUS_DOT: Record<string, string> = { critical: '#f43f5e', warning: '#f59e0b', routine_due: '#fb923c', info: '#38bdf8' }

function ago(ms: number) {
  const s = Math.round((Date.now() - ms) / 1000)
  if (s < 50) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return new Date(ms).toLocaleDateString()
}

function Status() {
  const { online, reachable, live, farm, pairing, refresh } = usePhone(useShallow((s) => ({ online: s.online, reachable: s.reachable, live: s.live, farm: s.farm, pairing: s.pairing, refresh: s.refresh })))
  const [label, tone, Icon] = !online ? ['No network: notes wait on the phone', 'text-amber-200', CloudOff]
    : reachable === false ? ['Brain not reachable: notes wait on the phone', 'text-amber-200', CloudOff]
    : live === 'live' ? ['Live', 'text-emerald-300', Wifi] : ['Connecting…', 'text-slate-400', Loader2]
  return (
    <header className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-lg font-semibold text-slate-50">{farm ?? pairing?.name ?? pairing?.ws}</p>
        <button type="button" onClick={() => void refresh()} className={`flex items-center gap-1.5 text-xs ${tone}`}>
          <Icon className={`size-3.5 ${Icon === Loader2 ? 'animate-spin' : ''}`} />{label}
        </button>
      </div>
      <Menu />
    </header>
  )
}

function Menu() {
  const unpair = usePhone((s) => s.unpair)
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button type="button" aria-label="Menu" onClick={() => setOpen((o) => !o)} className="grid size-10 place-items-center rounded-full bg-white/5 text-slate-300">
        <ChevronDown className="size-5" />
      </button>
      {open && (
        <div className="nc-glass absolute right-0 top-12 z-20 w-56 rounded-2xl p-2 text-sm">
          <p className="px-3 py-2 text-xs text-slate-400">{usePhone.getState().pairing?.url}</p>
          <button type="button" onClick={() => { setOpen(false); void unpair() }} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-rose-200 hover:bg-white/5">
            <LogOut className="size-4" />Disconnect this phone
          </button>
        </div>
      )}
    </div>
  )
}

function ContextPicker() {
  const { map, context, setContext } = usePhone(useShallow((s) => ({ map: s.map, context: s.context, setContext: s.setContext })))
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  // the farm as a tree that opens a branch at a time (the same fold logic as the desktop map); a search is a flat list
  const tree = useMemo(() => {
    const ns = (map?.nodes ?? []).filter((n) => (n.type === 'root' || n.type === 'category' || n.type === 'entity') && !n.virtual)
    return { by: new Map(ns.map((n) => [n.id, n])), idx: F.indexTree(ns.map((n) => ({ id: n.id, parent_id: n.type === 'root' ? null : n.parent_id }))) }
  }, [map])
  const [fold, setFold] = useState<F.FoldState>(F.mainAreas())
  const found = useMemo(() => (!q ? [] : (map?.nodes ?? []).filter((n) => (n.type === 'category' || n.type === 'entity') && !n.virtual
    && `${n.path} ${n.title}`.toLowerCase().includes(q.toLowerCase())).slice(0, 60)), [map, q])
  const rows = useMemo(() => (q ? found.map((n) => ({ n, depth: 0 })) : F.visible(tree.idx, fold)
    .filter((id) => tree.by.get(id)?.type !== 'root').map((id) => ({ n: tree.by.get(id)!, depth: (tree.idx.depth.get(id) ?? 1) - 1 }))),
  [q, found, tree, fold])
  const pick = (n: { id: string; title: string }) => { setContext({ id: n.id, title: n.title }); setOpen(false) }
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="mx-auto flex max-w-full items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200">
        <CircleDot className="size-4 shrink-0 text-sky-300" />
        <span className="truncate">{context ? `On ${context.title}` : 'On the whole farm'}</span>
        <ChevronDown className="size-4 shrink-0 text-slate-400" />
      </button>
      {open && (
        <div className="fixed inset-0 z-40 flex flex-col bg-slate-950/95 backdrop-blur-xl" role="dialog" aria-label="Record onto">
          <div className="safe flex items-center gap-2 py-3">
            {/* biome-ignore lint/a11y/noAutofocus: the owner just tapped "Record onto": typing the branch is the next step */}
            <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a branch: tractor, field 704…"
              className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-500 focus:outline-none" />
            <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="grid size-10 place-items-center rounded-full bg-white/10"><X className="size-5" /></button>
          </div>
          <ul className="safe flex-1 space-y-1 overflow-y-auto pb-8" role={q ? undefined : 'tree'} aria-label="Branches">
            <li>
              <button type="button" onClick={() => { setContext(null); setOpen(false) }} className="w-full rounded-xl px-3 py-3 text-left text-slate-200 hover:bg-white/5">
                Whole farm <span className="text-xs text-slate-500">· the brain decides where</span>
              </button>
            </li>
            {rows.map(({ n, depth }) => {
              const kids = (tree.idx.children.get(n.id)?.length ?? 0) > 0 && !q
              const isOpen = kids && F.isOpen(tree.idx, fold, n.id)
              return (
                <li key={n.id} className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}
                  {...(q ? {} : { role: 'treeitem', 'aria-level': depth + 1, 'aria-expanded': kids ? isOpen : undefined })}>
                  {kids
                    ? <button type="button" onClick={() => setFold(F.toggle(tree.idx, fold, n.id))} aria-label={isOpen ? `Fold ${n.title}` : `Open ${n.title}`}
                        className="grid size-9 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-white/5">
                        {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                      </button>
                    : <span className="size-9 shrink-0" />}
                  <button type="button" onClick={() => pick(n)} className="flex min-w-0 flex-1 items-center gap-3 rounded-xl px-2 py-2.5 text-left hover:bg-white/5">
                    <span className="size-2 shrink-0 rounded-full" style={{ background: STATUS_DOT[n.display_status ?? ''] ?? '#34d399' }} />
                    <span className="min-w-0">
                      <span className="block truncate text-[15px] text-slate-100">{n.title}</span>
                      {q && <span className="block truncate text-xs text-slate-500">{n.path}</span>}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </>
  )
}

function RecordButton() {
  const { rec, level, recStartedAt, toggleRecording, error } = usePhone(useShallow((s) => ({ rec: s.rec, level: s.level, recStartedAt: s.recStartedAt, toggleRecording: s.toggleRecording, error: s.error })))
  const [, tick] = useState(0)
  useEffect(() => {
    if (rec !== 'recording') return
    const t = setInterval(() => tick((n) => n + 1), 250)
    return () => clearInterval(t)
  }, [rec])
  const secs = rec === 'recording' ? Math.floor((Date.now() - recStartedAt) / 1000) : 0
  const on = rec === 'recording'
  return (
    <div className="flex flex-col items-center gap-3 py-4">
      <button
        type="button"
        onClick={() => void toggleRecording()}
        aria-label={on ? 'Stop and save the note' : 'Record a note'}
        className={`relative grid size-36 place-items-center rounded-full transition-all duration-200 active:scale-95 ${on ? 'bg-rose-500 text-white' : 'bg-gradient-to-br from-sky-500 to-emerald-500 text-white'}`}
        style={{ boxShadow: on ? `0 0 0 ${8 + level * 40}px rgb(244 63 94 / 0.25), 0 20px 50px -10px rgb(244 63 94 / 0.6)` : '0 20px 50px -12px rgb(56 189 248 / 0.6)' }}
      >
        {rec === 'arming' ? <Loader2 className="size-12 animate-spin" /> : on ? <Square className="size-11 fill-current" /> : <Mic className="size-14" />}
      </button>
      <p className="h-5 text-sm text-slate-300" aria-live="polite">
        {on ? `Recording ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, '0')} · tap to save` : 'Tap to talk, tap again to save'}
      </p>
      {error && <p className="text-sm text-amber-200">{error}</p>}
    </div>
  )
}

function TypeNote() {
  const sendText = usePhone((s) => s.sendText)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="mx-auto flex items-center gap-2 text-sm text-slate-400">
        <Keyboard className="size-4" />Type a note instead
      </button>
    )
  }
  return (
    <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); void sendText(text); setText(''); setOpen(false) }}>
      {/* biome-ignore lint/a11y/noAutofocus: the owner just tapped "Type a note" */}
      <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Wheel needs changing on the John Deere…"
        aria-label="Note" className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2.5 text-[15px] text-slate-100 placeholder:text-slate-500 focus:outline-none" />
      <button type="submit" aria-label="Save note" className="grid size-11 place-items-center rounded-xl bg-sky-500 text-white"><Send className="size-5" /></button>
    </form>
  )
}

function Row({ it }: { it: OutboxItem }) {
  const { retry, discard, undo } = usePhone(useShallow((s) => ({ retry: s.retry, discard: s.discard, undo: s.undo })))
  const s = STATE[it.state] ?? STATE.saved
  return (
    <li className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.tone}`}>{s.label}{it.state === 'uploading' ? ` ${Math.round(it.progress * 100)}%` : ''}</span>
        <span className="text-xs text-slate-500">{ago(it.createdAt)}{it.kind === 'audio' ? ` · ${(it.size / 1024).toFixed(0)} KB` : ''}</span>
      </div>
      {it.state === 'uploading' && <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10"><div className="h-full bg-sky-400 transition-all" style={{ width: `${it.progress * 100}%` }} /></div>}
      <p className="mt-2 text-[15px] text-slate-100">{it.transcript || it.text || (it.kind === 'audio' ? 'Voice note' : '')}</p>
      {(it.summary || it.contextTitle) && <p className="mt-1 text-xs text-slate-400">{it.summary || `on ${it.contextTitle}`}</p>}
      {it.error && it.state === 'failed' && <p className="mt-1 text-xs text-amber-200">{it.error}</p>}
      <div className="mt-2 flex gap-2">
        {it.state === 'applied' && <button type="button" onClick={() => void undo(it.id)} className="flex items-center gap-1 rounded-full bg-white/10 px-3 py-1 text-xs text-slate-100"><Undo2 className="size-3.5" />Undo</button>}
        {it.state === 'failed' && <button type="button" onClick={() => void retry(it.id)} className="flex items-center gap-1 rounded-full bg-white/10 px-3 py-1 text-xs text-slate-100"><RefreshCw className="size-3.5" />Send now</button>}
        {['saved', 'failed', 'undone', 'applied', 'needs_review'].includes(it.state) && (
          <button type="button" onClick={() => void discard(it.id)} className="flex items-center gap-1 rounded-full px-3 py-1 text-xs text-slate-400">
            <Trash2 className="size-3.5" />{['saved', 'failed'].includes(it.state) ? 'Delete' : 'Remove from list'}
          </button>
        )}
      </div>
    </li>
  )
}

function NativeRow({ it }: { it: NativeItem }) {
  const s = STATE[it.state] ?? STATE.saved
  return (
    <li className="rounded-2xl border border-violet-400/20 bg-violet-500/[0.06] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${s.tone}`}>{s.label}{it.state === 'uploading' ? ` ${Math.round(it.progress * 100)}%` : ''}</span>
        <span className="text-xs text-slate-500">bubble · {ago(it.createdAt)}</span>
      </div>
      {it.error && <p className="mt-1 text-xs text-amber-200">{it.error}</p>}
    </li>
  )
}

function Outbox() {
  const { items, native } = usePhone(useShallow((s) => ({ items: s.items, native: s.native })))
  const waiting = items.filter((i) => ['saved', 'uploading', 'failed'].includes(i.state)).length + native.filter((n) => n.state !== 'uploaded').length
  if (!items.length && !native.length) return null
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200">
        <MessageCircle className="size-4 text-sky-300" />Notes from this phone
        {waiting > 0 && <span className="rounded-full bg-amber-400/20 px-2 text-xs text-amber-100">{waiting} waiting</span>}
      </h2>
      <ul className="space-y-2">
        {native.filter((n) => n.state !== 'uploaded').map((n) => <NativeRow key={n.id} it={n} />)}
        {items.slice(0, 30).map((it) => <Row key={it.id} it={it} />)}
      </ul>
    </section>
  )
}

function NeedsWork() {
  const map = usePhone((s) => s.map)
  const work = (map?.nodes ?? []).filter((n) => n.type === 'entity' || n.type === 'category')
    .filter((n) => !n.virtual && (n.counts.open_alerts > 0 || n.counts.open_tasks > 0))
    .sort((a, b) => b.counts.open_alerts - a.counts.open_alerts || b.counts.open_tasks - a.counts.open_tasks).slice(0, 8)
  const tasks = (map?.nodes ?? []).filter((n) => n.type === 'task')
  if (!work.length) return null
  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-200"><ListTodo className="size-4 text-sky-300" />Needs work</h2>
      <ul className="space-y-1.5">
        {work.map((n) => (
          <li key={n.id} className="rounded-xl bg-white/[0.03] px-3 py-2">
            <div className="flex items-center gap-2">
              {n.counts.open_alerts > 0 ? <AlertTriangle className="size-4 shrink-0" style={{ color: STATUS_DOT[n.display_status ?? ''] ?? '#f59e0b' }} /> : <Check className="size-4 shrink-0 text-slate-500" />}
              <span className="truncate text-[15px] text-slate-100">{n.title}</span>
              <span className="ml-auto shrink-0 text-xs text-slate-500">{n.counts.open_tasks} task{n.counts.open_tasks === 1 ? '' : 's'}</span>
            </div>
            {tasks.filter((t) => t.parent_id === n.id).slice(0, 2).map((t) => (
              <p key={t.id} className="truncate pl-6 text-xs text-slate-400">{t.title}{t.assignee ? ` · ${t.assignee.split(' ')[0]}` : ''}</p>
            ))}
          </li>
        ))}
      </ul>
    </section>
  )
}

function BubbleCard() {
  const [running, setRunning] = useState(false)
  const [allowed, setAllowed] = useState(true)
  useEffect(() => {
    void Native.bubbleRunning().then(setRunning)
    void Native.overlayAllowed().then(setAllowed)
    const back = () => { if (!document.hidden) void Native.overlayAllowed().then(setAllowed) }
    document.addEventListener('visibilitychange', back)
    return () => document.removeEventListener('visibilitychange', back)
  }, [])
  if (platform !== 'android' || !Native.available) return null
  const toggle = async () => {
    if (running) { await Native.stopBubble(); setRunning(false); return }
    const r = await Native.startBubble()
    setRunning(r.started)
  }
  return (
    <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">Capture bubble</p>
          <p className="text-xs text-slate-400">A mic that floats over other apps. Tap it to record, tap again to save; it sends on its own.</p>
        </div>
        <button type="button" role="switch" aria-checked={running} onClick={() => void toggle()}
          className={`relative h-7 w-12 shrink-0 rounded-full transition ${running ? 'bg-emerald-500' : 'bg-white/15'}`}>
          <span className={`absolute top-1 size-5 rounded-full bg-white transition-all ${running ? 'left-6' : 'left-1'}`} />
        </button>
      </div>
      {!allowed && (
        <button type="button" onClick={() => void Native.openOverlaySettings()} className="mt-2 text-xs text-sky-300 underline">
          Allow "Display over other apps" for the floating bubble (the notification button works without it)
        </button>
      )}
    </section>
  )
}

export function Home() {
  return (
    <main className="safe mx-auto flex min-h-full max-w-md flex-col gap-5 pb-10 pt-4">
      <Status />
      <ContextPicker />
      <RecordButton />
      <TypeNote />
      <BubbleCard />
      <Outbox />
      <NeedsWork />
    </main>
  )
}
