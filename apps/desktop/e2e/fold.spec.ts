// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The foldable mind map (ADR 0013), on the showcase farm and the 2,000-node synthetic farm. Screenshots of the flow
// go to docs/media (NC_SHOTS=1).
import { expect, type Page, test } from '@playwright/test'
import { appendFileSync, mkdirSync } from 'node:fs'

const BRAIN = process.env.NC_BRAIN_URL ?? 'http://127.0.0.1:8788'
const SHOTS = process.env.NC_SHOTS ? '../../docs/media' : null
// the order of the flow, so files sort into a sequence whichever test runs first
const ORDER = ["main-areas", "one-branch", "level-2", "expand-all", "context-menu", "badge-after-note", "toast-open-reveals", "keyboard", "phone-width", "light-mode"]

async function snap(page: Page, name: string) {
  if (!SHOTS) return
  mkdirSync(SHOTS, { recursive: true })
  await page.screenshot({ path: `${SHOTS}/fold-${String(ORDER.indexOf(name) + 1).padStart(2, '0')}-${name}.png` })
}

const items = (page: Page) => page.locator('.react-flow__node[role="treeitem"]')
const item = (page: Page, title: string) => page.locator(`.react-flow__node[role="treeitem"][aria-label="${title}"]`)
const levelText = (page: Page) => page.locator('[data-fold-level]')

async function open(page: Page, ws = 'showcase', fresh = true) {
  if (fresh) await page.addInitScript(() => { try { if (!sessionStorage.getItem('kept')) { localStorage.clear(); localStorage.setItem('notecad.privacy.later', '99999999999999'); sessionStorage.setItem('kept', '1') } } catch { /* */ } })
  await page.goto(`./?ws=${ws}&view=map`)
  await items(page).first().waitFor()
  await page.waitForTimeout(400)
}

async function levels(page: Page) {
  return items(page).evaluateAll((els) => els.map((e) => Number(e.getAttribute('aria-level'))))
}

