// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Phone state: record into the outbox, upload the outbox with tus (resuming after drops), follow each note through
// the brain's live events until it is filed, and keep the farm's map for "record on this node".
import { Upload } from 'tus-js-client'
import { create } from 'zustand'
import type { MindMap } from '../../../desktop/src/lib/types'
import { deviceCopy, syncCopy } from './devicecopy'
import { isNative, Native, platform, type NativeItem } from './native'
import { outbox, DONE, WAITING, type ItemState, type OutboxItem } from './outbox'
import { isDeviceToken, loadPairing, needsRepair, savePairing, uuid7, type JoinLink, type Pairing } from './pairing'

export type Live = 'off' | 'connecting' | 'live' | 'reconnecting'
export type RecState = 'idle' | 'arming' | 'recording'
const RETRY = [2000, 5000, 15000, 30000, 60000, 120000]
const FOLLOW: ItemState[] = ['uploaded', 'transcribing', 'routing']
const MIMES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4', 'audio/webm']

interface PhoneState {
  pairing: Pairing | null
  farm: string | null
  items: OutboxItem[]
  native: NativeItem[]
  online: boolean
  reachable: boolean | null
  live: Live
  map: MindMap | null
  context: { id: string; title: string } | null
  rec: RecState
  recStartedAt: number
  level: number
  error: string | null
  /** A notecad://pair link that arrived: shown for the owner to confirm before the phone talks to that brain. */
  offer: Pairing | null
  offerPair(p: Pairing | null): void
  /** A notecad://join link (ADR 0014): what it offers is shown first; joining happens only when the person says so. */
  join: JoinLink | null
  joinPreview: JoinPreview | null
  offerJoin(j: JoinLink | null): Promise<void>
  acceptJoin(): Promise<string | null>
  /** This phone was removed from the business: hand in what it recorded before, then wipe everything. */
  revoked(): Promise<void>
  /** ADR 0014: who this phone acts as (GET /me), and the Inbox items it may decide or follows */
  me: Me | null
  inbox: InboxItem[]
  privacy: Privacy | null
  ackPrivacy(): Promise<void>
  /** POPIA s23: a copy of everything the business holds about this member. */
  myCopy(): Promise<Record<string, unknown> | null>
  decide(id: string, decision: 'approve' | 'reject', reason?: string): Promise<string | null>
  invite(name: string, role: 'employee' | 'manager'): Promise<{ link?: string; error?: string }>
  init(): Promise<void>
  pair(p: Pairing): Promise<string | null>
  unpair(): Promise<void>
  setContext(c: { id: string; title: string } | null): void
  startRecording(): Promise<void>
  stopRecording(): Promise<void>
  toggleRecording(): Promise<void>
  sendText(text: string): Promise<void>
  drain(): Promise<void>
  retry(id: string): Promise<void>
  discard(id: string): Promise<void>
  undo(id: string): Promise<void>
  refresh(): Promise<void>
}

export interface Me { member_id: string | null; name: string | null; level: number; role: string; scopes: string[];
  capabilities: Record<string, string> }
/** POPIA: what the business's privacy notice says, and whether this member has read it (GET .../privacy). */
export interface Privacy { business: string; owners: string[]; contact: string | null; retention_text: string; officer: string | null;
  cloud: { claude: boolean; deepgram: boolean; sync: string | null }; my_ack_at: string | null; is_owner: boolean }
export interface InboxItem { id: string; kind: string; question: string; event_text: string | null; author_member_id: string | null }

export interface JoinPreview { workspace: string; workspace_id: string; name: string; role: string; scope: string[]; expires_at: string }

/** The brain answered 410: this device (or its member) was revoked; the phone wipes its copy (ADR 0014). */
export class RevokedError extends Error {
  constructor() { super('This phone was removed from the business') }
}

let revoking = false

// ---------------------------------------------------------------- the brain over the farm network
function headers(p: Pairing): Record<string, string> {
  return p.token ? { Authorization: `Bearer ${p.token}` } : {}
}

