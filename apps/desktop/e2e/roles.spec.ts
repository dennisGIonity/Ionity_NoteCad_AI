// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// ADR 0014 end to end, against the running stack on the showcase farm (seed_farm_showcase.py --reset-clean): the owner
// invites an employee; the employee joins from a second browser context (another device, with its own token) and
// never sees Financials, on the map, in the drawer, through the API or in the live events. Removing them stops the
// device at once. The member made here is removed at the end.
import { expect, test } from '@playwright/test'

const BRAIN = process.env.NC_BRAIN_URL ?? 'http://127.0.0.1:8788'
const WS = process.env.NC_E2E_WS ?? 'showcase'

test('an employee who joins never sees Financials', async ({ browser, page, request }) => {
  const map = await (await request.get(`${BRAIN}/api/v1/workspaces/${WS}/mindmap`)).text()
  test.skip(!map.includes('Financials'), `seed it first: seed_farm_showcase.py --reset-clean (or --id ${WS}); NC_E2E_WS picks the workspace`)
  // the owner, on this PC: Financials is on their map, with its lock
  await page.goto(`./?ws=${WS}&view=map`)
  await page.locator('.react-flow__node').first().waitFor()
  await expect(page.locator('.react-flow__node[aria-label="Financials"]')).toBeVisible()
  await expect(page.locator('.react-flow__node[aria-label="Financials"] [data-lock="owners"]')).toBeVisible()

  // the owner makes an invite (the API the People & seats panel uses)
  const inv = await (await request.post(`${BRAIN}/api/v1/workspaces/${WS}/invites`,
    { data: { name: 'Zanele E2E', role: 'employee' } })).json()
  expect(inv.code).toBeTruthy()
  const link = `notecad://join?${new URLSearchParams({ u: BRAIN, c: inv.code, w: WS })}`

  // another device: a fresh browser context opens the invite, confirms what the brain says, and joins
  const device = await browser.newContext()
  const phone = await device.newPage()
  const seen: string[] = []
  phone.on('dialog', (d) => { seen.push(d.message()); void d.accept() })
  const sent: string[] = []
  phone.on('response', async (r) => { if (r.url().includes('/mindmap')) sent.push(await r.text().catch(() => '')) })
  await phone.goto(`./#join=${encodeURIComponent(link)}`)
  await phone.waitForURL((u) => !u.hash.includes('join') && !u.search.includes('join'))
  expect(seen[0]).toContain('as employee')
  const token = await phone.evaluate(() => localStorage.getItem('notecad.token'))
  expect(token).toMatch(/^nct_/)
  // the privacy notice (POPIA) waits for the new member to read it
  await phone.goto(`./?ws=${WS}&view=map`)
  await expect(phone.getByRole('dialog', { name: /Privacy notice/ })).toBeVisible()
  await phone.getByRole('button', { name: 'I have read this' }).click()
  await expect(phone.getByRole('dialog', { name: /Privacy notice/ })).toHaveCount(0)

  await phone.goto(`./?ws=${WS}&view=map`)
  await phone.locator('.react-flow__node').first().waitFor()
  await phone.getByRole('button', { name: 'Expand all' }).click()
  await expect.poll(() => sent.join('')).toContain('Field South 704')  // the farm reached the device (cards draw on screen only)
  await expect(phone.locator('.react-flow__node[aria-label="Financials"]')).toHaveCount(0)
  await expect(phone.locator('body')).not.toContainText('Financials')
  await expect(phone.locator('body')).not.toContainText('Bank Loan')
  expect(sent.join('')).not.toContain('Financials')  // nothing restricted even in what the app was sent

  // the same token through the API: map, digest, export, search words
  const h = { Authorization: `Bearer ${token}` }
  for (const path of ['mindmap', 'digest', 'export', 'keyterms', 'tree']) {
    const body = await (await request.get(`${BRAIN}/api/v1/workspaces/${WS}/${path}`, { headers: h })).text()
    expect(body, path).not.toContain('Financials')
    expect(body, path).not.toContain('Bank Loan')
  }
  const me = await (await request.get(`${BRAIN}/api/v1/workspaces/${WS}/me`, { headers: h })).json()
  expect(me.role).toBe('employee')

  // the owner removes them: the device is refused at once, and told to wipe
  expect((await request.post(`${BRAIN}/api/v1/members/${me.member_id}/revoke`)).ok()).toBe(true)
  const after = await request.get(`${BRAIN}/api/v1/workspaces/${WS}/mindmap`, { headers: h })
  expect(after.status()).toBe(410)
  expect((await after.json()).detail.wipe).toBe(true)
  await device.close()
})
