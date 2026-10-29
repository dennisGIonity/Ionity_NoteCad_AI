// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// People & seats (ADR 0014, decision 27). An owner adds seats, invites (a QR of a one-time join link), changes roles
// and branches, and removes people and devices. A manager invites employees into free seats, inside their branches,
// and sees their team. The brain checks every one of these again; this panel only offers what GET /me allows.
import { Copy, Download, Eraser, Loader2, ShieldCheck, Smartphone, Trash2, UserPlus, Users, X } from 'lucide-react'
import QRCode from 'qrcode'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { OPEN_PRIVACY } from './PrivacyNotice'
import { can, useApp } from '../lib/store'
import type { Device, Invite, Member, Seat } from '../lib/types'
import { ago, cls } from '../lib/ui'

const ROLE = ['', 'Owner', 'Manager', 'Employee']

/** Saves what the brain sent as a file on this computer (the person's own copy). */
function download(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function PeoplePanel({ onClose }: { onClose: () => void }) {
  const ws = useApp((s) => s.ws)
  const me = useApp((s) => s.me)
  const map = useApp((s) => s.map)
  const owner = can(me, 'manage_seats') === 'allow'
  const [members, setMembers] = useState<Member[]>([])
  const [seats, setSeats] = useState<Seat[]>([])
  const [invites, setInvites] = useState<Invite[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [role, setRole] = useState<'employee' | 'manager'>('employee')
  const [scope, setScope] = useState('')
  const [made, setMade] = useState<{ link: string; svg: string | null; name: string } | null>(null)

  const load = useCallback(async () => {
    try {
      const [m, s, i, d] = await Promise.all([api.members(ws), api.seats(ws), api.invites(ws), api.devices(ws)])
      setMembers(m)
      setSeats(s)
      setInvites(i)
      setDevices(d)
    } catch (e) {
      setErr((e as Error).message)
    }
  }, [ws])
  useEffect(() => { void load() }, [load])

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); onClose() } }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [onClose])

  const run = async (key: string, f: () => Promise<unknown>) => {
    setBusy(key)
    setErr(null)
    try { await f(); await load() } catch (e) { setErr((e as Error).message) } finally { setBusy(null) }
  }

  const invite = () => run('invite', async () => {
    const got = await api.invite(ws, { name: name.trim(), role, scope_node_ids: scope ? [scope] : [] })
    const link = got.links[0] ?? ''
    const svg = link ? await QRCode.toString(link, { type: 'svg', margin: 1, color: { dark: '#020617', light: '#ffffff' } }).catch(() => null) : null
    setMade({ link, svg, name: name.trim() })
    setName('')
  })

  const areas = (map?.nodes ?? []).filter((n) => (n.type === 'category' || n.type === 'entity') && !n.virtual && !n.stub && (n.depth ?? 0) <= 3)
  const free = seats.filter((s) => s.status === 'available')
  const team = owner ? members : members.filter((m) => m.level === 3)
  const field = 'rounded-lg border border-white/10 bg-white/5 px-2 py-1.5 text-xs text-slate-100'

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="people-title" className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4">
      <div className="nc-glass flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl">
        <header className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <Users className="size-4 text-sky-300" />
          <h2 id="people-title" className="flex-1 text-sm font-semibold text-slate-50">People & seats</h2>
          <button type="button" onClick={() => window.dispatchEvent(new Event(OPEN_PRIVACY))}
            className="flex items-center gap-1 rounded-full px-2 py-1 text-xs text-slate-300 hover:bg-white/10">
            <ShieldCheck className="size-3.5" />Privacy notice
          </button>
          <span className="text-xs text-slate-400">{me?.name} · {ROLE[me?.level ?? 1]}</span>
          <button type="button" aria-label="Close" onClick={onClose} className="grid size-7 place-items-center rounded-full text-slate-400 hover:bg-white/10"><X className="size-4" /></button>
        </header>
        <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 md:grid-cols-2">
          <section aria-labelledby="invite-h" className="space-y-2">
            <h3 id="invite-h" className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400"><UserPlus className="size-3.5" />Invite someone</h3>
            <p className="text-xs text-slate-400">{free.length} free seat{free.length === 1 ? '' : 's'}{owner ? '' : ' for employees'}. The code works once, for 72 hours.</p>
            <input aria-label="Their name" placeholder="Their name" value={name} onChange={(e) => setName(e.target.value)} className={cls(field, 'w-full')} />
            <div className="flex gap-2">
              {owner && (
                <select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as 'employee' | 'manager')} className={field}>
                  <option value="employee">Employee</option><option value="manager">Manager</option>
                </select>
              )}
              <select aria-label="Branch" value={scope} onChange={(e) => setScope(e.target.value)} className={cls(field, 'min-w-0 flex-1')}>
                <option value="">{owner ? 'The whole farm' : 'Choose a branch you manage'}</option>
                {areas.map((n) => <option key={n.id} value={n.id}>{n.path ?? n.title}</option>)}
              </select>
            </div>
            <button type="button" disabled={!name.trim() || busy === 'invite'} onClick={() => void invite()}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-sky-500 px-3 py-2 text-sm font-medium text-white disabled:opacity-40">
              {busy === 'invite' && <Loader2 className="size-4 animate-spin" />}Make the invite
            </button>
            {made && (
              <div data-invite-link className="rounded-xl border border-sky-300/20 bg-sky-400/5 p-3 text-center">
                <p className="text-xs text-slate-300">{made.name} scans this with their phone (shown once):</p>
                {made.svg && <img className="mx-auto mt-2 w-44 rounded-lg bg-white p-2" alt="Invite QR code" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(made.svg)}`} />}
                <button type="button" onClick={() => void navigator.clipboard?.writeText(made.link)}
                  className="mt-2 inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-1 text-xs text-slate-100"><Copy className="size-3" />Copy the link</button>
              </div>
            )}
            {owner && (
              <div className="flex flex-wrap items-center gap-2 pt-2 text-xs text-slate-300">
                <span>Add a seat:</span>
                {(['employee', 'manager'] as const).map((r) => (
                  <button key={r} type="button" disabled={busy === `seat-${r}`} onClick={() => void run(`seat-${r}`, () => api.addSeats(ws, r, 1))}
                    className="rounded-full bg-white/10 px-2.5 py-1 hover:bg-white/20">+ {r}</button>
                ))}
                <span className="text-slate-500">(no billing yet: seats are added by hand)</span>
              </div>
            )}
            {invites.filter((i) => !i.used_at && !i.revoked_at).length > 0 && (
              <ul className="space-y-1 pt-2">
                {invites.filter((i) => !i.used_at && !i.revoked_at).map((i) => (
                  <li key={i.id} className="flex items-center gap-2 rounded-lg bg-white/5 px-2 py-1 text-xs text-slate-300">
                    <span className="flex-1 truncate">{i.profile.name} · {i.profile.role} · until {i.expires_at.slice(0, 16).replace('T', ' ')}</span>
                    <button type="button" aria-label={`Withdraw the invite for ${i.profile.name}`} onClick={() => void run(i.id, () => api.revokeInvite(i.id))}
                      className="rounded p-1 text-slate-400 hover:bg-white/10"><Trash2 className="size-3.5" /></button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="team-h" className="space-y-2">
            <h3 id="team-h" className="text-xs font-semibold uppercase tracking-wide text-slate-400">{owner ? 'Everyone' : 'Your team'}</h3>
            <ul className="space-y-1.5">
              {team.filter((m) => m.status === 'active').map((m) => (
                <li key={m.id} data-member={m.display_name} className="rounded-xl bg-white/5 px-3 py-2 text-xs text-slate-200">
                  <div className="flex items-center gap-2">
                    <span className="flex-1 truncate text-sm text-slate-100">{m.display_name}</span>
                    {owner && m.id !== me?.member_id ? (
                      <select aria-label={`Role of ${m.display_name}`} value={m.role} onChange={(e) => void run(m.id, () => api.setRole(m.id, { role: e.target.value }))} className={field}>
                        <option value="owner">Owner</option><option value="manager">Manager</option><option value="employee">Employee</option>
                      </select>
                    ) : <span className="text-slate-400">{ROLE[m.level]}</span>}
                    {owner && m.id !== me?.member_id && (
                      <button type="button" aria-label={`Remove ${m.display_name}`} onClick={() => {
                        if (window.confirm(`Remove ${m.display_name}? Their phones stop at once and wipe their copy; the seat is free again.`)) void run(m.id, () => api.revokeMember(m.id))
                      }} className="rounded p-1 text-slate-400 hover:bg-white/10"><Trash2 className="size-3.5" /></button>
                    )}
                    {(owner || m.id === me?.member_id) && (
                      <button type="button" aria-label={`Copy of ${m.display_name}'s information`} title="A copy of everything about them (POPIA s23)"
                        onClick={() => void run(`x${m.id}`, async () => download(`${m.display_name}.json`, await api.subjectExport(ws, m.id)))}
                        className="rounded p-1 text-slate-400 hover:bg-white/10"><Download className="size-3.5" /></button>
                    )}
                    {owner && m.id !== me?.member_id && (
                      <button type="button" aria-label={`Erase ${m.display_name}`} title="Erase this person (POPIA s24)" onClick={() => {
                        if (window.prompt(`Erase ${m.display_name}? Their recordings go, their name becomes [removed] everywhere, their phones are wiped. The activity log keeps "Removed member". Type ERASE to go ahead.`) === 'ERASE') void run(`e${m.id}`, () => api.subjectErase(ws, m.id))
                      }} className="rounded p-1 text-rose-300 hover:bg-white/10"><Eraser className="size-3.5" /></button>
                    )}
                  </div>
                  {devices.filter((d) => d.member_id === m.id).map((d) => (
                    <div key={d.id} className="mt-1 flex items-center gap-1.5 pl-1 text-[11px] text-slate-400">
                      <Smartphone className="size-3" />
                      <span className="flex-1 truncate">{d.name}{d.revoked_at ? (d.wipe_acked_at ? ' · removed, wiped' : ' · removed, wipes on next contact') : d.last_seen_at ? ` · seen ${ago(d.last_seen_at)}` : ''}</span>
                      {!d.revoked_at && (owner || d.member_id === me?.member_id) && (
                        <button type="button" onClick={() => void run(d.id, () => api.revokeDevice(d.id))} className="rounded px-1.5 py-0.5 hover:bg-white/10">Remove</button>
                      )}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
            {owner && <p className="text-[11px] text-slate-500">{seats.length} seat{seats.length === 1 ? '' : 's'}: {seats.filter((s) => s.status === 'assigned').length} taken, {free.length} free. Owners need no seat.</p>}
          </section>
        </div>
        {err && <p role="alert" className="border-t border-white/10 px-4 py-2 text-xs text-rose-300">{err}</p>}
      </div>
    </div>
  )
}