async function call<T>(p: Pairing, path: string, init: RequestInit = {}): Promise<T> {
  const h = new Headers(init.headers)
  for (const [k, v] of Object.entries(headers(p))) h.set(k, v)
  if (init.body && !h.has('Content-Type')) h.set('Content-Type', 'application/json')
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), 10000)
  try {
    const r = await fetch(`${p.url}/api/v1${path}`, { ...init, headers: h, signal: ctl.signal })
    if (!r.ok) {
      let msg = `${r.status}`
      let body: { detail?: unknown } = {}
      try { body = await r.json() } catch { /* not JSON */ }
      if (r.status === 410 && (body.detail as { wipe?: boolean } | undefined)?.wipe) throw new RevokedError()
      msg = typeof body.detail === 'string' ? body.detail : msg
      throw new Error(r.status === 401 ? 'The phone token was not accepted: pair again' : String(msg))
    }
    return (await r.json()) as T
  } finally {
    clearTimeout(t)
  }
}

// ---------------------------------------------------------------- recording (web side: iOS and the Android app)
let stream: MediaStream | null = null
let mr: MediaRecorder | null = null
let chunks: Blob[] = []
let actx: AudioContext | null = null
let raf = 0
let es: EventSource | null = null
let lastEvent = 0
let draining = false
let pollTimer: ReturnType<typeof setInterval> | undefined
let started = false
let levelAt = 0
let progressAt = 0

function resetLive() {
  es?.close()
  es = null
  lastEvent = 0
}

async function reload(set: (s: Partial<PhoneState>) => void) {
  set({ items: await outbox.all(), native: await Native.listOutbox().catch(() => []) })
}

