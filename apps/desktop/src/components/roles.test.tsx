// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// ADR 0014, decision 27: the app offers what GET /me allows. An employee gets no People & seats and no Pair a phone; a
// manager gets People & seats; a restricted branch shows its lock. (The brain still decides every request.)
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { can, useApp } from '../lib/store'
import type { Me, MapNode } from '../lib/types'
import { LockBadge } from './nodes/Cards'
import { SyncIndicator } from './SyncIndicator'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const me = (level: number, caps: Record<string, Me['capabilities'][string]>): Me => ({
  workspace_id: 'farm', member_id: `m${level}`, name: 'X', level, role: (['', 'owner', 'manager', 'employee'] as const)[level] as Me['role'],
  read_only: false, scopes: [], device_id: level === 1 ? null : 'd1', capabilities: caps,
})
const EMPLOYEE = me(3, { invite: 'refuse', manage_workspace: 'refuse', set_visibility: 'refuse', append_note: 'allow' })
const MANAGER = me(2, { invite: 'allow', manage_workspace: 'refuse', set_visibility: 'allow' })
const OWNER = me(1, { invite: 'allow', manage_workspace: 'allow', set_visibility: 'allow', manage_seats: 'allow' })

let host: HTMLDivElement | null = null
afterEach(() => { host?.remove(); host = null })

async function render(node: React.ReactNode) {
  host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => { root.render(node) })
  return host
}

async function openChip(who: Me) {
  useApp.setState({ me: who, inbox: [], sync: null })
  const el = await render(<SyncIndicator />)
  const chip = [...el.querySelectorAll('button')].find((b) => b.getAttribute('aria-expanded') !== null)!
  await act(async () => { chip.click() })
  return [...el.querySelectorAll('button')].map((b) => b.textContent ?? '')
}

describe('role-aware controls', () => {
  it('an employee is offered neither People & seats nor Pair a phone', async () => {
    const labels = await openChip(EMPLOYEE)
    expect(labels.some((t) => t.includes('People & seats'))).toBe(false)
    expect(labels.some((t) => t.includes('Pair a phone'))).toBe(false)
  })

  it('a manager invites, an owner also pairs phones', async () => {
    expect((await openChip(MANAGER)).some((t) => t.includes('People & seats'))).toBe(true)
    host?.remove()
    const owner = await openChip(OWNER)
    expect(owner.some((t) => t.includes('People & seats')) && owner.some((t) => t.includes('Pair a phone'))).toBe(true)
  })

  it('shows the Inbox count only when something waits', async () => {
    useApp.setState({ me: MANAGER, inbox: [{ id: 'i1', kind: 'approval', question: 'Thandi proposes: rename', event_text: null,
      capture_id: null, options: [], author_member_id: 'm3', created_at: new Date().toISOString() }] })
    const el = await render(<SyncIndicator />)
    expect(el.querySelector('[data-inbox-count="1"]')).not.toBeNull()
  })

  it('a branch restricted to owners carries its lock, an open one none', async () => {
    const node = (v: Partial<MapNode>) => ({ id: 'n', type: 'category', kind: 'category', title: 'Financials', parent_id: 'r', depth: 1, counts: {}, ...v }) as MapNode
    const locked = await render(<LockBadge n={node({ visibility: 'owner', eff_level: 1 })} />)
    expect(locked.querySelector('[data-lock="owners"]')?.textContent).toContain('owners')
    const open = await render(<LockBadge n={node({ visibility: 'all', eff_level: 3 })} />)
    expect(open.querySelector('[data-lock]')).toBeNull()
  })

  it('an older brain without /me offers everything, as before roles', () => {
    expect(can(null, 'invite')).toBe('allow')
    expect(can(EMPLOYEE, 'invite')).toBe('refuse')
  })
})
