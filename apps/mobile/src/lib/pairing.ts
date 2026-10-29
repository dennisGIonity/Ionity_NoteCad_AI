// Ionity NoteCad - Mobile | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Which brain this phone talks to: the desktop or the Edge AI Node on the farm's network, with its phone token.
// Set by scanning the pairing QR on the desktop (a notecad://pair link) or by typing it in.
import { Native } from './native'

export interface Pairing {
  url: string; token: string; ws: string; name?: string
  /** Joined with an invite (ADR 0014): this phone's own token, and who it acts for. */
  member?: { id: string; name: string; role: string }
}

/** A seat offered to this phone: notecad://join?u=<brain>&c=<one-time code>&w=<farm> (the code, never a token). */
export interface JoinLink { url: string; code: string; ws: string }

export const isDeviceToken = (t: string | undefined) => !!t && t.startsWith('nct_')

const KEY = 'notecad.pairing'

export function loadPairing(): Pairing | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || 'null')
    return p?.url && p.ws ? p : null
  } catch {
    return null
  }
}

export async function savePairing(p: Pairing | null): Promise<void> {
  try {
    if (p) localStorage.setItem(KEY, JSON.stringify(p))
    else localStorage.removeItem(KEY)
  } catch { /* storage refused */ }
  // the Android bubble records and uploads without the app open: it needs the same address and token
  await Native.configure(p ? { url: p.url, token: p.token, ws: p.ws } : { url: '', token: '', ws: '' }).catch(() => undefined)
}

/** notecad://pair?u=http://192.168.1.20:8788&t=TOKEN&w=showcase (from the desktop's pairing QR). */
export function parsePairLink(link: string): Pairing | null {
  try {
    const s = link.trim()
    const q = s.includes('?') ? s.slice(s.indexOf('?') + 1) : s
    const p = new URLSearchParams(q)
    const url = (p.get('u') || '').replace(/\/$/, '')
    if (!/^https?:\/\//.test(url) || !p.get('w')) return null
    return { url, token: p.get('t') || '', ws: p.get('w') || '' }
  } catch {
    return null
  }
}

export function parseJoinLink(link: string): JoinLink | null {
  try {
    const s = link.trim()
    if (!/^notecad:\/\/join/i.test(s) && !s.includes('c=')) return null
    const p = new URLSearchParams(s.includes('?') ? s.slice(s.indexOf('?') + 1) : s)
    const url = (p.get('u') || '').replace(/\/$/, '')
    const code = p.get('c') || ''
    if (!/^https?:\/\//.test(url) || !p.get('w') || code.length < 6) return null
    return { url, code, ws: p.get('w') || '' }
  } catch {
    return null
  }
}

/** Time-ordered UUID (RFC 9562 v7): the capture id is made on the phone, so a retried upload never doubles. */
export function uuid7(): string {
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  const ms = Date.now()
  for (let i = 0; i < 6; i++) b[i] = Math.floor(ms / 2 ** (8 * (5 - i))) & 0xff
  b[6] = (b[6] & 0x0f) | 0x70
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}
