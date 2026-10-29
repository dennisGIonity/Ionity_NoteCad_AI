// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// ADR 0014: a computer joins with an invite link; nothing is joined unless the person confirms what the brain says.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { config, joinFromLink, parseJoinLink } from './api'

const LINK = 'notecad://join?u=http%3A%2F%2F192.168.1.20%3A8788&c=abcdefgh12&w=farm'

afterEach(() => vi.unstubAllGlobals())

function brain(calls: string[]) {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    const body = url.endsWith('/api/v1/join')
      ? { token: 'nct_desk', workspace_id: 'farm', role: 'manager' }
      : { workspace: 'Highveld Farm', role: 'manager', name: 'Marie', scope: ['Infrastructure'] }
    return new Response(JSON.stringify(body), { status: 200 })
  }))
}

describe('joining with an invite link', () => {
  it('reads only notecad://join links', () => {
    expect(parseJoinLink(LINK)).toEqual({ url: 'http://192.168.1.20:8788', code: 'abcdefgh12', ws: 'farm' })
    expect(parseJoinLink('notecad://pair?u=http%3A%2F%2Fx&t=1&w=farm')).toBeNull()
  })

  it('asks first, and does nothing when the person says no', async () => {
    const calls: string[] = []
    brain(calls)
    const asked: string[] = []
    expect(await joinFromLink(LINK, (t) => { asked.push(t); return false })).toBe('Not joined')
    expect(asked[0]).toBe('Join Highveld Farm as manager (Infrastructure), as Marie?')
    expect(calls).not.toContain('POST http://192.168.1.20:8788/api/v1/join')  // the one-time code is not spent
    expect(calls.some((c) => c.includes('abcdefgh12'))).toBe(false)  // and never in a URL (POPIA review)
  })

  it('keeps the device token and the brain once confirmed', async () => {
    const calls: string[] = []
    brain(calls)
    expect(await joinFromLink(LINK, () => true)).toBeNull()
    expect(calls).toContain('POST http://192.168.1.20:8788/api/v1/join')
    expect([config.token, config.brain, config.workspace]).toEqual(['nct_desk', 'http://192.168.1.20:8788', 'farm'])
  })
})
