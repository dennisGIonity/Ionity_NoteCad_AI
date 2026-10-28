// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// What the last note changed: the branches touched, one-click Undo (the brain's inverse transaction), and
// branch pills when the brain needs the owner to place a note (the choice also teaches it the owner's words).
import { AlertTriangle, Check, CheckCircle2, ListTodo, Loader2, NotebookPen, Sprout, Undo2, UserRoundCheck, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useRecorder } from '../lib/recorder'
import { headline, summarise, useApp } from '../lib/store'
import type { CaptureView } from '../lib/types'
import { cls } from '../lib/ui'

const SHOW_MS = 20000

function actionIcons(a: CaptureView['applied'][0]) {
  const out = []
  if (a.alerts) out.push(<AlertTriangle key="a" className="size-3.5 text-amber-300" aria-label="alert" />)
  if (a.tasks) out.push(<ListTodo key="t" className="size-3.5 text-sky-300" aria-label="task" />)
  if (a.actions.includes('update_attributes')) out.push(<Sprout key="p" className="size-3.5 text-emerald-300" aria-label="progress" />)
  if (a.delegated.length) out.push(<UserRoundCheck key="d" className="size-3.5 text-violet-300" aria-label="delegated" />)
  if (!out.length) out.push(<NotebookPen key="n" className="size-3.5 text-slate-300" aria-label="note" />)
  return out
}

