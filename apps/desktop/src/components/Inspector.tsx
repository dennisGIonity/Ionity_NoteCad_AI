// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Node inspector: status, progress, open tasks and alerts, the full action log, a mic that records a note for
// this node (context-anchored capture) and a companion ask bar that knows which node is open.
import {
  AlertTriangle, ArrowUp, Bot, Check, CircleDot, History, ListTodo, Loader2, Mic, NotebookPen, Square, Undo2, X,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useRecorder } from '../lib/recorder'
import { useApp } from '../lib/store'
import type { HistoryItem, NodeDetail } from '../lib/types'
import { ago, cls, due, iconFor, progressLabel, STATUS_LABEL, statusColor } from '../lib/ui'
import { Ring } from './nodes/Cards'

type Tab = 'tasks' | 'notes' | 'history'

const VERB: Record<string, string> = {
  append_note: 'Note', create_task: 'Task', create_alert: 'Alert', set_status: 'Status', update_attributes: 'Numbers',
  link_nodes: 'Link', create_node: 'New branch', upsert_profile_fact: 'Fact',
}

function describeItem(h: HistoryItem): string {
  const d = h.detail as Record<string, unknown>
  if (h.type === 'append_note') return String(d.text ?? '')
  if (h.type === 'create_task') return `${d.title}${d.assignee_hint ? ` → ${d.assignee_hint}` : ''}${d.due_at ? ` · ${due(d.due_at as string)}` : ''}`
  if (h.type === 'create_alert') return `${d.severity}: ${d.title}`
  if (h.type === 'set_status') return `${STATUS_LABEL[d.status as keyof typeof STATUS_LABEL] ?? d.status}${d.reason ? ` · ${d.reason}` : ''}`
  if (h.type === 'update_attributes') {
    const parts = [...Object.entries((d.set as object) ?? {}), ...Object.entries((d.increment as object) ?? {}).map(([k, v]) => [k, `+${v}`])]
    return parts.map(([k, v]) => `${k} ${v}`).join(', ')
  }
  if (h.type === 'link_nodes') return String(d.edge_type ?? '')
  return h.type
}

/** The companion answers in light markdown: **bold** and "* " / "- " bullets. Rendered as text, never as HTML. */
function keyed(parts: string[]): [string, string, number][] {
  const seen = new Map<string, number>()  // the same words twice get their own key, without using positions
  return parts.map((p, i) => {
    const n = (seen.get(p) ?? 0) + 1
    seen.set(p, n)
    return [`${n}:${p}`, p, i]
  })
}

function Reply({ text }: { text: string }) {
  const bold = (line: string) => keyed(line.split(/\*\*(.+?)\*\*/g)).map(([k, part, i]) =>
    i % 2 ? <strong key={k} className="font-semibold text-white">{part}</strong> : <span key={k}>{part}</span>)
  return (
    <div className="mt-1 space-y-1 text-slate-100">
      {keyed(text.split('\n').filter((l) => l.trim())).map(([k, l]) => {
        const m = l.match(/^\s*[*-]\s+(.*)$/)
        return m
          ? <p key={k} className="flex gap-1.5 pl-1"><span className="text-violet-300">•</span><span>{bold(m[1])}</span></p>
          : <p key={k}>{bold(l)}</p>
      })}
    </div>
  )
}

