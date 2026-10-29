// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// POPIA review, fix 4: the QR and the invite carry the brain's certificate fingerprint; plain-HTTP pairings re-pair.
import { describe, expect, it } from 'vitest'
import { needsRepair, parseJoinLink, parsePairLink } from './pairing'

const F = '292fe2731d4b20560c382a2a839be3da539e5af9fb71654c8dce6155e5b971b4'

describe('pairing links', () => {
  it('reads the certificate pin from a pairing QR', () => {
    const p = parsePairLink(`notecad://pair?u=https%3A%2F%2F192.168.1.20%3A9788&t=tok&w=farm&f=${F.toUpperCase()}`)
    expect(p).toEqual({ url: 'https://192.168.1.20:9788', token: 'tok', ws: 'farm', pin: F })
  })

  it('reads the certificate pin from an invite, and ignores one that is not a fingerprint', () => {
    expect(parseJoinLink(`notecad://join?u=https%3A%2F%2F10.0.0.5%3A9788&c=abcdefgh&w=farm&f=${F}`)?.pin).toBe(F)
    expect(parseJoinLink('notecad://join?u=https%3A%2F%2F10.0.0.5%3A9788&c=abcdefgh&w=farm&f=xyz')?.pin).toBeUndefined()
  })

  it('asks a phone paired over plain HTTP with another machine to pair again', () => {
    expect(needsRepair({ url: 'http://192.168.1.20:8788', token: 't', ws: 'farm' })).toBe(true)
    expect(needsRepair({ url: 'https://192.168.1.20:9788', token: 't', ws: 'farm', pin: F })).toBe(false)
    expect(needsRepair({ url: 'http://127.0.0.1:8788', token: '', ws: 'farm' })).toBe(false)
    expect(needsRepair(null)).toBe(false)
  })
})
