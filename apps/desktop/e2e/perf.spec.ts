// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Map performance: frames while panning the 2,000-node synthetic farm (tools/seed_synthetic_farm.py) and the time
// from a capture's `action.applied` event to the map redrawing with the change. Numbers go to data/desktop/perf.json.
import { expect, test, type Page } from '@playwright/test'
import { appendFileSync, mkdirSync } from 'node:fs'

const BRAIN = process.env.NC_BRAIN_URL ?? 'http://127.0.0.1:8788'
const OUT = '../../data/desktop/perf.jsonl'

function record(name: string, value: unknown) {
  mkdirSync('../../data/desktop', { recursive: true })
  appendFileSync(OUT, `${JSON.stringify({ at: new Date().toISOString(), name, value })}\n`)
  console.log(name, JSON.stringify(value))
}

async function openMap(page: Page, ws: string) {
  await page.addInitScript(() => { try { localStorage.clear(); localStorage.setItem('notecad.privacy.later', '99999999999999') } catch { /* */ } })
  const t = Date.now()
  await page.goto(`./?ws=${ws}&view=map`)
  await page.locator('.react-flow__node').first().waitFor({ timeout: 60_000 })
  await page.waitForTimeout(800)
  return Date.now() - t
}

async function panFps(page: Page, ms = 3000) {
  const box = (await page.locator('.react-flow__pane').boundingBox())!
  await page.evaluate(() => {
    const w = window as unknown as { __frames: number[]; __on: boolean }
    w.__frames = []
    w.__on = true
    const tick = (t: number) => { if (!w.__on) return; w.__frames.push(t); requestAnimationFrame(tick) }
    requestAnimationFrame(tick)
  })
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2
  const start = Date.now()
  let dir = 1
  while (Date.now() - start < ms) {
    await page.mouse.move(cx, cy)
    await page.mouse.down()
    for (let i = 0; i < 20; i++) await page.mouse.move(cx + dir * i * 15, cy + dir * i * 6)
    await page.mouse.up()
    dir = -dir
  }
  const frames = await page.evaluate(() => {
    const w = window as unknown as { __frames: number[]; __on: boolean }
    w.__on = false
    return w.__frames
  })
  const gaps = frames.slice(1).map((t, i) => t - frames[i])
  const secs = (frames[frames.length - 1] - frames[0]) / 1000
  const sorted = [...gaps].sort((a, b) => a - b)
  return {
    fps: +(gaps.length / secs).toFixed(1),
    p95_frame_ms: +sorted[Math.floor(sorted.length * 0.95)].toFixed(1),
    long_frames: gaps.filter((g) => g > 34).length,
    rendered_nodes: await page.locator('.react-flow__node').count(),
  }
}

test('2,000-node farm: first draw and panning', async ({ page }) => {
  const res = await page.request.get(`${BRAIN}/api/v1/workspaces/perf-2000/mindmap`)
  test.skip(res.status() !== 200, 'no perf-2000 workspace: run tools/seed_synthetic_farm.py')
  const load = await openMap(page, 'perf-2000')
  const fps = await panFps(page)
  record('perf-2000', { first_draw_ms: load, ...fps })
  expect(fps.fps).toBeGreaterThan(5)
})

test('capture to map: time from action.applied to the redraw', async ({ page }) => {
  await openMap(page, 'showcase')
  await page.evaluate((brain) => {
    const w = window as unknown as { __mut: number[]; __applied: number | null; __es: EventSource }
    w.__mut = []
    w.__applied = null
    new MutationObserver(() => w.__mut.push(performance.now()))
      .observe(document.querySelector('.react-flow__nodes')!, { subtree: true, childList: true, characterData: true, attributes: true })
    fetch(`${brain}/api/v1/workspaces/showcase/mindmap`).then((r) => r.json()).then((m) => {
      w.__es = new EventSource(`${brain}/api/v1/workspaces/showcase/events/stream?last_event_id=${m.cursor}`)
      w.__es.addEventListener('action.applied', () => { if (w.__applied == null) w.__applied = performance.now() })
    })
  }, BRAIN)
  await page.waitForTimeout(500)
  const cap = await (await page.request.post(`${BRAIN}/api/v1/workspaces/showcase/capture`, {
    multipart: { text: 'The North borehole pump is leaking', wait: 'false' },
  })).json()
  await expect.poll(() => page.evaluate(() => (window as unknown as { __applied: number | null }).__applied), { timeout: 60_000 }).not.toBeNull()
  await page.waitForTimeout(2500)
  const v = await page.evaluate(() => {
    const w = window as unknown as { __mut: number[]; __applied: number }
    const maps = performance.getEntriesByType('resource').filter((e) => e.name.includes('/mindmap') && e.startTime > w.__applied) as PerformanceResourceTiming[]
    const resp = maps.length ? maps[0].responseEnd : null
    const redraw = resp == null ? null : w.__mut.find((t) => t > resp) ?? null
    return { fetch_start_ms: maps.length ? +(maps[0].startTime - w.__applied).toFixed(0) : null,
      response_ms: resp == null ? null : +(resp - w.__applied).toFixed(0),
      redraw_ms: redraw == null ? null : +(redraw - w.__applied).toFixed(0) }
  })
  record('capture-to-map', v)
  if (cap.capture_id ?? cap.id) await page.request.post(`${BRAIN}/api/v1/captures/${cap.capture_id ?? cap.id}/undo`)
  expect(v.redraw_ms).not.toBeNull()
})
