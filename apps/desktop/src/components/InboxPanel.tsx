// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The Inbox (ADR 0014, decision 27): held notes to place, proposals to approve or reject (an employee's change, a
// change made on another device by someone whose role changed, a spoken role change to confirm). The brain sends
// only the items this person may see; Approve works only for what they may do themselves.
import { Check, Inbox, Loader2, X } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../lib/store'
import type { InboxOption } from '../lib/types'
import { ago } from '../lib/ui'

const KIND = { place: 'Where does it go?', approval: 'Proposal', sync: 'From another device' } as Record<string, string>

export function InboxPanel({ onClose }: { onClose: () => void }) {
  const items = useApp((s) => s.inbox)
  const me = useApp((s) => s.me)
  const refresh = useApp((s) => s.refreshInbox)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const run = async (id: string, f: () => Promise<unknown>) => {
    setBusy(id)
    setErr(null)
    try { await f(); await refresh(); void useApp.getState().refreshMap() } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }
  const options = (o: string | InboxOption[]): InboxOption[] => {
    if (Array.isArray(o)) return o
    try { return JSON.parse(o) as InboxOption[] } catch { return [] }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="inbox-title" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
      <div className="nc-glass flex max-h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl">
        <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <Inbox className="size-4 text-amber-300" />
          <h2 id="inbox-title" className="flex-1 text-sm font-semibold text-slate-50">Inbox</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="grid size-7 place-items-center rounded-full text-slate-400 hover:bg-white/10"><X className="size-4" /></button>
        </header>
        <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto p-4">
          {items.length === 0 && <li className="text-center text-xs text-slate-500">Nothing waiting.</li>}
          {items.map((i) => {
            const mine = !!me?.member_id && i.author_member_id === me.member_id
            return (
              <li key={i.id} data-inbox-item={i.kind} className="rounded-xl border border-white/10 bg-white/5 p-3">
                <p className="text-[10px] uppercase tracking-wide text-slate-400">{KIND[i.kind] ?? i.kind} · {ago(i.created_at)}</p>
                <p className="mt-1 text-sm text-slate-100">{i.question}</p>
                {i.event_text && i.kind !== 'place' && <p className="mt-0.5 truncate text-xs italic text-slate-400">“{i.event_text}”</p>}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {i.kind === 'place' && options(i.options).map((o) => (
                    <button key={o.node_id} type="button" disabled={busy === i.id} onClick={() => void run(i.id, () => api.resolveInbox(i.id, o.node_id))}
                      className="rounded-full bg-amber-300/15 px-2.5 py-1 text-xs text-amber-50 hover:bg-amber-300/30">{o.label.split(' > ').slice(-2).join(' › ')}</button>
                  ))}
                  {i.kind !== 'place' && !mine && (
                    <>
                      <button type="button" data-approve disabled={busy === i.id} onClick={() => void run(i.id, () => api.decide(i.id, 'approve'))}
                        className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-3 py-1 text-xs text-emerald-100 hover:bg-emerald-500/30"><Check className="size-3.5" />Approve</button>
                      <button type="button" data-reject disabled={busy === i.id} onClick={() => {
                        const reason = window.prompt('Why not? (the person sees this)') ?? undefined
                        void run(i.id, () => api.decide(i.id, 'reject', reason))
                      }} className="rounded-full px-3 py-1 text-xs text-slate-300 hover:bg-white/10">Reject</button>
                    </>
                  )}
                  {i.kind !== 'place' && mine && i.question.includes('confirm') && (
                    <button type="button" data-approve disabled={busy === i.id} onClick={() => void run(i.id, () => api.decide(i.id, 'approve'))}
                      className="flex items-center gap-1 rounded-full bg-emerald-500/20 px-3 py-1 text-xs text-emerald-100"><Check className="size-3.5" />Confirm</button>
                  )}
                  {i.kind !== 'place' && mine && !i.question.includes('confirm') && <span className="text-xs text-slate-400">Waiting for approval</span>}
                  {busy === i.id && <Loader2 className="size-4 animate-spin self-center text-slate-300" />}
                </div>
              </li>
            )
          })}
        </ul>
        {err && <p role="alert" className="border-t border-white/10 px-4 py-2 text-xs text-rose-300">{err}</p>}
      </div>
    </div>
  )
}
