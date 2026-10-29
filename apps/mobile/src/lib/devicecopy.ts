// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The member's copy of the business on this phone (ADR 0014, decision 21). It holds only what the brain sent for this
// member's role and branches: a snapshot, then changes (GET /v1/device/pull). Tombstones take out what they may no
// longer see: H drops a branch with everything that hangs off it, D a row (a capture with its cached audio). reset
// means: wipe and take a new snapshot. The phone never sends this copy anywhere; it writes through notes and calls.
import { openDB, type IDBPDatabase } from 'idb'

export type Row = Record<string, unknown>
export interface Change { op: 'U' | 'D' | 'H'; tbl: string; pk: string; row?: Row }
export interface Pulled { reset: boolean; changes?: Change[]; tombstones?: Change[]; cursor?: string; more?: boolean }
export interface Snapshot { reset: true; tables: Record<string, Row[]>; cursor: string }

const SEP = '\u001f'
/** Each table's key columns, as the brain journals them (services/brain/notecad_brain/sync.py TABLES). */
export const KEYS: Record<string, string[]> = {
  workspaces: ['id'], members: ['id'], member_scopes: ['member_id', 'node_id'], seats: ['id'], invites: ['id'],
  devices: ['id'], nodes: ['id'], node_aliases: ['node_id', 'alias'], edges: ['id'], captures: ['id'],
  capture_events: ['capture_id', 'idx'], notes: ['id'], tasks: ['id'], alerts: ['id'],
  profile_facts: ['workspace_id', 'key'], inbox: ['id'], notifications: ['id'],
}
const ON_NODE = ['notes', 'tasks', 'alerts', 'node_aliases']

export const keyOf = (tbl: string, row: Row) => (KEYS[tbl] ?? ['id']).map((k) => String(row[k])).join(SEP)

/** The copy in memory: table -> key -> row. Pure, so it is tested without a database. */
export type Copy = Map<string, Map<string, Row>>
export interface Applied { put: [string, string, Row][]; del: [string, string][]; audioGone: string[] }

export function fromSnapshot(s: Snapshot): Copy {
  const copy: Copy = new Map()
  for (const [tbl, rows] of Object.entries(s.tables)) copy.set(tbl, new Map(rows.map((r) => [keyOf(tbl, r), r])))
  return copy
}

function table(copy: Copy, tbl: string): Map<string, Row> {
  let t = copy.get(tbl)
  if (!t) {
    t = new Map()
    copy.set(tbl, t)
  }
  return t
}

/** Take out a branch the member may no longer see: the node, everything under it, and all that hangs off them. */
export function dropBranch(copy: Copy, nodeId: string, out: Applied): void {
  const nodes = table(copy, 'nodes')
  const top = nodes.get(nodeId)
  const path = typeof top?.path === 'string' ? top.path : null
  const gone = new Set<string>([nodeId])
  if (path) for (const [id, n] of nodes) if (n.path === path || String(n.path).startsWith(`${path}/`)) gone.add(id)
  for (const id of gone) if (nodes.delete(id)) out.del.push(['nodes', id])
  for (const tbl of ON_NODE) {
    const t = table(copy, tbl)
    for (const [k, r] of t) if (gone.has(String(r.node_id))) { t.delete(k); out.del.push([tbl, k]) }
  }
  const edges = table(copy, 'edges')
  for (const [k, e] of edges) {
    if (gone.has(String(e.src_id)) || gone.has(String(e.dst_id))) { edges.delete(k); out.del.push(['edges', k]) }
  }
}

/** Apply a pull: rows, deletes and tombstones. Returns what to write, what to delete, and the audio to throw away. */
export function apply(copy: Copy, changes: Change[]): Applied {
  const out: Applied = { put: [], del: [], audioGone: [] }
  for (const ch of changes) {
    if (ch.op === 'H' || (ch.op === 'D' && ch.tbl === 'nodes')) {
      dropBranch(copy, ch.pk, out)
    } else if (ch.op === 'D') {
      if (table(copy, ch.tbl).delete(ch.pk)) out.del.push([ch.tbl, ch.pk])
      if (ch.tbl === 'captures') {
        out.audioGone.push(ch.pk)
        const ev = table(copy, 'capture_events')
        for (const [k, r] of ev) if (r.capture_id === ch.pk) { ev.delete(k); out.del.push(['capture_events', k]) }
      }
    } else if (ch.row) {
      table(copy, ch.tbl).set(ch.pk, ch.row)
      out.put.push([ch.tbl, ch.pk, ch.row])
    }
  }
  return out
}

