// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Phase 6: notes parked on a refused token used to stay parked after pairing again (ADR 0013).
import { describe, expect, it } from 'vitest'
import { outbox, type OutboxItem } from './outbox'

const item = (id: string, patch: Partial<OutboxItem>): OutboxItem => ({
  id, kind: 'text', text: 'x', size: 1, createdAt: Date.now(), recordedAt: new Date().toISOString(), contextNodeId: null,
  contextTitle: null, source: 'phone', state: 'saved', progress: 0, attempts: 0, ...patch,
})

describe('outbox.unpark', () => {
  it('sends token-refused notes again and leaves the rest alone', async () => {
    await outbox.put(item('a', { state: 'failed', error: 'The phone token was not accepted: pair again', nextTryAt: Number.MAX_SAFE_INTEGER }))
    await outbox.put(item('b', { state: 'failed', error: 'Recording too large', nextTryAt: Number.MAX_SAFE_INTEGER }))
    await outbox.put(item('c', { state: 'applied' }))
    await outbox.unpark()
    expect((await outbox.get('a'))!.state).toBe('saved')
    expect((await outbox.get('a'))!.nextTryAt).toBe(0)
    expect((await outbox.get('b'))!.state).toBe('failed')
    expect((await outbox.get('c'))!.state).toBe('applied')
  })
})
