// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The privacy notice (POPIA s18; the POPIA review's fix 5). Shown once to everyone who uses a workspace: an owner first
// fills in a contact and how long recordings, transcripts and the activity log are kept, then accepts; every other
// member reads it and says so. Open it again from People & seats. The brain records both (GET/PUT .../privacy).
import { Loader2, ShieldCheck, X } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useApp } from '../lib/store'
import type { PrivacyNotice as Notice, Retention } from '../lib/types'

export const OPEN_PRIVACY = 'nc-privacy-open'
/** An owner may put the setup off for a day on this computer ("Not now"); a member cannot. */
export const LATER = 'notecad.privacy.later'
const later = () => { try { return Number(localStorage.getItem(LATER) || 0) > Date.now() } catch { return false } }
const PERIODS: [keyof Retention, string][] = [
  ['audio_days', 'Voice recordings'], ['transcript_days', 'Transcripts of what was said'], ['log_days', 'Activity log (who did what)']]
const CHOICES = [30, 90, 180, 365, 730, 1825]

export function notNeeded(n: Notice | null) {
  return !n || (n.is_owner ? !!n.accepted_at : !!n.my_ack_at)
}

/** Opens by itself until the notice is accepted (owner) or read (member); and on the OPEN_PRIVACY event. */
export function PrivacyGate() {
  const ws = useApp((s) => s.ws)
  const [n, setN] = useState<Notice | null>(null)
  const [open, setOpen] = useState(false)
  const load = useCallback(async () => {
    if (!ws) return
    try {
      const got = await api.privacy(ws)
      setN(got)
      if (!notNeeded(got) && !(got.is_owner && later())) setOpen(true)
    } catch { /* an older brain: no notice to show */ }
  }, [ws])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const show = () => { void load().then(() => setOpen(true)) }
    window.addEventListener(OPEN_PRIVACY, show)
    return () => window.removeEventListener(OPEN_PRIVACY, show)
  }, [load])
  if (!open || !n || !ws) return null
  return <PrivacyNotice ws={ws} notice={n} onDone={(got) => { setN(got); setOpen(false) }} canClose={notNeeded(n)} />
}

function PrivacyNotice({ ws, notice, onDone, canClose }: {
  ws: string; notice: Notice; onDone: (n: Notice) => void; canClose: boolean
}) {
  const [contact, setContact] = useState(notice.contact ?? '')
  const [days, setDays] = useState<Retention>(notice.accepted_at ? notice.retention : { ...notice.recommended })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const owner = notice.is_owner
  const save = async () => {
    setBusy(true)
    setErr(null)
    try {
      onDone(owner ? await api.acceptPrivacy(ws, contact.trim(), days) : await api.ackPrivacy(ws))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const kept = (k: keyof Retention) => (days[k] ? `${days[k]} days` : 'until deleted')
  const abroad = [
    notice.cloud.claude && 'the text of each note goes to Anthropic (USA) to be filed on the map',
    notice.cloud.deepgram && 'voice recordings go to Deepgram (USA) to be turned into text',
    notice.cloud.sync === 'supabase' && "a copy is kept in the business's Supabase project",
  ].filter(Boolean) as string[]
  const field = 'rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-slate-100'

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="privacy-title" className="fixed inset-0 z-[60] grid place-items-center bg-black/70 p-4">
      <div className="nc-glass flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl">
        <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <ShieldCheck className="size-4 text-emerald-300" />
          <h2 id="privacy-title" className="flex-1 text-sm font-semibold text-slate-50">Privacy notice · {notice.business}</h2>
          {canClose && (
            <button type="button" aria-label="Close" onClick={() => onDone(notice)} className="grid size-7 place-items-center rounded-full text-slate-400 hover:bg-white/10"><X className="size-4" /></button>
          )}
        </header>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4 text-xs leading-relaxed text-slate-300">
          <p><b className="text-slate-100">Who is responsible.</b> {notice.business}{notice.owners.length ? ` (${notice.owners.join(', ')})` : ''}. Questions and requests about your personal information: {notice.contact || <i>the owner fills this in below</i>}.</p>
          <p><b className="text-slate-100">What is recorded.</b> Voice notes and their text; the notes, tasks and alerts made from them; the names of people mentioned; who made each change and when; the phones that joined. No location, contacts or ID numbers.</p>
          <p><b className="text-slate-100">Why.</b> To run the business's work: field notes filed on its map, tasks and alerts for the people who do them.</p>
          <p><b className="text-slate-100">Who sees it.</b> Each person sees only the branches their role allows. Owners decide the roles.</p>
          <p><b className="text-slate-100">Where it is kept.</b> On the business's own computer{abroad.length ? `; also: ${abroad.join('; ')}` : ', and nothing leaves it'}.</p>
          <p><b className="text-slate-100">How long.</b> Recordings {kept('audio_days')}, transcripts {kept('transcript_days')}, the activity log {kept('log_days')}. Notes on the map stay until someone deletes them.</p>
          <p><b className="text-slate-100">Your rights.</b> Ask what is held about you, have it corrected or deleted, or object, through the contact above. You may also complain to the Information Regulator (inforegulator.org.za).</p>
          <p><b className="text-slate-100">Please do not</b> dictate health, religion, union or other sensitive details about anyone.</p>
          {owner && (
            <section aria-label="Settings for this business" className="space-y-2 rounded-xl border border-white/10 p-3">
              <p className="text-slate-100">As an owner you are the responsible party: fill in a contact and choose how long things are kept. Older items are deleted every few hours once this is saved.</p>
              <label className="flex items-center gap-2">
                <span className="w-40 shrink-0">Contact</span>
                <input value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Name, phone or email" className={`${field} flex-1`} />
              </label>
              {PERIODS.map(([k, label]) => (
                <label key={k} className="flex items-center gap-2">
                  <span className="w-40 shrink-0">{label}</span>
                  <select value={days[k] ?? ''} onChange={(e) => setDays({ ...days, [k]: e.target.value ? Number(e.target.value) : null })} className={field}>
                    <option value="">Keep until deleted</option>
                    {CHOICES.map((d) => <option key={d} value={d}>{d} days{notice.recommended[k] === d ? ' (suggested)' : ''}</option>)}
                  </select>
                </label>
              ))}
            </section>
          )}
          {err && <p role="alert" className="text-rose-300">{err}</p>}
        </div>
        <footer className="flex justify-end gap-2 border-t border-white/10 px-4 py-3">
          {owner && !notice.accepted_at && (
            <button type="button" onClick={() => { try { localStorage.setItem(LATER, String(Date.now() + 86_400_000)) } catch { /* private window */ } onDone(notice) }}
              className="rounded-full px-4 py-1.5 text-xs text-slate-300 hover:bg-white/10">Not now</button>
          )}
          <button type="button" disabled={busy || (owner && !contact.trim())} onClick={() => void save()}
            className="flex items-center gap-1.5 rounded-full bg-emerald-500/90 px-4 py-1.5 text-xs font-semibold text-slate-950 disabled:opacity-40">
            {busy && <Loader2 className="size-3 animate-spin" />}{owner ? 'Save and accept' : 'I have read this'}
          </button>
        </footer>
      </div>
    </div>
  )
}
