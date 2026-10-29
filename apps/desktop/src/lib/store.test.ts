// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Phase 6 regressions in the app store (ADR 0013).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  config: { workspace: 'ws1', save: vi.fn() },
  api: {
    workspaces: vi.fn(async () => [{ id: 'ws1', name: 'Farm' }]),
    mindmap: vi.fn(async () => ({ cursor: 7, nodes: [], edges: [], root: 'r', stats: {}, workspace: { id: 'ws1', name: 'Farm' } })),
    sync: vi.fn(async () => ({})),
    eventsUrl: async (ws: string, id: number) => `http://brain/${ws}?last_event_id=${id}`,
  },
}))

class FakeSource {
  static all: FakeSource[] = []
  static readonly CLOSED = 2
  readyState = 0
  url: string
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  types: string[] = []
  constructor(url: string) { this.url = url; FakeSource.all.push(this) }
  addEventListener(t: string) { this.types.push(t) }
  close() { this.readyState = 2 }
}

describe('live events', () => {
  beforeEach(() => { FakeSource.all = []; vi.stubGlobal('EventSource', FakeSource); vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

  it('listens to every event that refreshes the map, sync.applied included', async () => {
    const { EVENT_TYPES, REFRESHING } = await import('./store')
    for (const t of REFRESHING) expect(EVENT_TYPES).toContain(t)
  })

  it('opens the stream again after the browser gave up on it', async () => {
    const { useApp } = await import('./store')
    await useApp.getState().switchWorkspace('ws1')
    expect(FakeSource.all).toHaveLength(1)
    const first = FakeSource.all[0]
    expect(first.types).toContain('sync.applied')
    first.readyState = FakeSource.CLOSED  // e.g. a 401 after the token changed
    first.onerror?.()
    expect(useApp.getState().live).toBe('reconnecting')
    await vi.advanceTimersByTimeAsync(1100)
    expect(FakeSource.all).toHaveLength(2)
    expect(FakeSource.all[1].url).toContain('last_event_id=7')
  })

  it('a quick second switch does not leave the first stream open', async () => {
    const { useApp } = await import('./store')
    const a = useApp.getState().switchWorkspace('ws1')
    const b = useApp.getState().switchWorkspace('ws1')
    await Promise.all([a, b])
    const open = FakeSource.all.filter((s) => s.readyState !== FakeSource.CLOSED)
    expect(open).toHaveLength(1)
  })
})
