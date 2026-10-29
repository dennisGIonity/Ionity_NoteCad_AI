// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// POPIA review, fix 5: the notice opens by itself until an owner has accepted it, or a member has read it.
import { describe, expect, it } from 'vitest'
import type { PrivacyNotice } from '../lib/types'
import { notNeeded } from './PrivacyNotice'

const base: PrivacyNotice = {
  version: 1, business: 'Highveld Farm', owners: ['Dennis'], contact: null, accepted_at: null,
  retention: { audio_days: null, transcript_days: null, log_days: null }, retention_text: '',
  recommended: { audio_days: 90, transcript_days: 365, log_days: 365 },
  cloud: { claude: false, deepgram: false, allowed: false, available: { claude: false, deepgram: false }, sync: null },
  my_ack_at: null, is_owner: true, officer: 'Dennis', officer_named: false,
}

describe('when the privacy notice must be shown', () => {
  it('to an owner until they accept it', () => {
    expect(notNeeded(base)).toBe(false)
    expect(notNeeded({ ...base, accepted_at: '2026-10-29T10:00:00+00:00' })).toBe(true)
  })

  it('to a member until they have read it, even when the owner has accepted', () => {
    const member = { ...base, is_owner: false, accepted_at: '2026-10-29T10:00:00+00:00' }
    expect(notNeeded(member)).toBe(false)
    expect(notNeeded({ ...member, my_ack_at: '2026-10-29T11:00:00+00:00' })).toBe(true)
  })

  it('not at all when the brain has none (an older brain)', () => {
    expect(notNeeded(null)).toBe(true)
  })
})
