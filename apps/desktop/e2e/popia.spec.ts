// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The POPIA action audit end to end, against the running stack on the role-aware farm (NC_E2E_WS, default
// roles-showcase; seed_farm_showcase.py --reset-clean --id roles-showcase). Everything made here is a test member,
// removed or erased at the end; nothing real is erased and no retention period or cloud setting is changed.
import { readFileSync } from 'node:fs'
import { expect, type APIRequestContext, type Browser, test } from '@playwright/test'

const BRAIN = process.env.NC_BRAIN_URL ?? 'http://127.0.0.1:8788'
const WS = process.env.NC_E2E_WS ?? 'roles-showcase'
const LOG = new URL('../../../data/brain/logs/api.log', import.meta.url)
const api = `${BRAIN}/api/v1`

async function seatAndInvite(request: APIRequestContext, name: string) {
  await request.post(`${api}/workspaces/${WS}/seats`, { data: { role: 'employee', count: 1 } })
  const inv = await (await request.post(`${api}/workspaces/${WS}/invites`, { data: { name, role: 'employee' } })).json()
  expect(inv.code).toBeTruthy()
  return { code: inv.code as string, link: `notecad://join?${new URLSearchParams({ u: BRAIN, c: inv.code, w: WS })}` }
}

/** A second browser (another device) joins with the invite; every URL it loads is kept. */
async function joinAsDevice(browser: Browser, link: string) {
  const device = await browser.newContext()
  const page = await device.newPage()
  const urls: string[] = []
  page.on('request', (r) => urls.push(r.url()))
  page.on('dialog', (d) => void d.accept())
  await page.goto(`./#join=${encodeURIComponent(link)}`)
  await page.waitForURL((u) => !u.hash.includes('join') && !u.search.includes('join'))
  const token = await page.evaluate(() => localStorage.getItem('notecad.token'))
  expect(token).toMatch(/^nct_/)
  return { device, page, urls, token: token as string, h: { Authorization: `Bearer ${token}` } }
}

test.beforeAll(async ({ request }) => {
  const r = await request.get(`${api}/workspaces/${WS}`)
  test.skip(!r.ok(), `seed it first: seed_farm_showcase.py --reset-clean --id ${WS}`)
})

test('a new member reads the privacy notice before their first note', async ({ browser, request }) => {
  const { link } = await seatAndInvite(request, 'Notice E2E')
  const d = await joinAsDevice(browser, link)
  const me = await (await request.get(`${api}/workspaces/${WS}/me`, { headers: d.h })).json()
  // before reading: no note is taken
  const before = await request.post(`${api}/workspaces/${WS}/captures`, { headers: d.h, data: { text: 'The gate is open' } })
  expect(before.status()).toBe(403)
  expect((await before.json()).detail).toContain('privacy_unread')
  // the notice opens by itself, names the officer and the monitoring, and is read
  await d.page.goto(`./?ws=${WS}&view=map`)
  const dialog = d.page.getByRole('dialog', { name: /Privacy notice/ })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('Information Officer')
  await expect(dialog).toContainText('At work.')
  await expect(dialog).toContainText('nothing leaves it')  // the cloud transfer gate is off on this farm
  await d.page.getByRole('button', { name: 'I have read this' }).click()
  await expect(dialog).toHaveCount(0)
  const after = await request.post(`${api}/workspaces/${WS}/captures`, { headers: d.h, data: { text: 'The gate at the north camp is open' } })
  expect(after.status()).toBe(200)
  await request.post(`${api}/members/${me.member_id}/revoke`)
  await d.device.close()
})

test('erasing a person removes them from the map, search, digest, export and an employee pull', async ({ browser, request }) => {
  const surname = `Erase${Date.now().toString(36)}`  // unique per run: a leftover from another run cannot match
  const name = `Zodwa ${surname}`
  const { link } = await seatAndInvite(request, name)
  const d = await joinAsDevice(browser, link)
  const me = await (await request.get(`${api}/workspaces/${WS}/me`, { headers: d.h })).json()
  await request.post(`${api}/workspaces/${WS}/privacy/ack`, { headers: d.h })
  // the owner files a note naming them; another employee (a watcher) keeps a device copy
  const note = await request.post(`${api}/workspaces/${WS}/captures`, { data: { text: `${name} fixed the gate at the north camp`, wait: true } })
  expect(note.ok()).toBe(true)
  const w = await seatAndInvite(request, 'Watcher E2E')
  const watcher = await joinAsDevice(browser, w.link)
  const wme = await (await request.get(`${api}/workspaces/${WS}/me`, { headers: watcher.h })).json()
  const snap = await (await request.get(`${api}/device/snapshot`, { headers: watcher.h })).json()
  // their own copy first (s23)
  const copy = await (await request.get(`${api}/workspaces/${WS}/subjects/${me.member_id}/export`, { headers: d.h })).json()
  expect(JSON.stringify(copy)).toContain(name)
  // the owner erases them (s24), with the confirmation
  expect((await request.post(`${api}/workspaces/${WS}/subjects/${me.member_id}/erase`)).status()).toBe(400)
  const gone = await (await request.post(`${api}/workspaces/${WS}/subjects/${me.member_id}/erase?confirm=${me.member_id}`)).json()
  expect(gone.erased).toBe(me.member_id)
  for (const path of ['mindmap', 'digest', 'export', 'keyterms', 'tree', 'members']) {
    const body = await (await request.get(`${api}/workspaces/${WS}/${path}`)).text()
    expect(body, path).not.toContain(surname)
  }
  const pull = await (await request.get(`${api}/device/pull?cursor=${encodeURIComponent(snap.cursor)}`, { headers: watcher.h })).text()
  expect(pull).not.toContain(surname)
  expect(pull).toContain('[removed]')  // the watcher's copy is corrected on its next pull
  expect((await request.get(`${api}/workspaces/${WS}/mindmap`, { headers: d.h })).status()).toBe(410)
  await request.post(`${api}/members/${wme.member_id}/revoke`)
  await d.device.close()
  await watcher.device.close()
})

test('no token or invite code in any URL the browser loads, or in the log; the cloud gate is off', async ({ browser, request }) => {
  const { code, link } = await seatAndInvite(request, 'Urls E2E')
  const d = await joinAsDevice(browser, link)
  const me = await (await request.get(`${api}/workspaces/${WS}/me`, { headers: d.h })).json()
  await request.post(`${api}/workspaces/${WS}/privacy/ack`, { headers: d.h })
  await d.page.goto(`./?ws=${WS}&view=map`)
  await d.page.locator('.react-flow__node').first().waitFor()
  await expect.poll(() => d.urls.some((u) => u.includes('/events/stream'))).toBe(true)  // the live stream opened
  const loaded = d.urls.filter((u) => u.startsWith(BRAIN))
  expect(loaded.length).toBeGreaterThan(3)
  for (const u of loaded) {
    expect(u).not.toContain(d.token)
    expect(u).not.toContain('token=')
    expect(u).not.toContain(code)
  }
  const notice = await (await request.get(`${api}/workspaces/${WS}/privacy`)).json()
  expect(notice.cloud.allowed).toBe(false)
  await request.post(`${api}/members/${me.member_id}/revoke`)
  await d.device.close()
  await new Promise((r) => setTimeout(r, 500))  // the log is written as requests finish
  const log = readFileSync(LOG, 'utf8')
  expect(log).not.toContain(d.token)
  expect(log).not.toContain(code)
  expect(log).not.toMatch(/token=nct_|ticket=nck_/)
  expect(log).not.toContain('cloud transfer capture=')  // nothing went to Anthropic or Deepgram
})
