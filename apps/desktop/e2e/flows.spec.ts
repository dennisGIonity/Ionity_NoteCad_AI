// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The owner's flows end to end against the running stack, on the showcase farm (seed_farm_showcase.py --reset-clean):
// typed note + Undo, Inbox placement, node drawer with history and audio, hold Space to talk (a fake microphone plays
// a recorded note), "Record note for this node", the companion, pairing, Sync now with the Edge AI Node, export.
// Every note made here is undone at the end of its test.
import { expect, type Page, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'

const BRAIN = process.env.NC_BRAIN_URL ?? 'http://127.0.0.1:8788'
const EDGE = process.env.NC_EDGE_URL ?? 'http://127.0.0.1:8789'
const WAV = fileURLToPath(new URL('../../../data/samples/showcase/showcase_3.wav', import.meta.url))

test.use({
  launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${WAV}`] },
  permissions: ['microphone'],
})

async function openMap(page: Page) {
  await page.goto('./?ws=showcase&view=map')
  await page.locator('.react-flow__node').first().waitFor()
}

/** The map opens on its main areas: reach a node the way the owner does, through "Go to" (opens its path, selects it). */
async function goTo(page: Page, title: string) {
  await page.getByLabel('Go to a node').fill(title)
  await page.getByLabel('Go to a node').press('Enter')
  await expect(page.locator(`.react-flow__node[aria-label="${title}"]`)).toHaveAttribute('aria-selected', 'true')
  await page.locator('body').click({ position: { x: 2, y: 400 } }).catch(() => undefined)
  await page.locator(`.react-flow__node[aria-label="${title}"]`).click()
}

async function latestCaptures(page: Page, n = 5) {
  const r = await page.request.get(`${BRAIN}/api/v1/workspaces/showcase/export`)
  const caps = ((await r.json()).tables?.captures ?? []) as { id: string; created_at: string; anchor_node_id: string | null; source: string; state: string }[]
  return caps.sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, n)
}

async function undo(page: Page, id: string) {
  await page.request.post(`${BRAIN}/api/v1/captures/${id}/undo`)
}

async function nodeId(page: Page, title: string) {
  const mm = await (await page.request.get(`${BRAIN}/api/v1/workspaces/showcase/mindmap`)).json()
  return (mm.nodes as { id: string; title: string }[]).find((n) => n.title === title)!.id
}

test('typed note lands, then Undo takes it back', async ({ page }) => {
  await openMap(page)
  await page.getByRole('button', { name: 'Type instead' }).click()
  await page.getByLabel('Type a note').fill('Ask Thabo to grease John Deere 9550 number 2 before Friday')
  await page.getByLabel('Type a note').press('Enter')
  await expect(page.getByText(/Updated .*John Deere 9550 #2/).first()).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: /^Undo$/ }).click()
  await expect(page.getByText('Undone: nothing from this note is on the map')).toBeVisible()
})

test('a note the brain is unsure of is placed from the Inbox in one tap', async ({ page }) => {
  await openMap(page)
  const before = (await latestCaptures(page, 1))[0]?.id
  await page.getByRole('button', { name: 'Type instead' }).click()
  await page.getByLabel('Type a note').fill('Sort out the stuff')
  await page.getByLabel('Type a note').press('Enter')
  const pill = page.locator('[data-inbox-option]').first()
  await expect(pill).toBeVisible({ timeout: 30_000 })
  await pill.click()
  await expect(page.locator('[data-inbox-option]')).toHaveCount(0, { timeout: 10_000 })
  const cap = (await latestCaptures(page, 1))[0]
  expect(cap.id).not.toBe(before)
  await undo(page, cap.id)
})

test('node drawer: tasks, history, the companion', async ({ page }) => {
  const r = await (await page.request.post(`${BRAIN}/api/v1/workspaces/showcase/capture`, {
    data: { text: 'North borehole pump pressure is low again', wait: true } })).json()
  await openMap(page)
  await goTo(page, 'North Borehole Pump')
  const drawer = page.getByRole('complementary')
  await expect(drawer.getByText('North Borehole Pump').first()).toBeVisible()
  await drawer.getByRole('tab', { name: /History/ }).click()
  await expect(drawer.locator('li').first()).toBeVisible()
  await drawer.getByLabel('Ask the companion').fill('What is open on this pump?')
  await drawer.getByRole('button', { name: 'Ask' }).click()
  await expect(drawer.locator('[data-companion-reply]')).toBeVisible({ timeout: 60_000 })
  await undo(page, r.capture_id)
})

test('hold Space to talk: the selected node is the context, and the drawer plays the recording', async ({ page }) => {
  await openMap(page)
  const pump = await nodeId(page, 'North Borehole Pump')
  await goTo(page, 'North Borehole Pump')
  await page.keyboard.down('Space')
  await page.waitForTimeout(4500)
  await page.keyboard.up('Space')
  await expect.poll(async () => (await latestCaptures(page, 1))[0], { timeout: 60_000 })
    .toMatchObject({ anchor_node_id: pump })
  const cap = (await latestCaptures(page, 1))[0]
  await expect.poll(async () => (await latestCaptures(page, 1))[0].state, { timeout: 60_000 }).toMatch(/applied|needs_review/)
  const audio = await page.request.get(`${BRAIN}/api/v1/captures/${cap.id}/audio`)
  expect(audio.status()).toBe(200)
  expect((await audio.body()).length).toBeGreaterThan(1000)
  const drawer = page.getByRole('complementary')
  await drawer.getByRole('tab', { name: /History/ }).click()
  await expect(drawer.getByLabel('Play the voice note').first()).toBeVisible({ timeout: 15_000 })
  await undo(page, cap.id)
})

test('"Record note for this node" anchors the recording', async ({ page }) => {
  await openMap(page)
  const jd = await nodeId(page, 'John Deere 9550 #1')
  await goTo(page, 'John Deere 9550 #1')
  const drawer = page.getByRole('complementary')
  await drawer.getByRole('button', { name: /Record note for this node/ }).click()
  await page.waitForTimeout(4000)
  await drawer.getByRole('button', { name: /Stop and send/ }).click()
  await expect.poll(async () => (await latestCaptures(page, 1))[0], { timeout: 60_000 }).toMatchObject({ anchor_node_id: jd })
  await undo(page, (await latestCaptures(page, 1))[0].id)
})

test('pairing dialog opens and Escape closes only the dialog', async ({ page }) => {
  await openMap(page)
  await goTo(page, 'North Borehole Pump')
  await page.getByTitle('Local store and sync status').click()
  await page.getByRole('button', { name: /Pair a phone/ }).click()
  await expect(page.getByRole('dialog', { name: 'Pair a phone' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'Pair a phone' })).toHaveCount(0)
  await expect(page.getByRole('complementary').getByText('North Borehole Pump').first()).toBeVisible()  // still selected
})

test('Sync now with the Edge AI Node leaves nothing unsynced on either side', async ({ page }) => {
  const st = await (await page.request.get(`${BRAIN}/api/v1/sync/status`)).json()
  test.skip(!st.target, 'start with -EdgeNode (or set NC_BRAIN_SYNC_TARGET)')
  await openMap(page)
  await page.getByTitle('Local store and sync status').click()
  await page.getByRole('button', { name: /Sync now/ }).click()
  await expect.poll(async () => (await (await page.request.get(`${BRAIN}/api/v1/sync/status`)).json()).last_error, { timeout: 30_000 }).toBeNull()
  const res = await (await page.request.post(`${BRAIN}/api/v1/sync/now`)).json()
  expect(res.ok).toBe(true)
  for (const base of [BRAIN, EDGE]) {
    const s = await (await page.request.get(`${base}/api/v1/workspaces/showcase/sync`)).json()
    expect(s.pending.sync_events, base).toBe(0)
  }
})

test('workspace export is the whole farm as JSON', async ({ page }) => {
  const r = await page.request.get(`${BRAIN}/api/v1/workspaces/showcase/export`)
  expect(r.status()).toBe(200)
  const j = await r.json()
  expect(j.workspace.id).toBe('showcase')
  expect(j.tables.nodes.length).toBeGreaterThan(20)
})