export const usePhone = create<PhoneState>((set, get) => ({
  pairing: loadPairing(),
  farm: null,
  items: [],
  native: [],
  online: navigator.onLine,
  reachable: null,
  live: 'off',
  map: null,
  context: null,
  offer: null,
  join: null,
  joinPreview: null,
  me: null,
  privacy: null,
  inbox: [],
  rec: 'idle',
  recStartedAt: 0,
  level: 0,
  error: needsRepair(loadPairing()) && isNative
    ? 'The farm network now uses a secure connection: pair this phone again (Pair a phone on the PC).' : null,

  async init() {
    if (started) return
    started = true
    await outbox.prune()
    await reload(set)
    window.addEventListener('online', () => { set({ online: true }); void get().drain(); void get().refresh() })
    window.addEventListener('offline', () => set({ online: false }))
    document.addEventListener('visibilitychange', () => { if (!document.hidden) { void reload(set); void get().drain() } })
    void Native.on('outboxChanged', () => { void reload(set) })
    void Native.on('launchAction', (d) => { if (d.action === 'record') void get().toggleRecording() })
    const was = get().pairing
    if (was && Native.vaulted) {
      if (was.token) await savePairing(was)  // stored before the vault: move the token into it
      else set({ pairing: { ...was, token: await Native.token().catch(() => '') } })
    }
    const action = await Native.consumeLaunchAction().catch(() => null)  // iOS Action Button / Siri opened the app
    if (get().pairing) {
      void get().refresh()
      void get().drain()
      if (action === 'record') void get().startRecording()
    }
    clearInterval(pollTimer)
    // cheap when idle: the decision uses the items already in memory, not a read of every recording
    pollTimer = setInterval(() => {
      const items = get().items
      if (items.some((i) => WAITING.includes(i.state) && (!i.nextTryAt || i.nextTryAt <= Date.now()))) void get().drain()
      if (get().live !== 'live' && items.some((i) => FOLLOW.includes(i.state))) void followByPolling(get, set)
    }, 5000)
  },

  async pair(p) {
    try {
      await Native.trust(p.url, p.pin)
      const w = await call<{ name: string }>(p, `/workspaces/${p.ws}`)
      resetLive()  // a different brain: its own stream, its own event ids
      await savePairing({ ...p, name: w.name })
      set({ pairing: { ...p, name: w.name }, offer: null, error: null })
      await outbox.unpark()  // notes parked on a refused token get another go
      await get().refresh()
      void get().drain()
      return null
    } catch (e) {
      return (e as Error).name === 'AbortError' ? `No answer from ${p.url}: is the brain started with -Lan, and is the phone on the same network?` : (e as Error).message
    }
  },

  async unpair() {
    resetLive()
    await savePairing(null)
    set({ pairing: null, farm: null, map: null, live: 'off', reachable: null })
  },

  setContext(c) { set({ context: c }) },

  offerPair(p) { set({ offer: p }) },

  async offerJoin(j) {
    set({ join: j, joinPreview: null, error: null })
    if (!j) return
    try {
      await Native.trust(j.url, j.pin)
      const r = await fetch(`${j.url}/api/v1/join/preview`, {  // the code in the body, never in a URL
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: j.code }) })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `${r.status}`)
      set({ joinPreview: (await r.json()) as JoinPreview })
    } catch (e) {
      set({ error: (e as Error).name === 'TypeError' ? `No answer from ${j.url}: is the phone on the farm's network?` : (e as Error).message })
    }
  },

  async acceptJoin() {
    const j = get().join
    if (!j) return null
    try {
      const r = await fetch(`${j.url}/api/v1/join`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: j.code, device_name: deviceName(), platform }),
      })
      const got = await r.json().catch(() => ({}))
      if (!r.ok) return got.detail ?? `The brain answered ${r.status}`
      resetLive()
      await deviceCopy.wipe()  // a new seat: nothing from before stays on this phone
      const p: Pairing = { url: j.url, token: got.token, ws: got.workspace_id, name: got.workspace, pin: j.pin,
        member: { id: got.member_id, name: got.name, role: got.role } }
      await savePairing(p)
      set({ pairing: p, join: null, joinPreview: null, offer: null, error: null })
      await outbox.unpark()
      await get().refresh()
      void get().drain()
      return null
    } catch (e) {
      return (e as Error).message
    }
  },

  async ackPrivacy() {
    const p = get().pairing
    if (!p) return
    try { set({ privacy: await call<Privacy>(p, `/workspaces/${p.ws}/privacy/ack`, { method: 'POST' }) }) } catch { return }
    // notes recorded before reading it were refused (POPIA s18): they go now
    await savePairing(p)  // the native outbox gets another go too
    await outbox.unpark()
    void get().drain()
  },

  async myCopy() {
    const p = get().pairing
    if (!p?.member) return null
    try { return await call<Record<string, unknown>>(p, `/workspaces/${p.ws}/subjects/${p.member.id}/export`) } catch { return null }
  },

  async decide(id, decision, reason) {
    const p = get().pairing
    if (!p) return 'Not connected'
    try {
      await call(p, `/inbox/${id}/resolve`, { method: 'POST', body: JSON.stringify({ decision, reason }) })
      await loadPeople(p, set)
      return null
    } catch (e) {
      return (e as Error).message
    }
  },

  async invite(name, role) {
    const p = get().pairing
    if (!p) return { error: 'Not connected' }
    try {
      const r = await call<{ links: string[] }>(p, `/workspaces/${p.ws}/invites`, { method: 'POST', body: JSON.stringify({ name, role }) })
      // the brain answered at the address this phone uses: that is where the new phone joins too
      return { link: r.links[0] }
    } catch (e) {
      return { error: (e as Error).message }
    }
  },

  async revoked() {
    const p = get().pairing
    if (!p || revoking) return
    revoking = true
    try {
      // what was recorded before the revoke is handed in once (held for an owner); the rest is refused and goes
      await get().drain()
      await deviceCopy.wipe()
      try { await call(p, '/device/wiped', { method: 'POST' }) } catch { /* it wipes all the same */ }
      for (const it of await outbox.all()) await outbox.remove(it.id)
      await Native.wipe().catch(() => undefined)
      resetLive()
      await savePairing(null)
      set({ pairing: null, farm: null, map: null, live: 'off', reachable: null, items: [],
        error: `This phone was removed from ${p.name ?? 'the business'}: its copy has been wiped.` })
    } finally {
      revoking = false
    }
  },

  async refresh() {
    const p = get().pairing
    if (!p) return
    try {
      if (isDeviceToken(p.token)) await syncCopy((path) => call(p, path))  // the member's copy, kept for no signal
      const map = await call<MindMap>(p, `/workspaces/${p.ws}/mindmap?tasks=true&notes=0`)
      set({ map, farm: map.workspace.name, reachable: true })
      void loadPeople(p, set)
      connectLive(p, get, set, map.cursor)
    } catch (e) {
      if (e instanceof RevokedError) void get().revoked()
      else set({ reachable: false })
    }
  },

  async startRecording() {
    if (get().rec !== 'idle') return
    set({ rec: 'arming', error: null })
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } })
    } catch (e) {
      set({ rec: 'idle', error: (e as Error).name === 'NotAllowedError' ? 'Allow the microphone for IBMM in the phone settings' : 'No microphone' })
      return
    }
    const mime = MIMES.find((m) => typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(m))
    mr = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 32000 } : undefined)
    chunks = []
    mr.ondataavailable = (ev) => { if (ev.data.size) chunks.push(ev.data) }
    mr.start(500)
    try {
      actx = new AudioContext()
      const an = actx.createAnalyser()
      an.fftSize = 512
      actx.createMediaStreamSource(stream).connect(an)
      const buf = new Uint8Array(new ArrayBuffer(an.fftSize))
      const tick = () => {
        an.getByteTimeDomainData(buf)
        let s = 0
        for (const v of buf) s += Math.abs(v - 128)
        const now = performance.now()
        if (now - levelAt > 66) { levelAt = now; set({ level: Math.min(1, (s / buf.length / 128) * 6) }) }
        raf = requestAnimationFrame(tick)
      }
      tick()
    } catch { /* level meter is optional */ }
    if ('vibrate' in navigator) navigator.vibrate?.(30)
    set({ rec: 'recording', recStartedAt: Date.now() })
  },

  async stopRecording() {
    if (get().rec !== 'recording' || !mr) {
      set({ rec: 'idle' })
      return
    }
    const r = mr
    const done = new Promise<void>((res) => { r.onstop = () => res() })
    r.stop()
    await done
    cancelAnimationFrame(raf)
    for (const t of stream?.getTracks() ?? []) t.stop()
    actx?.close().catch(() => undefined)
    const type = (r.mimeType || 'audio/webm').split(';')[0]
    const blob = new Blob(chunks, { type })
    const secs = (Date.now() - get().recStartedAt) / 1000
    stream = null; mr = null; actx = null; chunks = []
    set({ rec: 'idle', level: 0 })
    if (secs < 0.6 || blob.size < 1000) {
      set({ error: 'Too short: hold a little longer' })
      return
    }
    if ('vibrate' in navigator) navigator.vibrate?.([20, 40, 20])
    const ctx = get().context
    await outbox.put({
      id: uuid7(), kind: 'audio', blob, mime: type, size: blob.size, createdAt: Date.now(),
      recordedAt: new Date(get().recStartedAt).toISOString(), contextNodeId: ctx?.id ?? null, contextTitle: ctx?.title ?? null,
      source: 'phone', state: 'saved', progress: 0, attempts: 0,
    })
    await reload(set)
    void get().drain()
  },

  async toggleRecording() {
    const s = get().rec
    if (s === 'idle') await get().startRecording()
    else if (s === 'recording') await get().stopRecording()
  },

  async sendText(text) {
    const t = text.trim()
    if (!t) return
    const ctx = get().context
    await outbox.put({
      id: uuid7(), kind: 'text', text: t, size: t.length, createdAt: Date.now(), recordedAt: new Date().toISOString(),
      contextNodeId: ctx?.id ?? null, contextTitle: ctx?.title ?? null, source: 'phone', state: 'saved', progress: 0, attempts: 0,
    })
    await reload(set)
    void get().drain()
  },

  /** Send whatever waits in the outbox, oldest first, one at a time. */
  async drain() {
    const p = get().pairing
    if (!p || draining || !navigator.onLine) return
    draining = true
    try {
      const waiting = (await outbox.all()).filter((i) => WAITING.includes(i.state)
        && (!i.nextTryAt || i.nextTryAt <= Date.now())).reverse()
      for (const it of waiting) {
        const ok = await send(p, it, set)
        await reload(set)
        if (!ok) break  // the brain is not reachable: keep the rest for later, in order
      }
      if (waiting.length) void Native.uploadNow()
    } finally {
      draining = false
    }
  },

  async retry(id) {
    await outbox.patch(id, { state: 'saved', nextTryAt: 0, error: undefined })
    await reload(set)
    void get().drain()
  },

  async discard(id) {
    await outbox.remove(id)
    await Native.forget(id).catch(() => undefined)
    await reload(set)
  },

  async undo(id) {
    const p = get().pairing
    if (!p) return
    try {
      await call(p, `/captures/${id}/undo`, { method: 'POST' })
      await outbox.patch(id, { state: 'undone' })
    } catch (e) {
      set({ error: (e as Error).message })
    }
    await reload(set)
  },
}))