// ---------------------------------------------------------------- kept in IndexedDB
const DB = 'notecad-copy'
let dbp: Promise<IDBPDatabase> | null = null

function db() {
  dbp ??= openDB(DB, 1, {
    upgrade(d) {
      d.createObjectStore('rows')   // `${tbl}\u001f${key}` -> row
      d.createObjectStore('audio')  // capture id -> recording kept for playback without signal
      d.createObjectStore('meta')   // cursor
    },
  })
  return dbp
}

const rowKey = (tbl: string, pk: string) => `${tbl}${SEP}${pk}`

export const deviceCopy = {
  async load(): Promise<Copy> {
    const d = await db()
    const copy: Copy = new Map()
    let cur = await d.transaction('rows').store.openCursor()
    while (cur) {
      const k = String(cur.key)
      const i = k.indexOf(SEP)
      table(copy, k.slice(0, i)).set(k.slice(i + 1), cur.value as Row)
      cur = await cur.continue()
    }
    return copy
  },
  async cursor(): Promise<string | null> {
    return ((await (await db()).get('meta', 'cursor')) as string | undefined) ?? null
  },
  async replace(s: Snapshot): Promise<Copy> {
    const copy = fromSnapshot(s)
    const d = await db()
    const tx = d.transaction(['rows', 'audio', 'meta'], 'readwrite')
    await Promise.all([tx.objectStore('rows').clear(), tx.objectStore('audio').clear()])
    for (const [tbl, rows] of copy) for (const [k, r] of rows) void tx.objectStore('rows').put(r, rowKey(tbl, k))
    void tx.objectStore('meta').put(s.cursor, 'cursor')
    await tx.done
    return copy
  },
  async write(a: Applied, cursor: string): Promise<void> {
    const d = await db()
    const tx = d.transaction(['rows', 'audio', 'meta'], 'readwrite')
    for (const [tbl, pk, row] of a.put) void tx.objectStore('rows').put(row, rowKey(tbl, pk))
    for (const [tbl, pk] of a.del) void tx.objectStore('rows').delete(rowKey(tbl, pk))
    for (const id of a.audioGone) void tx.objectStore('audio').delete(id)
    void tx.objectStore('meta').put(cursor, 'cursor')
    await tx.done
  },
  async keepAudio(captureId: string, blob: Blob): Promise<void> {
    await (await db()).put('audio', blob, captureId)
  },
  async audio(captureId: string): Promise<Blob | undefined> {
    return (await db()).get('audio', captureId)
  },
  /** Everything gone: rows, cached audio, cursor (a revoked phone, a reset, another farm). */
  async wipe(): Promise<void> {
    const d = await db()
    const tx = d.transaction(['rows', 'audio', 'meta'], 'readwrite')
    await Promise.all([tx.objectStore('rows').clear(), tx.objectStore('audio').clear(), tx.objectStore('meta').clear()])
    await tx.done
  },
}

/** Bring the copy up to date: a snapshot the first time (or after a reset), then pulls until nothing is left. */
export async function syncCopy(get: <T>(path: string) => Promise<T>): Promise<{ reset: boolean; changes: number }> {
  let cursor = await deviceCopy.cursor()
  let copy: Copy | null = null
  let reset = false
  let changes = 0
  for (let round = 0; round < 50; round++) {
    if (!cursor) {
      const s = await get<Snapshot>('/device/snapshot')
      copy = await deviceCopy.replace(s)
      cursor = s.cursor
      reset = true
      continue
    }
    const p = await get<Pulled>(`/device/pull?cursor=${encodeURIComponent(cursor)}`)
    if (p.reset) {
      await deviceCopy.wipe()
      cursor = null
      continue
    }
    copy ??= await deviceCopy.load()
    const all = [...(p.tombstones ?? []), ...(p.changes ?? [])]
    await deviceCopy.write(apply(copy, all), p.cursor ?? cursor)
    changes += all.length
    cursor = p.cursor ?? cursor
    if (!p.more) break
  }
  return { reset, changes }
}
