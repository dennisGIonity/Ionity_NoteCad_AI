// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// App state: the map, the live event stream, captures in flight and what to highlight.
import * as F from '@notecad/core/fold'
import { create } from 'zustand'
import { api, config } from './api'
import { mapTree, type MapTree } from './maptree'
import type { CaptureView, LiveEvent, MindMap, SyncStatus, Workspace } from './types'

export type View = 'hud' | 'map'
export type Layout = 'tree' | 'radial'
export type LiveState = 'connecting' | 'live' | 'reconnecting' | 'off'

export const EVENT_TYPES = ['capture.queued', 'stt.transcribing', 'stt.completed', 'router.resolving', 'action.applied',
  'inbox.created', 'capture.completed', 'capture.failed', 'action.undone', 'node.updated', 'task.updated',
  'alert.updated', 'inbox.resolved', 'sync.applied']
export const REFRESHING = new Set(['action.applied', 'action.undone', 'node.updated', 'inbox.resolved', 'task.updated', 'alert.updated', 'capture.completed', 'sync.applied'])
const HIGHLIGHT_MS = 6000

interface AppState {
  view: View
  layout: Layout
  workspaces: Workspace[]
  ws: string
  map: MindMap | null
  mapError: string | null
  live: LiveState
  lastEventId: number
  captures: Record<string, CaptureView>
  activeCapture: string | null
  highlights: Record<string, number>
  focusRequest: { ids: string[]; at: number } | null
  selected: string | null
  /** Fold state of the map (view state for this device and lens: local storage, never synced). */
  fold: F.FoldState
  /** The node a fold action was made on: it stays still on screen while the map re-lays out. */
  foldAnchor: { id: string; at: number } | null
  /** Bumped by "/" and other places that want the typed-note field open. */
  typeRequest: number
  sync: SyncStatus | null
  syncError: string | null
  setView(v: View): void
  setLayout(l: Layout): void
  select(id: string | null): void
  /** Change the fold state; `anchor` stays put on screen. */
  setFold(next: F.FoldState, anchor?: string | null): void
  foldTree(): MapTree | null
  /** Open the path to a node, select it and glide to it (toast "Open", Inbox, search). */
  goTo(id: string): void
  requestTyping(): void
  init(): Promise<void>
  switchWorkspace(ws: string): Promise<void>
  refreshMap(): Promise<void>
  refreshSync(): Promise<void>
  startCapture(c: Pick<CaptureView, 'id' | 'kind' | 'contextNodeId'> & { state?: CaptureView['state'] }): void
  renameCapture(tempId: string, id: string): void
  failCapture(id: string, error: string): void
  onEvent(e: LiveEvent): void
}

let source: EventSource | null = null
let refreshTimer: ReturnType<typeof setTimeout> | undefined
let syncTimer: ReturnType<typeof setInterval> | undefined
let reopenTimer: ReturnType<typeof setTimeout> | undefined
let reopenTries = 0
let treeCache: { map: MindMap; tree: MapTree } | null = null

// fold state per workspace and lens; the first visit shows the main areas
const foldKey = (ws: string, layout: Layout) => `notecad.fold.${ws}.${layout}`
function loadFold(ws: string, layout: Layout): F.FoldState {
  try { return F.parse(localStorage.getItem(foldKey(ws, layout))) ?? F.mainAreas() } catch { return F.mainAreas() }
}
function saveFold(ws: string, layout: Layout, s: F.FoldState) {
  try { localStorage.setItem(foldKey(ws, layout), F.serialize(s)) } catch { /* private window: the fold lasts this session */ }
}

/** The live stream. EventSource retries by itself after a drop, but gives up for good on an HTTP error (a 401 after a
 * token change, the brain restarting behind a proxy): then it is opened again here, backing off to 30 s. */
function openStream(ws: string, cursor: number, get: () => AppState, set: (p: Partial<AppState>) => void) {
  clearTimeout(reopenTimer)
  source?.close()
  const es = new EventSource(api.eventsUrl(ws, cursor))
  source = es
  es.onopen = () => { reopenTries = 0; set({ live: 'live' }) }
  es.onerror = () => {
    if (source !== es) return
    if (es.readyState !== EventSource.CLOSED) { set({ live: 'reconnecting' }); return }
    set({ live: 'reconnecting' })
    const wait = Math.min(30000, 1000 * 2 ** reopenTries++)
    reopenTimer = setTimeout(() => { if (get().ws === ws && source === es) openStream(ws, get().lastEventId, get, set) }, wait)
  }
  for (const t of EVENT_TYPES) {
    es.addEventListener(t, (ev) => {
      try { get().onEvent(JSON.parse((ev as MessageEvent).data)) } catch { /* bad frame */ }
    })
  }
}