async function loadPeople(p: Pairing, set: (s: Partial<PhoneState>) => void) {
  try {
    const me = await call<Me>(p, `/workspaces/${p.ws}/me`)
    set({ me, inbox: await call<InboxItem[]>(p, `/workspaces/${p.ws}/inbox`) })
    set({ privacy: await call<Privacy>(p, `/workspaces/${p.ws}/privacy`) })
  } catch { /* an older brain: no roles, no notice */ }
}

function deviceName(): string {
  return platform === 'android' ? 'Android phone' : platform === 'ios' ? 'iPhone' : 'Browser'
}

async function send(p: Pairing, it: OutboxItem, set: (s: Partial<PhoneState>) => void): Promise<boolean> {
  const fail = async (err: string, retryable = true) => {
    const attempts = it.attempts + 1
    await outbox.patch(it.id, {
      state: 'failed', error: err, attempts,
      nextTryAt: retryable ? Date.now() + RETRY[Math.min(attempts - 1, RETRY.length - 1)] : Number.MAX_SAFE_INTEGER,
    })
    set({ reachable: !retryable })
    return false
  }
  if (it.kind === 'text') {
    await outbox.patch(it.id, { state: 'uploading' })
    try {
      await call(p, `/workspaces/${p.ws}/capture`, {
        method: 'POST',
        body: JSON.stringify({ text: it.text, capture_id: it.id, context_node_id: it.contextNodeId, source: it.source,
          recorded_at: it.recordedAt, wait: false }),
      })
      await outbox.patch(it.id, { state: 'uploaded', progress: 1, error: undefined })
      set({ reachable: true })
      return true
    } catch (e) {
      if (e instanceof RevokedError) {  // recorded after the phone was removed: the brain will not take it
        await outbox.patch(it.id, { state: 'failed', error: e.message, nextTryAt: Number.MAX_SAFE_INTEGER })
        if (!revoking) void usePhone.getState().revoked()
        return true  // go on with the next one
      }
      return fail((e as Error).message, !(e as Error).message.includes('token'))
    }
  }
  if (!it.blob) return fail('The recording is missing on this phone', false)
  await outbox.patch(it.id, { state: 'uploading', error: undefined })
  return new Promise<boolean>((resolve) => {
    const up = new Upload(it.blob!, {
      endpoint: `${p.url}/api/v1/workspaces/${p.ws}/uploads`,
      uploadUrl: it.uploadUrl ?? null,
      headers: headers(p),
      chunkSize: 256 * 1024,
      retryDelays: [0, 1000, 3000],
      storeFingerprintForResuming: false,
      metadata: {
        capture_id: it.id, filetype: it.mime || 'audio/webm', filename: `${it.id}.${(it.mime || '').includes('mp4') ? 'm4a' : 'webm'}`,
        recorded_at: it.recordedAt, source: it.source, ...(it.contextNodeId ? { context_node_id: it.contextNodeId } : {}),
      },
      onUploadUrlAvailable: () => { void outbox.patch(it.id, { uploadUrl: up.url ?? undefined }) },
      onProgress: (sent, total) => {  // the screen in memory every chunk, the outbox at most twice a second
        const progress = total ? sent / total : 0
        set({ items: usePhone.getState().items.map((x) => (x.id === it.id ? { ...x, progress } : x)) })
        if (Date.now() - progressAt > 500) { progressAt = Date.now(); void outbox.patch(it.id, { progress }) }
      },
      onSuccess: async () => {
        await outbox.patch(it.id, { state: 'uploaded', progress: 1, error: undefined, attempts: 0 })
        set({ reachable: true })
        resolve(true)
      },
      onError: async (err) => {
        const status = (err as { originalResponse?: { getStatus(): number } }).originalResponse?.getStatus?.()
        if (status === 404 || status === 410) await outbox.patch(it.id, { uploadUrl: undefined })  // start that one again
        resolve(await fail(status === 401 ? 'The phone token was not accepted: pair again' : `Upload paused: ${status ? `brain answered ${status}` : 'no connection'}`,
          status !== 401 && status !== 413))
      },
    })
    up.start()
  })
}