export function Inspector() {
  const { selected, select, map, ws } = useApp()
  const rec = useRecorder()
  const node = map?.nodes.find((n) => n.id === selected)
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [tab, setTab] = useState<Tab>('tasks')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<{ q: string; a?: string; err?: string; ms?: number } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!selected) return
    try {
      const [d, h] = await Promise.all([api.node(selected), api.history(selected)])
      setDetail(d)
      setHistory(h)
    } catch { setDetail(null) }
  }, [selected])

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset and load only when another node is selected
  useEffect(() => { setDetail(null); setHistory([]); setAnswer(null); setQuestion(''); void load() }, [selected])
  // biome-ignore lint/correctness/useExhaustiveDependencies: reload when the map changed (a note landed)
  useEffect(() => { if (selected) void load() }, [map?.generated_at])

  const open = !!selected && !!node
  const recordingHere = (rec.state === 'recording' || rec.state === 'arming') && rec.contextNodeId === selected
  const Icon = node ? iconFor(node) : NotebookPen
  const st = node?.display_status ?? 'ok'
  const openTasks = detail?.tasks.filter((t) => t.state === 'open') ?? []
  const openAlerts = detail?.alerts.filter((a) => !a.resolved_at) ?? []

  const ask = async () => {
    const q = question.trim()
    if (!q || !selected) return
    setAnswer({ q })
    setQuestion('')
    try {
      const r = await api.ask(ws, q, selected)
      setAnswer({ q, a: r.reply, ms: r.ms })
    } catch (e) { setAnswer({ q, err: (e as Error).message }) }
  }
  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key)
    try { await fn() } catch { /* the map refresh shows the real state */ }
    setBusy(null)
    void load()
  }

  return (
    <aside
      aria-hidden={!open}
      className={cls('nc-glass pointer-events-auto absolute bottom-24 right-4 top-4 z-20 flex w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-3xl shadow-2xl shadow-black/50 transition-all duration-300',
        open ? 'translate-x-0 opacity-100' : 'pointer-events-none translate-x-[110%] opacity-0')}
    >
      {node && (
        <>
          <header className="flex items-start gap-3 border-b border-white/10 p-4">
            <Ring pct={node.progress_pct} size={48} color="#34d399">
              <div className="grid size-9 place-items-center rounded-full" style={{ boxShadow: `0 0 0 2px ${statusColor(st)}` }}>
                <Icon className="size-4 text-slate-100" />
              </div>
            </Ring>
            <div className="min-w-0 flex-1">
              <h2 className="truncate text-base font-semibold text-slate-50">{node.title}</h2>
              <p className="truncate text-xs text-slate-400">{node.path}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="rounded-full px-2 py-0.5 font-medium" style={{ background: `${statusColor(st)}22`, color: statusColor(st) }}>{STATUS_LABEL[st]}</span>
                {progressLabel(node) && <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-emerald-200">{progressLabel(node)}</span>}
                {node.updated_at && <span className="text-slate-500">updated {ago(node.updated_at)}</span>}
              </div>
            </div>
            <button type="button" aria-label="Close" onClick={() => select(null)} className="grid size-8 place-items-center rounded-full text-slate-400 hover:bg-white/10"><X className="size-4" /></button>
          </header>

          <div className="flex gap-2 p-4 pb-2">
            <button
              type="button"
              onClick={() => rec.toggle(selected)}
              className={cls('flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium transition',
                recordingHere ? 'bg-rose-500 text-white shadow-lg shadow-rose-500/30' : 'bg-sky-500/90 text-white hover:bg-sky-400')}
            >
              {recordingHere ? <><Square className="size-4 fill-current" />Stop and send</> : <><Mic className="size-4" />Record note for this node</>}
            </button>
          </div>
          {openAlerts.length > 0 && (
            <div className="mx-4 mb-1 space-y-1.5">
              {openAlerts.map((a) => (
                <div key={a.id} className="flex items-center gap-2 rounded-xl border border-rose-400/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
                  <AlertTriangle className="size-4 shrink-0" />
                  <span className="min-w-0 flex-1 truncate" title={a.title}>{a.title}</span>
                  <button type="button" disabled={busy === a.id} onClick={() => act(a.id, () => api.resolveAlert(a.id))}
                    className="shrink-0 rounded-full bg-white/10 px-2 py-0.5 hover:bg-white/20">{busy === a.id ? '…' : 'Resolve'}</button>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-1 px-4 pt-2 text-xs" role="tablist">
            {([['tasks', ListTodo, `Tasks ${openTasks.length || ''}`], ['notes', NotebookPen, 'Notes'], ['history', History, 'History']] as const).map(([k, I, label]) => (
              <button key={k} role="tab" aria-selected={tab === k} type="button" onClick={() => setTab(k)}
                className={cls('flex items-center gap-1.5 rounded-lg px-2.5 py-1.5', tab === k ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-slate-200')}>
                <I className="size-3.5" />{label}
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {!detail && <Loader2 className="mx-auto mt-6 size-5 animate-spin text-slate-500" />}
            {detail && tab === 'tasks' && (
              openTasks.length ? (
                <ul className="space-y-1.5">
                  {openTasks.map((t) => (
                    <li key={t.id} className="flex items-start gap-2.5 rounded-xl bg-white/5 px-3 py-2">
                      <button type="button" aria-label="Mark done" disabled={busy === t.id} onClick={() => act(t.id, () => api.taskState(t.id, 'done'))}
                        className="mt-0.5 grid size-4.5 shrink-0 place-items-center rounded-full border border-slate-500 text-transparent hover:border-emerald-400 hover:text-emerald-400">
                        {busy === t.id ? <Loader2 className="size-3 animate-spin text-slate-300" /> : <Check className="size-3" />}
                      </button>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-slate-100">{t.title}</p>
                        <p className="text-[11px] text-slate-400">
                          {[t.priority !== 'normal' && t.priority, t.assignee_hint && `for ${t.assignee_hint}`, t.due_at && due(t.due_at),
                            t.node_id !== selected && detail.children.find((c) => c.id === t.node_id)?.title].filter(Boolean).join(' · ') || 'open'}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-4 text-center text-xs text-slate-500">No open tasks here.</p>
            )}
            {detail && tab === 'notes' && (
              detail.notes.length ? (
                <ul className="space-y-2">
                  {detail.notes.slice(0, 40).map((n) => (
                    <li key={n.id} className="rounded-xl bg-white/5 px-3 py-2">
                      <p className="text-sm text-slate-100">{n.body}</p>
                      <p className="mt-0.5 text-[10px] text-slate-500">{ago(n.created_at)} · {n.author.replace('ai:', 'filed by ')}</p>
                    </li>
                  ))}
                </ul>
              ) : <p className="mt-4 text-center text-xs text-slate-500">No notes yet. Record one above.</p>
            )}
            {detail && tab === 'history' && (
              history.length ? (
                <ol className="relative space-y-3 border-l border-white/10 pl-4">
                  {history.map((h) => (
                    <li key={h.id} className={cls('relative', h.undone && 'opacity-50')}>
                      <span className="absolute -left-[21px] top-1 grid size-2.5 place-items-center rounded-full bg-slate-500" style={{ background: h.type === 'create_alert' ? '#f43f5e' : h.type === 'create_task' ? '#38bdf8' : h.type === 'update_attributes' ? '#34d399' : '#94a3b8' }} />
                      <p className={cls('text-xs text-slate-200', h.undone && 'line-through')}>
                        <span className="font-semibold text-slate-100">{VERB[h.type] ?? h.type}</span>{h.channel && <span className="text-slate-400"> · {h.channel}</span>} — {describeItem(h)}
                      </p>
                      <p className="mt-0.5 text-[10px] text-slate-500">
                        {ago(h.at)}{h.router ? ` · ${h.router}` : ''}{h.actor === 'user:inbox' ? ' · placed by you' : ''}{h.undone ? ' · undone' : ''}
                      </p>
                      {h.capture_text && <p className="mt-0.5 truncate text-[10px] italic text-slate-500" title={h.capture_text}>“{h.capture_text}”</p>}
                      {h.audio && h.capture_id && history.findIndex((x) => x.capture_id === h.capture_id) === history.indexOf(h) && (
                        // biome-ignore lint/a11y/useMediaCaption: the owner's own voice note; its transcript is the line above
                        <audio controls preload="none" src={api.audioUrl(h.capture_id)} aria-label="Play the voice note" className="mt-1 h-7 w-full max-w-60" />
                      )}
                      {!h.undone && h.capture_id && history.findIndex((x) => x.capture_id === h.capture_id) === history.indexOf(h) && (
                        <button type="button" onClick={() => act(`u${h.capture_id}`, () => api.undo(h.capture_id!))}
                          className="mt-1 flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-100">
                          <Undo2 className="size-3" />{busy === `u${h.capture_id}` ? 'Undoing…' : 'Undo this note'}
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              ) : <p className="mt-4 text-center text-xs text-slate-500">Nothing has changed here yet.</p>
            )}
            {detail && detail.children.length > 0 && tab === 'tasks' && (
              <div className="mt-4">
                <p className="mb-1.5 text-[10px] uppercase tracking-wide text-slate-500">Under this</p>
                <div className="flex flex-wrap gap-1.5">
                  {detail.children.filter((c) => c.kind !== 'channel').map((c) => (
                    <button key={c.id} type="button" onClick={() => select(c.id)}
                      className="flex items-center gap-1.5 rounded-full bg-white/5 px-2.5 py-1 text-xs text-slate-200 hover:bg-white/10">
                      <CircleDot className="size-3" style={{ color: statusColor(c.display_status) }} />{c.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <footer className="border-t border-white/10 p-3">
            {answer && (
              <div className="mb-2 max-h-40 overflow-y-auto rounded-xl bg-white/5 p-2.5 text-xs">
                <p className="text-slate-400">{answer.q}</p>
                {answer.a ? <div data-companion-reply><Reply text={answer.a} /></div>
                  : answer.err ? <p className="mt-1 text-rose-300">{answer.err}</p>
                  : <Loader2 className="mt-1 size-4 animate-spin text-slate-400" />}
              </div>
            )}
            <form className="flex items-center gap-2 rounded-xl bg-white/5 px-2.5 py-1.5" onSubmit={(e) => { e.preventDefault(); void ask() }}>
              <Bot className="size-4 shrink-0 text-violet-300" />
              <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={`Ask about ${node.title}…`} aria-label="Ask the companion"
                className="min-w-0 flex-1 bg-transparent py-1 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none" />
              <button type="submit" aria-label="Ask" disabled={!question.trim()} className="grid size-7 place-items-center rounded-lg bg-violet-500/80 text-white disabled:opacity-30">
                <ArrowUp className="size-4" />
              </button>
            </form>
          </footer>
        </>
      )}
    </aside>
  )
}
