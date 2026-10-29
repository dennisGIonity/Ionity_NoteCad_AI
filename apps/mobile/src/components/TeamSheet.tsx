// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Team & Inbox on the phone (ADR 0014, decision 27): proposals to approve or reject, and an invite to share with a new
// person (a one-time link they open on their own phone). Owners and managers; an employee sees what they proposed.
import { Check, Copy, Loader2, Share2, UserPlus, X } from 'lucide-react'
import { useState } from 'react'
import { usePhone } from '../lib/phone'

export function TeamSheet({ onClose }: { onClose: () => void }) {
  const me = usePhone((s) => s.me)
  const inbox = usePhone((s) => s.inbox)
  const decide = usePhone((s) => s.decide)
  const invite = usePhone((s) => s.invite)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [role, setRole] = useState<'employee' | 'manager'>('employee')
  const [link, setLink] = useState<string | null>(null)
  const canInvite = me?.capabilities.invite === 'allow'

  const run = async (id: string, f: () => Promise<string | null>) => {
    setBusy(id)
    setErr(await f())
    setBusy(null)
  }
  const make = async () => {
    setBusy('invite')
    const r = await invite(name.trim(), role)
    setBusy(null)
    if (r.error) setErr(r.error)
    else { setLink(r.link ?? null); setName('') }
  }
  const share = async () => {
    if (!link) return
    const nav = navigator as Navigator & { share?: Navigator['share'] }
    if (nav.share) await nav.share({ title: 'IBMM invite', text: link }).catch(() => undefined)
    else await nav.clipboard?.writeText(link)
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="team-title" className="fixed inset-0 z-50 grid place-items-end bg-black/60 p-3 sm:place-items-center">
      <div className="nc-glass max-h-[85vh] w-full max-w-md overflow-y-auto rounded-2xl p-4">
        <div className="flex items-center justify-between">
          <h2 id="team-title" className="text-base font-semibold text-slate-50">Team & Inbox</h2>
          <button type="button" aria-label="Close" onClick={onClose} className="grid size-8 place-items-center rounded-full text-slate-300 hover:bg-white/10"><X className="size-4" /></button>
        </div>

        <ul className="mt-3 space-y-2">
          {inbox.filter((i) => i.kind !== 'place').length === 0 && <li className="text-sm text-slate-400">No proposals waiting.</li>}
          {inbox.filter((i) => i.kind !== 'place').map((i) => {
            const mine = !!me?.member_id && i.author_member_id === me.member_id
            return (
              <li key={i.id} className="rounded-xl bg-white/5 p-3 text-sm">
                <p className="text-slate-100">{i.question}</p>
                {mine ? <p className="mt-1 text-xs text-slate-400">Waiting for approval</p> : (
                  <div className="mt-2 flex gap-2">
                    <button type="button" disabled={busy === i.id} onClick={() => void run(i.id, () => decide(i.id, 'approve'))}
                      className="flex items-center gap-1 rounded-full bg-emerald-500/25 px-3 py-1.5 text-xs text-emerald-100"><Check className="size-3.5" />Approve</button>
                    <button type="button" disabled={busy === i.id} onClick={() => void run(i.id, () => decide(i.id, 'reject'))}
                      className="rounded-full px-3 py-1.5 text-xs text-slate-300">Reject</button>
                    {busy === i.id && <Loader2 className="size-4 animate-spin self-center" />}
                  </div>
                )}
              </li>
            )
          })}
        </ul>

        {canInvite && (
          <section className="mt-4 border-t border-white/10 pt-3">
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-100"><UserPlus className="size-4 text-sky-300" />Invite someone</p>
            <input aria-label="Their name" placeholder="Their name" value={name} onChange={(e) => setName(e.target.value)}
              className="mt-2 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100" />
            {me?.level === 1 && (
              <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as 'employee' | 'manager')}
                className="mt-2 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100">
                <option value="employee">Employee</option><option value="manager">Manager</option>
              </select>
            )}
            <button type="button" disabled={!name.trim() || busy === 'invite'} onClick={() => void make()}
              className="mt-2 w-full rounded-xl bg-sky-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Make the invite</button>
            {link && (
              <div className="mt-2 rounded-xl bg-sky-400/10 p-3 text-xs text-slate-200">
                <p className="break-all">{link}</p>
                <button type="button" onClick={() => void share()} className="mt-2 inline-flex items-center gap-1 rounded-full bg-white/10 px-3 py-1">
                  {'share' in navigator ? <Share2 className="size-3.5" /> : <Copy className="size-3.5" />}Send it to them (works once)
                </button>
              </div>
            )}
          </section>
        )}
        {err && <p role="alert" className="mt-2 text-sm text-rose-300">{err}</p>}
      </div>
    </div>
  )
}