export const useApp = create<AppState>((set, get) => ({
  view: (new URLSearchParams(location.search).get('view') as View) || 'hud',
  layout: 'tree',
  workspaces: [],
  ws: config.workspace,
  map: null,
  mapError: null,
  live: 'off',
  lastEventId: 0,
  captures: {},
  activeCapture: null,
  highlights: {},
  focusRequest: null,
  selected: null,
  fold: F.mainAreas(),
  foldAnchor: null,
  typeRequest: 0,
  sync: null,
  syncError: null,

  setView: (view) => set({ view }),
  setLayout: (layout) => set({ layout, fold: loadFold(get().ws, layout) }),
  select: (selected) => set({ selected }),
  setFold(next, anchor = null) {
    set({ fold: next, foldAnchor: anchor ? { id: anchor, at: Date.now() } : null })
    saveFold(get().ws, get().layout, next)
  },
  foldTree() {
    const map = get().map
    if (!map) return null
    if (treeCache?.map !== map) treeCache = { map, tree: mapTree(map) }
    return treeCache.tree
  },
  goTo(id) {
    const t = get().foldTree()
    if (t) get().setFold(F.reveal(t.idx, get().fold, id))
    set({ view: 'map', selected: id, focusRequest: { ids: [id], at: Date.now() } })
  },
  requestTyping: () => set((s) => ({ typeRequest: s.typeRequest + 1 })),

  async init() {
    try {
      const workspaces = await api.workspaces()
      set({ workspaces })
      const ws = get().ws && workspaces.some((w) => w.id === get().ws) ? get().ws : workspaces[0]?.id
      if (ws) await get().switchWorkspace(ws)
      else set({ mapError: 'No workspace yet: create one in the brain (POST /v1/workspaces) or run tools/seed_demo_farm.py' })
    } catch (e) {
      set({ mapError: (e as Error).message, live: 'off' })
      setTimeout(() => get().init(), 4000)  // the brain may still be starting
    }
  },

  async switchWorkspace(ws) {
    config.save({ workspace: ws })
    clearTimeout(reopenTimer)
    source?.close()
    source = null
    set({ ws, map: null, captures: {}, activeCapture: null, selected: null, highlights: {}, fold: loadFold(ws, get().layout), foldAnchor: null })
    await get().refreshMap()
    if (get().ws !== ws) return  // another switch happened while the map loaded
    const cursor = get().map?.cursor ?? 0
    set({ lastEventId: cursor, live: 'connecting' })
    openStream(ws, cursor, get, set)
    await get().refreshSync()
    clearInterval(syncTimer)
    syncTimer = setInterval(() => get().refreshSync(), 10000)
  },

  async refreshMap() {
    const ws = get().ws
    if (!ws) return
    try {
      const map = await api.mindmap(ws)
      if (get().ws !== ws) return
      const t = mapTree(map)
      treeCache = { map, tree: t }
      // ids that were deleted or synced away drop out of the saved fold state
      const fold = F.prune(t.idx, get().fold)
      const pruned = fold.expanded.length !== get().fold.expanded.length || fold.collapsed.length !== get().fold.collapsed.length
      set({ map, mapError: null, ...(pruned ? { fold } : {}) })
      if (pruned) saveFold(ws, get().layout, fold)
    } catch (e) {
      set({ mapError: (e as Error).message })
    }
  },

  async refreshSync() {
    const ws = get().ws
    if (!ws) return
    try {
      set({ sync: await api.sync(ws), syncError: null })
    } catch (e) {
      set({ syncError: (e as Error).message })
    }
  },

  startCapture(c) {
    set((s) => ({
      captures: { ...s.captures, [c.id]: { ...c, state: c.state ?? 'uploading', startedAt: Date.now(), events: 0, applied: [], inbox: [] } },
      activeCapture: c.id,
    }))
  },

  renameCapture(tempId, id) {
    set((s) => {
      const { [tempId]: cap, ...rest } = s.captures
      if (!cap) return {}
      const existing = rest[id]  // events may have arrived before the upload returned
      return { captures: { ...rest, [id]: { ...cap, ...existing, id, kind: cap.kind, contextNodeId: cap.contextNodeId, startedAt: cap.startedAt } }, activeCapture: id }
    })
  },

  failCapture(id, error) {
    set((s) => ({ captures: { ...s.captures, [id]: { ...s.captures[id], state: 'failed', error, finishedAt: Date.now() } } }))
  },

  onEvent(e) {
    if (e.workspace_id !== get().ws) return
    set({ lastEventId: Math.max(get().lastEventId, e.id) })
    const cid = e.capture_id as string | undefined
    if (cid) {
      set((s) => {
        const cap: CaptureView = s.captures[cid] ?? {
          id: cid, state: 'queued', kind: (e.kind as 'audio' | 'text') ?? 'text', contextNodeId: (e.context_node_id as string) ?? null,
          startedAt: Date.now(), events: 0, applied: [], inbox: [],
        }
        const next = reduceCapture(cap, e)
        if (next === cap) return {}
        // a capture from another device (phone) becomes the active one if nothing of ours is in flight
        const mine = s.activeCapture && s.captures[s.activeCapture]
        const busy = mine && !mine.finishedAt && mine.id !== cid
        return { captures: { ...s.captures, [cid]: next }, activeCapture: busy ? s.activeCapture : cid }
      })
    }
    if (e.type === 'action.applied' || e.type === 'action.undone') {
      const ids = (e.map_node_ids as string[] | undefined) ?? (e.node_ids as string[] | undefined) ?? []
      const until = Date.now() + HIGHLIGHT_MS
      set((s) => {
        const highlights = { ...s.highlights }
        for (const id of ids) highlights[id] = until
        return { highlights, focusRequest: { ids, at: Date.now() } }
      })
      setTimeout(() => {
        const now = Date.now()
        set((s) => ({ highlights: Object.fromEntries(Object.entries(s.highlights).filter(([, t]) => t > now)) }))
      }, HIGHLIGHT_MS + 50)
    }
    if (REFRESHING.has(e.type)) {
      clearTimeout(refreshTimer)
      refreshTimer = setTimeout(() => get().refreshMap(), 250)
    }
    if (e.type === 'capture.completed' || e.type === 'capture.failed' || e.type === 'action.undone' || e.type === 'sync.applied') get().refreshSync()
  },
}))

