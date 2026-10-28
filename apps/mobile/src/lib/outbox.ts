// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The on-device outbox (IndexedDB): every note is saved on the phone first, with its own capture id, and only then
// uploaded. No signal in the field loses nothing: the note waits here and goes when the phone is back on the network.
import { openDB, type IDBPDatabase } from 'idb'

export type ItemState = 'saved' | 'uploading' | 'uploaded' | 'transcribing' | 'routing' | 'applied' | 'needs_review'
  | 'failed' | 'undone'

export interface OutboxItem {
  id: string                  // the capture id (UUIDv7), made on the phone
  kind: 'audio' | 'text'
  blob?: Blob                 // dropped once the brain has filed it
  mime?: string
  text?: string
  size: number
  createdAt: number
  recordedAt: string
  contextNodeId: string | null
  contextTitle?: string | null
  source: string
  state: ItemState
  progress: number            // 0..1 of the upload
  uploadUrl?: string          // tus upload, so a dropped upload resumes where it stopped
  attempts: number
  nextTryAt?: number
  error?: string
  transcript?: string
  summary?: string
}

const DB = 'notecad-outbox'
let dbp: Promise<IDBPDatabase> | null = null

function db() {
  dbp ??= openDB(DB, 1, {
    upgrade(d) {
      const s = d.createObjectStore('items', { keyPath: 'id' })
      s.createIndex('createdAt', 'createdAt')
    },
  })
  return dbp
}

export const outbox = {
  async all(): Promise<OutboxItem[]> {
    return ((await (await db()).getAllFromIndex('items', 'createdAt')) as OutboxItem[]).reverse()
  },
  async get(id: string): Promise<OutboxItem | undefined> {
    return (await db()).get('items', id)
  },
  async put(item: OutboxItem): Promise<void> {
    await (await db()).put('items', item)
  },
  async patch(id: string, patch: Partial<OutboxItem>): Promise<OutboxItem | undefined> {
    const d = await db()
    const tx = d.transaction('items', 'readwrite')
    const cur = (await tx.store.get(id)) as OutboxItem | undefined
    if (!cur) {
      await tx.done
      return undefined
    }
    const next = { ...cur, ...patch }
    await tx.store.put(next)
    await tx.done
    return next
  },
  async remove(id: string): Promise<void> {
    await (await db()).delete('items', id)
  },
  /** After pairing again: notes parked because the old token was refused are sent again. */
  async unpark(): Promise<void> {
    for (const it of await this.all()) {
      if (it.state === 'failed' && /token|pair again/.test(it.error ?? '')) await this.patch(it.id, { state: 'saved', nextTryAt: 0, error: undefined })
    }
  },
  /** Keep a week of filed notes for the list; audio is dropped as soon as a note is filed. */
  async prune(days = 7): Promise<void> {
    const cut = Date.now() - days * 86400000
    for (const it of await this.all()) {
      if (it.createdAt < cut && ['applied', 'needs_review', 'undone'].includes(it.state)) await this.remove(it.id)
    }
  },
}

export const DONE: ItemState[] = ['applied', 'needs_review', 'undone']
export const WAITING: ItemState[] = ['saved', 'uploading', 'failed']