export function ActionToast() {
  const captures = useApp((s) => s.captures)
  const activeCapture = useApp((s) => s.activeCapture)
  const cap = activeCapture ? captures[activeCapture] : undefined
  const [hidden, setHidden] = useState<string | null>(null)
  const [hover, setHover] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [, tick] = useState(0)

  const openInbox = cap?.inbox.filter((i) => !i.resolved && !i.dismissed) ?? []
  const finished = !!cap?.finishedAt && cap.state !== 'failed'
  const fresh = finished && Date.now() - (cap!.finishedAt ?? 0) < SHOW_MS
  const recording = useRecorder((r) => r.state !== 'idle')
  const visible = !!cap && finished && !recording && hidden !== cap.id && (fresh || hover || openInbox.length > 0 || cap.state === 'undone')

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new finish time restarts the hide timer
  useEffect(() => {
    if (!finished) return
    const t = setTimeout(() => tick((n) => n + 1), SHOW_MS + 100)
    return () => clearTimeout(t)
  }, [finished, cap?.finishedAt])
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new capture clears the last error
  useEffect(() => { setErr(null) }, [activeCapture])

  if (!cap || !visible) return null
  const s = summarise(cap)
  const nodes = cap.applied.flatMap((a) => a.nodes.map((n) => ({ ...n, a })))
  const uniq = [...new Map(nodes.map((n) => [n.map_id, n])).values()]
  const undone = cap.state === 'undone'
  const resolvedTo = cap.inbox.find((i) => i.resolved)
  const placed = resolvedTo ? resolvedTo.options.find((o) => o.node_id === resolvedTo.resolved)?.label ?? 'the map' : null

  const undo = async () => {
    setBusy('undo')
    setErr(null)
    try { await api.undo(cap.id) } catch (e) { setErr((e as Error).message) }
    setBusy(null)
  }
  const place = async (inboxId: string, nodeId: string) => {
    setBusy(inboxId)
    setErr(null)
    try {
      await api.resolveInbox(inboxId, nodeId)
      useApp.setState((st) => {
        const cur = st.captures[cap.id] ?? cap
        return { captures: { ...st.captures, [cap.id]: { ...cur, inbox: cur.inbox.map((i) => (i.inbox_id === inboxId ? { ...i, resolved: nodeId } : i)) } } }
      })
    } catch (e) { setErr((e as Error).message) }
    setBusy(null)
  }
  const skip = async (inboxId: string) => {
    setBusy(inboxId)
    try { await api.dismissInbox(inboxId) } catch { /* the item stays in the Inbox */ }
    useApp.setState((st) => {
      const cur = st.captures[cap.id] ?? cap
      return { captures: { ...st.captures, [cap.id]: { ...cur, inbox: cur.inbox.map((i) => (i.inbox_id === inboxId ? { ...i, dismissed: true } : i)) } } }
    })
    setBusy(null)
  }
  const open = (id: string) => useApp.getState().goTo(id)  // opens only the path to it, then selects it

  return (
    <div
      role="status"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="nc-glass nc-toast pointer-events-auto w-full max-w-[680px] rounded-2xl p-3 shadow-2xl shadow-black/40"
    >
      <div className="flex items-start gap-3">
        <div className={cls('mt-0.5 grid size-7 shrink-0 place-items-center rounded-full',
          undone ? 'bg-slate-500/20 text-slate-300' : openInbox.length ? 'bg-amber-400/15 text-amber-300' : 'bg-emerald-400/15 text-emerald-300')}>
          {undone ? <Undo2 className="size-4" /> : openInbox.length && !s.count ? <AlertTriangle className="size-4" /> : <CheckCircle2 className="size-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-slate-100">
            {undone ? 'Undone: nothing from this note is on the map' : s.count ? headline(s)
              : placed ? `Placed in ${placed.split(' > ').slice(-2).join(' / ')}` : 'One quick question'}
          </p>
          {cap.transcript && <p className="mt-0.5 truncate text-xs text-slate-400">“{cap.transcript}”</p>}
          {!undone && uniq.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {uniq.slice(0, 8).map((n) => (
                <button key={n.map_id} type="button" onClick={() => open(n.map_id)} title={n.map_path}
                  className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-slate-200 hover:bg-white/10">
                  {actionIcons(n.a)}
                  <span className="max-w-48 truncate">{n.map_path.split(' > ').slice(-2).join(' › ')}</span>
                </button>
              ))}
              {uniq.length > 8 && <span className="px-1 py-1 text-xs text-slate-400">+{uniq.length - 8} more</span>}
            </div>
          )}
          {openInbox.map((i) => (
            <div key={i.inbox_id} className="mt-2.5 rounded-xl border border-amber-300/20 bg-amber-300/5 p-2">
              <p className="text-xs text-amber-100">Where does “{i.text}” go?</p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {i.options.map((o) => (
                  <button key={o.node_id} type="button" data-inbox-option disabled={busy === i.inbox_id} onClick={() => place(i.inbox_id, o.node_id)}
                    className="rounded-full bg-amber-300/15 px-2.5 py-1 text-xs text-amber-50 transition hover:bg-amber-300/30 disabled:opacity-50">
                    {o.label.split(' > ').slice(-2).join(' › ')}
                  </button>
                ))}
                <button type="button" disabled={busy === i.inbox_id} onClick={() => skip(i.inbox_id)}
                  className="rounded-full px-2.5 py-1 text-xs text-slate-400 hover:bg-white/5">Leave in Inbox</button>
                {busy === i.inbox_id && <Loader2 className="size-4 animate-spin self-center text-amber-200" />}
              </div>
            </div>
          ))}
          {!undone && cap.inbox.some((i) => i.resolved) && (
            <p className="mt-2 flex items-center gap-1 text-xs text-emerald-300"><Check className="size-3.5" />Placed. NoteCad will remember those words for next time.</p>
          )}
          {err && <p className="mt-2 text-xs text-rose-300">{err}</p>}
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {!undone && (s.count > 0 || cap.inbox.some((i) => i.resolved)) && (
            <button type="button" onClick={undo} disabled={busy === 'undo'}
              className="flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-white/20 disabled:opacity-50">
              {busy === 'undo' ? <Loader2 className="size-3.5 animate-spin" /> : <Undo2 className="size-3.5" />}Undo
            </button>
          )}
          <button type="button" aria-label="Dismiss" onClick={() => setHidden(cap.id)} className="grid size-7 place-items-center rounded-full text-slate-400 hover:bg-white/10">
            <X className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