test.describe('fold on the showcase farm', () => {
  test('the map opens on the main areas', async ({ page }) => {
    await open(page)
    expect(Math.max(...await levels(page))).toBe(2)  // the farm (level 1) and its categories (level 2)
    await expect(levelText(page)).toHaveText(/Level 1/)
    await expect(item(page, 'Vehicles')).toHaveAttribute('aria-expanded', 'false')
    await expect(item(page, 'Vehicles').locator('[data-fold-badge]')).toHaveText(/^\+\d+/)
    await expect(page.locator('[role="tree"]')).toBeVisible()
    await snap(page, 'main-areas')
  })

  test('the chevron opens one node, one level', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: /Show what is under Vehicles/ }).click()
    await expect(item(page, 'Tractors')).toBeVisible()
    await expect(item(page, 'John Deere 9550 #1')).toHaveCount(0)  // only the next level
    await expect(item(page, 'Field South 704')).toHaveCount(0)     // other branches stay folded
    await expect(item(page, 'Vehicles')).toHaveAttribute('aria-expanded', 'true')
    await snap(page, 'one-branch')
  })

  test('expand one level, expand all, collapse all, main areas', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: 'Expand one level' }).click()
    await expect(levelText(page)).toHaveText(/Level 2/)
    expect(Math.max(...await levels(page))).toBe(3)
    await snap(page, 'level-2')
    await page.getByRole('button', { name: 'Expand all' }).click()
    await expect(levelText(page)).toHaveText(/Level 3 \/ 3/)
    await page.getByRole('button', { name: 'Fit to screen' }).click()
    await page.waitForTimeout(700)  // only cards inside the viewport are in the DOM
    await expect(item(page, 'John Deere 9550 #1')).toHaveCount(1)
    await snap(page, 'expand-all')
    await page.getByRole('button', { name: 'Collapse all' }).click()
    await expect(items(page)).toHaveCount(1)
    await expect(item(page, 'Wabakipi Farm').locator('[data-fold-badge]')).toHaveText(/^\+\d+/)
    await page.getByRole('button', { name: 'Main areas' }).click()
    await expect(levelText(page)).toHaveText(/Level 1/)
  })

  test('shift+click opens the whole branch; the context menu folds it again', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: /Show what is under Vehicles/ }).click({ modifiers: ['Shift'] })
    await expect(item(page, 'Vehicles')).toHaveAttribute('aria-expanded', 'true')
    await expect(item(page, 'Tractors')).toHaveAttribute('aria-expanded', 'true')  // the whole branch
    await item(page, 'Vehicles').click({ button: 'right' })
    await page.getByRole('menuitem', { name: 'Collapse all below' }).click()
    await expect(item(page, 'Tractors')).toHaveCount(0)
    await item(page, 'Fields').click({ button: 'right' })
    await snap(page, 'context-menu')
    await page.getByRole('menuitem', { name: 'Focus this branch' }).click()
    await expect(item(page, 'Fields')).toBeVisible()
  })

  test('a reload brings back the fold state', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: /Show what is under Fields/ }).click()
    await expect(item(page, 'South Block')).toBeVisible()
    await page.reload()
    await items(page).first().waitFor()
    await expect(item(page, 'South Block')).toBeVisible()
    await expect(item(page, 'Tractors')).toHaveCount(0)
  })

  test('a note into a folded branch updates the badge and pulses the card, without unfolding; Open reveals it', async ({ page }) => {
    await open(page)
    const water = item(page, 'Water')
    const badge = water.locator('[data-fold-badge]')
    const before = await badge.textContent()
    const tasksBefore = Number((before?.match(/(\d+) task/) ?? [0, 0])[1])
    const cap = await (await page.request.post(`${BRAIN}/api/v1/workspaces/showcase/capture`, {
      multipart: { text: 'Ask Thabo to service the South borehole pump on Friday', wait: 'false' } })).json()
    await expect(badge).toHaveText(new RegExp(`${tasksBefore + 1} task`), { timeout: 30_000 })
    await expect(water.locator('.nc-pulse')).toHaveCount(1)
    await expect(item(page, 'South Borehole Pump')).toHaveCount(0)  // still folded
    await snap(page, 'badge-after-note')
    await page.getByRole('button', { name: /South Borehole Pump/ }).first().click()  // the toast's Open
    await expect(item(page, 'South Borehole Pump')).toBeVisible()
    await expect(item(page, 'South Borehole Pump')).toHaveAttribute('aria-selected', 'true')
    await expect(item(page, 'Tractors')).toHaveCount(0)  // only the path was opened
    await snap(page, 'toast-open-reveals')
    await page.request.post(`${BRAIN}/api/v1/captures/${cap.capture_id}/undo`)
  })

  test('keyboard only: arrows move and fold, Shift+arrows fold branches, Enter opens the drawer', async ({ page }) => {
    await open(page)
    await item(page, 'Wabakipi Farm').focus()
    await page.keyboard.press('ArrowDown')
    await expect(item(page, 'Admin')).toBeFocused()
    for (let i = 0; i < 10; i++) {
      if (await item(page, 'Vehicles').evaluate((e) => e === document.activeElement)) break
      await page.keyboard.press('ArrowDown')
    }
    await expect(item(page, 'Vehicles')).toBeFocused()
    await page.keyboard.press('ArrowRight')  // open
    await expect(item(page, 'Vehicles')).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('ArrowRight')  // first child
    await expect(item(page, 'Bakkies')).toBeFocused()
    await page.keyboard.press('ArrowLeft')   // to the parent (Bakkies is folded)
    await expect(item(page, 'Vehicles')).toBeFocused()
    await page.keyboard.press('Shift+ArrowRight')
    await expect(item(page, 'Tractors')).toHaveAttribute('aria-expanded', 'true')
    await page.keyboard.press('Shift+ArrowLeft')
    await expect(item(page, 'Tractors')).toHaveCount(0)
    await page.keyboard.press('Enter')
    await expect(page.getByRole('complementary').getByText('Vehicles').first()).toBeVisible()
    await snap(page, 'keyboard')
    // "/" opens the typed note; it is not a tree key
    await item(page, 'Vehicles').focus()
    await page.keyboard.press('/')
    await expect(page.getByLabel('Type a note')).toBeFocused()
  })

  test('reduced motion: nothing animates', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await open(page)
    await page.evaluate(() => {
      const w = window as unknown as { __anim: number }
      w.__anim = 0
      new MutationObserver(() => { if (document.querySelector('.react-flow__node.nc-anim')) w.__anim++ })
        .observe(document.body, { subtree: true, attributes: true, childList: true })
    })
    await page.getByRole('button', { name: /Show what is under Vehicles/ }).click()
    await expect(item(page, 'Tractors')).toBeVisible()
    expect(await page.evaluate(() => (window as unknown as { __anim: number }).__anim)).toBe(0)
  })

  test('with motion, children grow out of the parent and the clicked node stays still', async ({ page }) => {
    await open(page)
    const box = async () => (await item(page, 'Fields').boundingBox())!
    const before = await box()
    let animated = false
    page.on('console', () => undefined)
    const watch = page.evaluate(() => new Promise<boolean>((r) => {
      const t = setTimeout(() => r(false), 1500)
      new MutationObserver((_, o) => { if (document.querySelector('.react-flow__node.nc-anim')) { clearTimeout(t); o.disconnect(); r(true) } })
        .observe(document.body, { subtree: true, attributes: true, childList: true })
    }))
    await page.getByRole('button', { name: /Show what is under Fields/ }).click()
    animated = await watch
    await page.waitForTimeout(500)
    const after = await box()
    expect(animated).toBe(true)
    expect(Math.abs(after.y - before.y)).toBeLessThan(3)
    expect(Math.abs(after.x - before.x)).toBeLessThan(3)
  })

  test('phone width: the map and its fold controls work', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await open(page)
    await expect(page.getByRole('button', { name: 'Expand one level' })).toBeVisible()
    await page.getByRole('button', { name: 'Expand one level' }).click()
    await expect(levelText(page)).toHaveText(/Level 2/)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(overflow).toBe(false)
    await snap(page, 'phone-width')
  })

  test('light mode renders readable cards', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' })
    await open(page)
    const [fg, bg] = await item(page, 'Vehicles').locator('.nc-card').evaluate((e) => {
      const rgb = (css: string) => {  // any CSS colour (oklab, color-mix ...) to sRGB through a canvas
        const c = document.createElement('canvas').getContext('2d')!
        c.fillStyle = '#fff'; c.fillRect(0, 0, 1, 1); c.fillStyle = css; c.fillRect(0, 0, 1, 1)
        const d = c.getImageData(0, 0, 1, 1).data
        return 0.2126 * d[0] + 0.7152 * d[1] + 0.0722 * d[2]
      }
      return [rgb(getComputedStyle(e.querySelector('.font-semibold')!).color), rgb(getComputedStyle(e).backgroundColor)]
    })
    expect(bg - fg).toBeGreaterThan(120)  // dark text on a light card
    await snap(page, 'light-mode')
  })
})

