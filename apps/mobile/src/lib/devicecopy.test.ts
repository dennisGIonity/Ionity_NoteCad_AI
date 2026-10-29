// Ionity Business Mind Map (IBMM) - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// ADR 0014: the member's copy on the phone. A branch they may no longer see goes with everything on it; a capture
// that became too restricted goes with its audio; a reset wipes it all.
import { describe, expect, it } from 'vitest'
import { apply, deviceCopy, fromSnapshot, keyOf, type Snapshot } from './devicecopy'
import { isDeviceToken, parseJoinLink } from './pairing'

const snap = (): Snapshot => ({
  reset: true, cursor: 'w|e|10|0|x',
  tables: {
    nodes: [{ id: 'root', path: 'r' }, { id: 'water', path: 'r/w' }, { id: 'pump', path: 'r/w/p' }, { id: 'sheep', path: 'r/s' }],
    notes: [{ id: 'n1', node_id: 'pump', body: 'oil low' }, { id: 'n2', node_id: 'sheep', body: 'shorn' }],
    edges: [{ id: 'e1', src_id: 'pump', dst_id: 'sheep' }],
    node_aliases: [{ node_id: 'pump', alias: 'main pump' }],
    captures: [{ id: 'c1' }, { id: 'c2' }],
    capture_events: [{ capture_id: 'c1', idx: 0 }],
  },
})

describe('the device copy', () => {
  it('drops a hidden branch with everything that hangs off it', () => {
    const copy = fromSnapshot(snap())
    const out = apply(copy, [{ op: 'H', tbl: 'nodes', pk: 'water' }])
    expect([...copy.get('nodes')!.keys()]).toEqual(['root', 'sheep'])
    expect([...copy.get('notes')!.keys()]).toEqual(['n2'])
    expect(copy.get('edges')!.size).toBe(0)
    expect(copy.get('node_aliases')!.size).toBe(0)
    expect(out.del).toContainEqual(['notes', 'n1'])
  })

  it('a capture too restricted now goes with its events and its audio', () => {
    const copy = fromSnapshot(snap())
    const out = apply(copy, [{ op: 'D', tbl: 'captures', pk: 'c1' }, { op: 'U', tbl: 'notes', pk: 'n3', row: { id: 'n3', node_id: 'sheep' } }])
    expect(copy.get('captures')!.has('c1')).toBe(false)
    expect(copy.get('capture_events')!.size).toBe(0)
    expect(out.audioGone).toEqual(['c1'])
    expect(copy.get('notes')!.has('n3')).toBe(true)
  })

  it('keeps composite keys the way the brain journals them', () => {
    expect(keyOf('node_aliases', { node_id: 'pump', alias: 'main pump' })).toBe('pump\u001fmain pump')
  })

  it('is kept in IndexedDB and wiped whole', async () => {
    await deviceCopy.replace(snap())
    await deviceCopy.keepAudio('c1', new Blob(['x']))
    expect(await deviceCopy.cursor()).toBe('w|e|10|0|x')
    const loaded = await deviceCopy.load()
    expect(loaded.get('notes')!.size).toBe(2)
    await deviceCopy.write(apply(loaded, [{ op: 'D', tbl: 'captures', pk: 'c1' }]), 'w|e|11|0|x')
    expect(await deviceCopy.audio('c1')).toBeUndefined()
    await deviceCopy.wipe()
    expect(await deviceCopy.cursor()).toBeNull()
    expect((await deviceCopy.load()).size).toBe(0)
  })
})

describe('invite links', () => {
  it('reads a join link and refuses anything else', () => {
    expect(parseJoinLink('notecad://join?u=http%3A%2F%2F192.168.1.20%3A8788&c=abcdefgh12&w=farm'))
      .toEqual({ url: 'http://192.168.1.20:8788', code: 'abcdefgh12', ws: 'farm' })
    expect(parseJoinLink('notecad://join?u=javascript:alert(1)&c=abcdefgh12&w=farm')).toBeNull()
    expect(parseJoinLink('notecad://join?u=http%3A%2F%2Fx&c=abc&w=farm')).toBeNull()  // too short to be a code
    expect(isDeviceToken('nct_abc') && !isDeviceToken('shared-token')).toBe(true)
  })
})
