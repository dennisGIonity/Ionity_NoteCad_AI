// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Corner status: local store health, live stream, multi-worker sync (Phase 5) and "Pair a phone".
import { ArrowDownUp, Database, Inbox, Loader2, RefreshCw, Smartphone, Users } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { api, config } from '../lib/api'
import { can, useApp } from '../lib/store'
import { cls, fmtBytes } from '../lib/ui'

const PairPhone = lazy(() => import('./PairPhone').then((m) => ({ default: m.PairPhone })))  // with its QR library
const PeoplePanel = lazy(() => import('./PeoplePanel').then((m) => ({ default: m.PeoplePanel })))
const InboxPanel = lazy(() => import('./InboxPanel').then((m) => ({ default: m.InboxPanel })))

const ago = (iso: string | null | undefined) => {
  if (!iso) return 'never'
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000))
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`
}

export function SyncIndicator() {
  const { sync, syncError, live, lastEventId, refreshSync } = useApp()
  const [open, setOpen] = useState(false)
  const [pairing, setPairing] = useState(false)
  const [panel, setPanel] = useState<'people' | 'inbox' | null>(null)
  const me = useApp((s) => s.me)
  const inbox = useApp((s) => s.inbox)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const peer = sync?.sync
  const pending = peer?.target ? peer.pending_changes ?? 0 : sync ? sync.pending.sync_events : 0
  const syncNow = async () => {
    setSyncing(true)
    setSyncMsg(null)
    try {
      const r = await api.syncNow()
      setSyncMsg(r.ok ? `Sent ${r.pushed ?? 0}, received ${r.pulled ?? 0}` : r.error ?? 'Sync failed')
    } catch (e) {
      setSyncMsg((e as Error).message)
    }
    setSyncing(false)
    void refreshSync()
  }
  const inFlight = sync ? sync.pending.captures_in_flight + sync.pending.jobs_queued : 0
  const tone = syncError || (sync && !sync.ok) ? 'bad' : peer?.last_error ? 'warn' : live !== 'live' || inFlight || sync?.pending.jobs_failed ? 'warn' : 'good'
  const dot = { good: 'bg-emerald-400', warn: 'bg-amber-400', bad: 'bg-rose-500' }[tone]
  const label = syncError ? 'Brain offline' : sync ? `${sync.db === 'sqlite' ? 'SQLite' : 'Postgres'} ${sync.ok ? 'ok' : 'check'}` : 'Checking…'

  return (
    <div className="pointer-events-auto absolute bottom-3 right-3 z-50 flex flex-col items-end gap-2 text-[11px]">
      {open && (
        <div className="nc-glass w-64 rounded-2xl p-3 text-slate-300 shadow-xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold text-slate-100">Local store</span>
            <button type="button" aria-label="Check now" onClick={() => void refreshSync()} className="rounded p-1 hover:bg-white/10"><RefreshCw className="size-3.5" /></button>
          </div>
          {syncError ? <p className="text-rose-300">{syncError} at {config.brain}</p> : sync && (
            <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
              <dt>Database</dt><dd className="text-right text-slate-100">{sync.db} · {sync.journal_mode ?? '–'}</dd>
              <dt>Integrity</dt><dd className={cls('text-right', sync.ok ? 'text-emerald-300' : 'text-rose-300')}>{sync.integrity}</dd>
              <dt>Size / WAL</dt><dd className="text-right text-slate-100">{fmtBytes(sync.size_bytes)} / {fmtBytes(sync.wal_bytes)}</dd>
              <dt>Waiting to sync</dt><dd className="text-right text-slate-100">{sync.pending.sync_events}</dd>
              <dt>Notes in flight</dt><dd className="text-right text-slate-100">{inFlight}</dd>
              <dt>Failed jobs</dt><dd className={cls('text-right', sync.pending.jobs_failed ? 'text-amber-300' : 'text-slate-100')}>{sync.pending.jobs_failed}</dd>
              <dt>Push queue</dt><dd className="text-right text-slate-100">{sync.pending.notifications_unsent}</dd>
              <dt>Inbox</dt><dd className="text-right text-slate-100">{sync.pending.inbox_open}</dd>
              <dt>Live stream</dt><dd className="text-right text-slate-100">{live} · #{lastEventId}</dd>
            </dl>
          )}
          {sync && (
            <div className="mt-3 border-t border-white/10 pt-2">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-semibold text-slate-100">Sync</span>
                {peer?.target && (
                  <button type="button" onClick={() => void syncNow()} disabled={syncing}
                    className="flex items-center gap-1 rounded-full bg-white/10 px-2 py-0.5 text-slate-100 hover:bg-white/15 disabled:opacity-50">
                    {syncing ? <Loader2 className="size-3 animate-spin" /> : <ArrowDownUp className="size-3" />}Sync now
                  </button>
                )}
              </div>
              {peer?.target ? (
                <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1">
                  <dt>With</dt><dd className="max-w-36 truncate text-right text-slate-100" title={peer.target}>{peer.peer ?? peer.target}</dd>
                  <dt>This worker</dt><dd className="max-w-36 truncate text-right text-slate-100">{peer.worker_id}</dd>
                  <dt>Last sync</dt><dd className="text-right text-slate-100">{ago(peer.last_sync_at)}</dd>
                  <dt>Changes to send</dt><dd className="text-right text-slate-100">{peer.pending_changes ?? 0}</dd>
                  <dt>Sent / received</dt><dd className="text-right text-slate-100">{peer.pushed} / {peer.pulled}</dd>
                </dl>
              ) : (
                <p className="text-slate-500">Only on this PC. Set <code>NC_BRAIN_SYNC_TARGET</code> in the vault to sync with the Edge AI Node or Supabase.</p>
              )}
              {peer?.last_error && <p className="mt-1 text-amber-300">{peer.last_error}</p>}
              {syncMsg && <p className="mt-1 text-slate-400">{syncMsg}</p>}
            </div>
          )}
          {can(me, 'manage_workspace') === 'allow' && !me?.device_id && (
            <button type="button" onClick={() => setPairing(true)}
              className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-sky-500/20 px-3 py-1.5 text-sky-100 hover:bg-sky-500/30">
              <Smartphone className="size-3.5" />Pair a phone
            </button>
          )}
          {can(me, 'invite') === 'allow' && (
            <button type="button" onClick={() => { setPanel('people'); setOpen(false) }}
              className="mt-2 flex w-full items-center justify-center gap-2 rounded-xl bg-white/10 px-3 py-1.5 text-slate-100 hover:bg-white/15">
              <Users className="size-3.5" />People & seats
            </button>
          )}
        </div>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        title="Local store and sync status"
        className="nc-glass flex items-center gap-2 rounded-full px-2.5 py-1 text-slate-300 opacity-70 transition hover:opacity-100"
      >
        <span className={cls('size-1.5 rounded-full', dot, tone !== 'good' && 'animate-pulse')} />
        <Database className="size-3" />
        <span>{label}</span>
        {sync && <span className="text-slate-500">· {pending} {peer?.target ? 'to sync' : 'pending'}</span>}
      </button>
      {inbox.length > 0 && (
        <button type="button" data-inbox-count={inbox.length} onClick={() => setPanel('inbox')} title="Inbox: notes to place, proposals to decide"
          className="nc-glass ml-1 flex items-center gap-1 rounded-full px-2.5 py-1 text-amber-200 hover:text-amber-100">
          <Inbox className="size-3" />{inbox.length}
        </button>
      )}
      {pairing && <Suspense fallback={null}><PairPhone onClose={() => setPairing(false)} /></Suspense>}
      {panel === 'people' && <Suspense fallback={null}><PeoplePanel onClose={() => setPanel(null)} /></Suspense>}
      {panel === 'inbox' && <Suspense fallback={null}><InboxPanel onClose={() => setPanel(null)} /></Suspense>}
    </div>
  )
}