export function reduceCapture(c: CaptureView, e: LiveEvent): CaptureView {
  switch (e.type) {
    case 'capture.queued':
      return { ...c, state: c.state === 'uploading' || c.state === 'recording' ? 'queued' : c.state, kind: (e.kind as CaptureView['kind']) ?? c.kind }
    case 'stt.transcribing':
      return { ...c, state: 'transcribing' }
    case 'stt.completed':
      return { ...c, state: 'routing', transcript: e.transcript as string }
    case 'router.resolving':
      return { ...c, state: 'routing', events: (e.events as number) ?? c.events, resolving: { idx: e.idx as number, text: e.text as string } }
    case 'action.applied':
      return {
        ...c, applied: [...c.applied.filter((a) => a.idx !== e.idx), {
          idx: e.idx as number, nodes: (e.nodes as CaptureView['applied'][0]['nodes']) ?? [], actions: (e.actions as string[]) ?? [],
          tasks: (e.tasks as number) ?? 0, alerts: (e.alerts as number) ?? 0, notes: (e.notes as number) ?? 0,
          delegated: (e.delegated as { to: string }[]) ?? [],
        }],
      }
    case 'inbox.created':
      return {
        ...c, inbox: [...c.inbox.filter((i) => i.inbox_id !== e.inbox_id), {
          inbox_id: e.inbox_id as string, idx: e.idx as number, text: e.text as string, question: e.question as string,
          options: (e.options as CaptureView['inbox'][0]['options']) ?? [],
        }],
      }
    case 'inbox.resolved':
      return { ...c, inbox: c.inbox.map((i) => (i.inbox_id === e.inbox_id ? { ...i, resolved: e.node_id as string } : i)) }
    case 'capture.completed':
      return { ...c, state: e.state as CaptureView['state'], finishedAt: Date.now(), resolving: undefined }
    case 'capture.failed':
      return { ...c, state: 'failed', error: e.error as string, finishedAt: Date.now() }
    case 'action.undone':
      return { ...c, state: 'undone' }
    default:
      return c
  }
}

/** "Updated 5 nodes in Fields / South Block": the places a capture changed, by their shared branch. */
export function summarise(c: CaptureView): { count: number; where: string; paths: string[] } {
  const byId = new Map<string, string>()
  for (const a of c.applied) for (const n of a.nodes) byId.set(n.map_id, n.map_path)
  const paths = [...byId.values()]
  if (!paths.length) return { count: 0, where: '', paths }
  const split = paths.map((p) => p.split(' > '))
  const common: string[] = []
  for (let i = 0; i < split[0].length; i++) {
    const seg = split[0][i]
    if (split.every((s) => s[i] === seg)) common.push(seg)
    else break
  }
  if (paths.length > 1 && common.length === split[0].length) common.pop()
  const where = paths.length === 1 ? split[0].join(' / ') : (common.length ? common.join(' / ') : split.map((s) => s[s.length - 1]).slice(0, 3).join(', '))
  return { count: paths.length, where, paths }
}

/** "Updated 5 nodes in Fields / South Block", or for one: "Updated Main Borehole Pump in Infrastructure / Water". */
export function headline(s: { count: number; where: string }) {
  if (s.count !== 1) return `Updated ${s.count} nodes in ${s.where}`
  const parts = s.where.split(' / ')
  return parts.length > 1 ? `Updated ${parts.pop()} in ${parts.join(' / ')}` : `Updated ${s.where}`
}