// ---------------------------------------------------------------- following notes to "filed"
const STATE_OF: Record<string, ItemState> = { 'stt.transcribing': 'transcribing', 'stt.completed': 'routing', 'router.resolving': 'routing' }

let opening = false

/** EventSource cannot send a header, so the URL carries a 10-minute ticket instead of the token (a URL ends up in
 * logs). A closed stream asks for a new ticket on the next refresh. */
function connectLive(p: Pairing, get: () => PhoneState, set: (s: Partial<PhoneState>) => void, cursor: number) {
  if (es || opening) return
  opening = true
  set({ live: 'connecting' })
  const ticket = p.token
    ? call<{ ticket: string | null }>(p, '/tickets', { method: 'POST' }).then((t) => t.ticket, () => null)
    : Promise.resolve(null)
  void ticket.then((t) => {
    opening = false
    if (es || (p.token && !t)) { if (!es) set({ live: 'off' }); return }
    openLive(p, get, set, cursor, t)
  })
}

function openLive(p: Pairing, get: () => PhoneState, set: (s: Partial<PhoneState>) => void, cursor: number, ticket: string | null) {
  const u = new URL(`${p.url}/api/v1/workspaces/${p.ws}/events/stream`)
  u.searchParams.set('last_event_id', String(lastEvent || cursor))
  if (ticket) u.searchParams.set('ticket', ticket)
  es = new EventSource(u.toString())
  es.onopen = () => set({ live: 'live', reachable: true })
  const mine = es
  es.onerror = () => {
    if (es !== mine) return
    if (mine.readyState === EventSource.CLOSED) {  // given up (an HTTP error): the next refresh opens it again
      es = null
      set({ live: 'off' })
    } else set({ live: 'reconnecting' })
  }
  const on = async (type: string, raw: MessageEvent) => {
    const e = JSON.parse(raw.data)
    lastEvent = Math.max(lastEvent, e.id)
    const id = e.capture_id as string | undefined
    if (type.startsWith('inbox.')) void loadPeople(p, set)
    if (type === 'sync.refused') set({ error: `Not taken by the farm: ${e.reason ?? 'not allowed'}` })
    if (!id || !(await outbox.get(id))) {
      if (type === 'action.applied' || type === 'sync.applied') void get().refresh()
      return
    }
    if (STATE_OF[type]) await outbox.patch(id, { state: STATE_OF[type], ...(e.transcript ? { transcript: e.transcript } : {}) })
    if (type === 'action.applied') {
      const it = await outbox.get(id)
      const where = (e.nodes as { map_path: string }[] | undefined)?.map((n) => n.map_path.split(' > ').slice(-2).join(' › ')) ?? []
      await outbox.patch(id, { summary: [...new Set([...(it?.summary ? it.summary.split(' · ') : []), ...where])].join(' · ') })
    }
    if (type === 'inbox.created') await outbox.patch(id, { summary: e.kind === 'approval' ? 'Part of it waits for a manager to approve' : 'Waiting in the Inbox' })
    if (type === 'capture.completed') await outbox.patch(id, { state: e.state as ItemState, blob: undefined })
    if (type === 'capture.failed') await outbox.patch(id, { state: 'failed', error: e.error, nextTryAt: Number.MAX_SAFE_INTEGER })
    if (type === 'action.undone') await outbox.patch(id, { state: 'undone' })
    if (type === 'capture.answer') await outbox.patch(id, { summary: e.text as string })
    if (type === 'action.refused') await outbox.patch(id, { summary: `Not done: ${((e.refused as { reason: string }[]) ?? []).map((r) => r.reason).join('; ')}` })
    set({ items: await outbox.all() })
  }
  for (const t of ['capture.queued', 'stt.transcribing', 'stt.completed', 'router.resolving', 'action.applied', 'inbox.created',
    'capture.completed', 'capture.failed', 'action.undone', 'sync.applied', 'capture.answer', 'action.refused', 'sync.refused',
    'inbox.resolved']) {
    es.addEventListener(t, (ev) => { void on(t, ev as MessageEvent) })
  }
}

/** When the live stream is down, ask about notes that were uploaded but not yet filed. */
async function followByPolling(get: () => PhoneState, set: (s: Partial<PhoneState>) => void) {
  const p = get().pairing
  if (!p || get().live === 'live' || !navigator.onLine) return
  const pending = get().items.filter((i) => FOLLOW.includes(i.state))
  for (const it of pending) {
    try {
      const s = await call<{ state: string; text: string | null; error: string | null }>(p, `/captures/${it.id}`)
      const st = (['queued'].includes(s.state) ? 'uploaded' : s.state) as ItemState
      await outbox.patch(it.id, { state: st, transcript: s.text ?? it.transcript, ...(DONE.includes(st) ? { blob: undefined } : {}) })
    } catch { /* try again in 5 s */ }
  }
  if (pending.length) set({ items: await outbox.all() })
}
