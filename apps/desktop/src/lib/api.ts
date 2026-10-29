// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Brain (:8788) and companion (:8787) clients. Both default to this machine; override with VITE_ env vars,
// ?brain= / ?companion= / ?token= in the URL, or the settings popover (kept in this browser only).
import type { HistoryItem, MindMap, NodeDetail, Pairing, SyncRunResult, SyncStatus, Workspace } from './types'

const store = {
  get(k: string): string | null {
    try { return localStorage.getItem(`notecad.${k}`) } catch { return null }
  },
  set(k: string, v: string | null) {
    try { v == null ? localStorage.removeItem(`notecad.${k}`) : localStorage.setItem(`notecad.${k}`, v) } catch { /* private window */ }
  },
}

const q = new URLSearchParams(location.search)
export const config = {
  brain: (q.get('brain') || store.get('brain') || import.meta.env.VITE_BRAIN_URL || (location.port === '8788' ? location.origin : 'http://127.0.0.1:8788')).replace(/\/$/, ''),
  companion: (q.get('companion') || store.get('companion') || import.meta.env.VITE_COMPANION_URL || 'http://127.0.0.1:8787').replace(/\/$/, ''),
  token: q.get('token') || store.get('token') || import.meta.env.VITE_API_TOKEN || '',
  workspace: q.get('ws') || store.get('ws') || import.meta.env.VITE_WORKSPACE || '',
  save(patch: Partial<Record<'brain' | 'companion' | 'token' | 'workspace', string>>) {
    for (const [k, v] of Object.entries(patch)) {
      ;(config as unknown as Record<string, string>)[k] = v ?? ''
      store.set(k === 'workspace' ? 'ws' : k, v || null)
    }
  },
}

/** notecad://join?u=<brain>&c=<one-time code>&w=<farm> (ADR 0014): a seat offered to this computer. */
export function parseJoinLink(link: string): { url: string; code: string; ws: string } | null {
  const s = link.trim()
  if (!/^notecad:\/\/join\?/i.test(s)) return null
  const p = new URLSearchParams(s.slice(s.indexOf('?') + 1))
  const url = (p.get('u') || '').replace(/\/$/, '')
  const code = p.get('c') || ''
  if (!/^https?:\/\//.test(url) || !p.get('w') || code.length < 6) return null
  return { url, code, ws: p.get('w') || '' }
}

/** Join with an invite (?join=<link>): the brain says what it is, the person confirms, then this computer keeps its
 *  own device token (a shared office PC, run with NC_BRAIN_TRUST_LOOPBACK=0). The code works once. */
export async function joinFromLink(link: string, confirm: (text: string) => boolean = window.confirm): Promise<string | null> {
  const j = parseJoinLink(link)
  if (!j) return 'That is not a NoteCad invite link'
  try {
    const pv = await fetch(`${j.url}/api/v1/join?c=${encodeURIComponent(j.code)}`)
    const info = await pv.json()
    if (!pv.ok) return info.detail ?? `The brain answered ${pv.status}`
    const where = info.scope?.length ? ` (${info.scope.join(', ')})` : ''
    if (!confirm(`Join ${info.workspace} as ${info.role}${where}, as ${info.name}?`)) return 'Not joined'
    const r = await fetch(`${j.url}/api/v1/join`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: j.code, device_name: 'Desktop', platform: 'desktop' }) })
    const got = await r.json()
    if (!r.ok) return got.detail ?? `The brain answered ${r.status}`
    config.save({ brain: j.url, token: got.token, workspace: got.workspace_id })
    return null
  } catch {
    return `No answer from ${j.url}`
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function call<T>(base: string, path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (config.token) headers.set('Authorization', `Bearer ${config.token}`)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let res: Response
  try {
    res = await fetch(`${base}${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, base === config.brain ? 'Brain not reachable' : 'Companion not reachable')
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg)
  }
  return (await res.json()) as T
}

const brain = <T,>(path: string, init?: RequestInit) => call<T>(config.brain, `/api/v1${path}`, init)
const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const api = {
  workspaces: () => brain<Workspace[]>('/workspaces'),
  mindmap: (ws: string) => brain<MindMap>(`/workspaces/${ws}/mindmap?notes=3`),
  node: (id: string) => brain<NodeDetail>(`/nodes/${id}`),
  history: (id: string) => brain<HistoryItem[]>(`/nodes/${id}/history?limit=60`),
  sync: (ws: string) => brain<SyncStatus>(`/workspaces/${ws}/sync`),
  syncNow: () => brain<SyncRunResult>('/sync/now', { method: 'POST' }),
  pairing: (ws: string | null) => brain<Pairing>(`/pairing${ws ? `?ws=${encodeURIComponent(ws)}` : ''}`),
  captureAudio(ws: string, blob: Blob, contextNodeId: string | null) {
    const fd = new FormData()
    const ext = blob.type.includes('ogg') ? 'ogg' : blob.type.includes('mp4') ? 'm4a' : blob.type.includes('wav') ? 'wav' : 'webm'
    fd.append('file', blob, `note.${ext}`)
    if (contextNodeId) fd.append('context_node_id', contextNodeId)
    fd.append('source', 'desktop')
    fd.append('wait', 'false')
    return brain<{ capture_id: string; state: string }>(`/workspaces/${ws}/capture`, { method: 'POST', body: fd })
  },
  captureText: (ws: string, text: string, contextNodeId: string | null) =>
    brain<{ capture_id: string; state: string }>(`/workspaces/${ws}/capture`,
      json({ text, context_node_id: contextNodeId, source: 'desktop', wait: false })),
  undo: (cid: string) => brain<{ capture_id: string; reverted: number }>(`/captures/${cid}/undo`, { method: 'POST' }),
  resolveInbox: (id: string, nodeId: string) => brain<{ resolved: string }>(`/inbox/${id}/resolve`, json({ node_id: nodeId })),
  dismissInbox: (id: string) => brain<{ dismissed: string }>(`/inbox/${id}/dismiss`, { method: 'POST' }),
  taskState: (id: string, state: 'open' | 'done' | 'cancelled') =>
    brain<unknown>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ state }) }),
  resolveAlert: (id: string) => brain<unknown>(`/alerts/${id}/resolve`, { method: 'POST' }),
  ask: (ws: string, text: string, contextNodeId: string | null) =>
    call<{ reply: string; ms: number; model?: string }>(config.companion, `/v1/${ws}/chat`,
      json({ text, context_node_id: contextNodeId })),
  audioUrl(captureId: string) {
    const u = new URL(`${config.brain}/api/v1/captures/${captureId}/audio`)
    if (config.token) u.searchParams.set('token', config.token)
    return u.toString()
  },
  eventsUrl(ws: string, lastId: number) {
    const u = new URL(`${config.brain}/api/v1/workspaces/${ws}/events/stream`)
    u.searchParams.set('last_event_id', String(lastId))
    if (config.token) u.searchParams.set('token', config.token)
    return u.toString()
  },
}