test.describe('fold on 2,000 nodes', () => {
  test('Expand all and Collapse all settle in under 300 ms; panning stays smooth', async ({ page }) => {
    const res = await page.request.get(`${BRAIN}/api/v1/workspaces/perf-2000/mindmap`)
    test.skip(res.status() !== 200, 'no perf-2000 workspace: run tools/seed_synthetic_farm.py')
    await open(page, 'perf-2000')
    const timed = async (label: string, level: RegExp) => page.evaluate(async ([name, re]) => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === name)!
      const t = performance.now()
      btn.click()
      const want = new RegExp(re)
      await new Promise<void>((r) => {
        const tick = () => (want.test(document.querySelector('[data-fold-level]')?.textContent ?? '') ? r() : requestAnimationFrame(tick))
        tick()
      })
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))  // painted
      return performance.now() - t
    }, [label, level.source] as const)
    const max = Number((await levelText(page).textContent())!.split('/')[1])
    const expand = await timed('Expand all', new RegExp(`Level ${max} /`))
    await page.waitForTimeout(800)
    // the display's own frame rate here (laptop panels switch between 60 and 144 Hz): the bar panning is measured against
    const idle = await page.evaluate(() => new Promise<number>((r) => {
      const f: number[] = []
      const tick = (t: number) => { f.push(t); if (t - f[0] < 1000) requestAnimationFrame(tick); else r((f.length - 1) / ((f[f.length - 1] - f[0]) / 1000)) }
      requestAnimationFrame(tick)
    }))
    const box = (await page.locator('.react-flow__pane').boundingBox())!
    await page.evaluate(() => {
      const w = window as unknown as { __f: number[]; __on: boolean }
      w.__f = []; w.__on = true
      const tick = (t: number) => { if (!w.__on) return; w.__f.push(t); requestAnimationFrame(tick) }
      requestAnimationFrame(tick)
    })
    const cx = box.x + box.width / 2, cy = box.y + box.height / 2
    for (let k = 0; k < 6; k++) {
      await page.mouse.move(cx, cy); await page.mouse.down()
      for (let i = 0; i < 20; i++) await page.mouse.move(cx + (k % 2 ? -1 : 1) * i * 15, cy + i * 4)
      await page.mouse.up()
    }
    const frames = await page.evaluate(() => { const w = window as unknown as { __f: number[]; __on: boolean }; w.__on = false; return w.__f })
    const gaps = frames.slice(1).map((t, i) => t - frames[i]).sort((a, b) => a - b)
    const fps = gaps.length / ((frames[frames.length - 1] - frames[0]) / 1000)
    const collapse = await timed('Collapse all', /Level 0/)
    const rendered = await items(page).count()
    const long = gaps.filter((g) => g > 34).length
    const out = { expand_all_ms: Math.round(expand), collapse_all_ms: Math.round(collapse), display_fps: +idle.toFixed(1),
      pan_fps_expanded: +fps.toFixed(1), long_frames: long,
      p95_frame_ms: +gaps[Math.floor(gaps.length * 0.95)].toFixed(1), rendered_after_collapse: rendered }
    mkdirSync('../../data/desktop', { recursive: true })
    appendFileSync('../../data/desktop/perf.jsonl', `${JSON.stringify({ at: new Date().toISOString(), name: 'fold-2000', value: out })}\n`)
    console.log('fold-2000', JSON.stringify(out))
    expect(expand).toBeLessThan(300)
    expect(collapse).toBeLessThan(300)
    expect(fps).toBeGreaterThan(Math.min(55, idle * 0.85))  // 60 fps on a 60 Hz panel, allowing for input pacing
    expect(long).toBe(0)
  })
})
