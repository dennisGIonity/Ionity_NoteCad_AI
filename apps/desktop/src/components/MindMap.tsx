// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The whole map, live and foldable. The owner starts from the main areas and opens the tree a level, a branch or
// all at once (ADR 0013). Folding decides which cards exist; zoom only decides how much a card shows. When a note
// lands inside a folded branch nothing unfolds: the nearest card on screen pulses and its badge counts the change.
import * as F from '@notecad/core/fold'
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow, useStore,
  type Node, type NodeMouseHandler,
} from '@xyflow/react'
import {
  AlertTriangle, Bell, ChevronsDownUp, ChevronsUpDown, Crosshair, Inbox, LayoutGrid, ListTodo, Loader2, Maximize2, Minus,
  Network, Orbit, Plus, Search, ZoomIn, ZoomOut,
} from 'lucide-react'
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { buildEdges, buildNodes, type CardData, layoutEngine, layoutPositions, type Pos } from '../lib/layout'
import { useApp } from '../lib/store'
import { cls, statusColor } from '../lib/ui'
import { isTiny, nodeTypes } from './nodes/Cards'

const ANIM_MS = 300

/** New node objects keep what React Flow measured last time, so a rebuild does not re-measure (or hide) cards. */
function keep(cur: Node<CardData>[], next: Node<CardData>[]): Node<CardData>[] {
  const was = new Map(cur.map((n) => [n.id, n.measured]))
  return next.map((n) => { const m = was.get(n.id); return m ? { ...n, measured: m } : n })
}
const ANIM_MAX = 150
const MINIMAP_MAX = 400
const FIT_PAD = { top: '84px', bottom: '120px', left: '32px', right: '32px' } as const  // room for the toolbar and the HUD  // more cards than this appear or vanish at once: no animation (it would only cost time)

function reducedMotion() {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches } catch { return false }
}

function FoldControls() {
  const fold = useApp((s) => s.fold)
  const map = useApp((s) => s.map)
  const tree = useMemo(() => (map ? useApp.getState().foldTree() : null), [map])
  if (!tree) return null
  const lvl = F.level(tree.idx, fold)
  const go = (next: F.FoldState) => useApp.getState().setFold(next)
  const btn = 'grid size-7 place-items-center rounded-md text-slate-300 hover:bg-white/10 hover:text-white disabled:opacity-30'
  return (
    // biome-ignore lint/a11y/useSemanticElements: a toolbar group, not a form fieldset
    <div className="flex items-center gap-0.5 rounded-lg bg-white/5 p-0.5" role="group" aria-label="Fold the map">
      <button type="button" className={cls(btn, 'w-auto px-2 text-xs')} onClick={() => go(F.mainAreas())} aria-label="Main areas" title="Main areas: the farm and its top-level categories">
        <LayoutGrid className="mr-1 size-3.5" />Main areas
      </button>
      <button type="button" className={btn} onClick={() => go(F.collapseLevel(tree.idx, fold))} disabled={lvl === 0} aria-label="Collapse one level" title="Collapse one level"><Minus className="size-4" /></button>
      <span className="min-w-[4.5rem] text-center text-xs tabular-nums text-slate-200" aria-live="polite" data-fold-level={lvl}>Level {lvl} / {tree.idx.maxDepth}</span>
      <button type="button" className={btn} onClick={() => go(F.expandLevel(tree.idx, fold))} disabled={lvl >= tree.idx.maxDepth} aria-label="Expand one level" title="Expand one level"><Plus className="size-4" /></button>
      <button type="button" className={btn} onClick={() => go(F.expandAll(tree.idx))} aria-label="Expand all" title="Expand all"><ChevronsUpDown className="size-4" /></button>
      <button type="button" className={btn} onClick={() => go(F.collapseAll(tree.idx))} aria-label="Collapse all" title="Collapse all"><ChevronsDownUp className="size-4" /></button>
    </div>
  )
}

function FindNode() {
  const map = useApp((s) => s.map)
  const [q, setQ] = useState('')
  const titles = useMemo(() => (map ? [...new Set(map.nodes.filter((n) => n.type !== 'task' && !n.virtual).map((n) => n.title))].slice(0, 3000) : []), [map])
  const find = () => {
    const t = q.trim().toLowerCase()
    if (!t || !map) return
    const hit = map.nodes.find((n) => n.title.toLowerCase() === t) ?? map.nodes.find((n) => n.type !== 'task' && n.title.toLowerCase().includes(t))
    if (hit) { useApp.getState().goTo(hit.id); setQ('') }
  }
  return (
    <form aria-label="Find on the map" className="flex items-center gap-1 rounded-lg bg-white/5 px-2" onSubmit={(e) => { e.preventDefault(); find() }}>
      <Search className="size-3.5 text-slate-400" />
      <input value={q} onChange={(e) => setQ(e.target.value)} list="nc-node-titles" placeholder="Go to…" aria-label="Go to a node"
        className="w-28 bg-transparent py-1 text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none" />
      <datalist id="nc-node-titles">{titles.map((t) => <option key={t} value={t} />)}</datalist>
    </form>
  )
}

function Toolbar() {
  const map = useApp((s) => s.map)
  const layout = useApp((s) => s.layout)
  const workspaces = useApp((s) => s.workspaces)
  const ws = useApp((s) => s.ws)
  const { fitView, zoomIn, zoomOut } = useReactFlow()
  if (!map) return null
  const s = map.stats
  const { setLayout, switchWorkspace } = useApp.getState()
  const btn = 'grid size-8 place-items-center rounded-lg text-slate-300 hover:bg-white/10 hover:text-white'
  return (
    <div className="nc-glass pointer-events-auto absolute left-4 right-4 top-4 z-10 flex flex-wrap items-center gap-2 rounded-2xl px-3 py-2 sm:right-auto">
      {workspaces.length > 1 ? (
        <select value={ws} onChange={(e) => void switchWorkspace(e.target.value)} aria-label="Workspace"
          className="max-w-52 truncate rounded-lg bg-transparent py-1 pr-1 text-sm font-semibold text-slate-100 focus:outline-none">
          {workspaces.map((w) => <option key={w.id} value={w.id} className="bg-slate-900">{w.name}</option>)}
        </select>
      ) : <span className="text-sm font-semibold text-slate-100">{map.workspace.name}</span>}
      <div className="mx-1 hidden h-5 w-px bg-white/10 sm:block" />
      <span title="Open alerts" className="flex items-center gap-1 text-xs text-rose-200"><AlertTriangle className="size-3.5" />{s.open_alerts}</span>
      <span title="Open tasks" className="flex items-center gap-1 text-xs text-sky-200"><ListTodo className="size-3.5" />{s.open_tasks}</span>
      <span title="Overdue" className="flex items-center gap-1 text-xs text-amber-200"><Bell className="size-3.5" />{s.overdue_tasks}</span>
      {s.inbox > 0 && <span title="Waiting in the Inbox" className="flex items-center gap-1 text-xs text-amber-200"><Inbox className="size-3.5" />{s.inbox}</span>}
      <div className="mx-1 hidden h-5 w-px bg-white/10 sm:block" />
      <FoldControls />
      <FindNode />
      {/* biome-ignore lint/a11y/useSemanticElements: a segmented control, not a form fieldset */}
      <div className="flex rounded-lg bg-white/5 p-0.5" role="group" aria-label="Layout">
        <button type="button" onClick={() => setLayout('tree')} title="Tree layout" aria-label="Tree layout" aria-pressed={layout === 'tree'}
          className={cls('grid size-7 place-items-center rounded-md', layout === 'tree' ? 'bg-sky-500/25 text-sky-200' : 'text-slate-400 hover:text-white')}><Network className="size-4" /></button>
        <button type="button" onClick={() => setLayout('radial')} title="Radial layout" aria-label="Radial layout" aria-pressed={layout === 'radial'}
          className={cls('grid size-7 place-items-center rounded-md', layout === 'radial' ? 'bg-sky-500/25 text-sky-200' : 'text-slate-400 hover:text-white')}><Orbit className="size-4" /></button>
      </div>
      <button type="button" className={btn} title="Zoom out" aria-label="Zoom out" onClick={() => zoomOut({ duration: 200 })}><ZoomOut className="size-4" /></button>
      <button type="button" className={btn} title="Zoom in" aria-label="Zoom in" onClick={() => zoomIn({ duration: 200 })}><ZoomIn className="size-4" /></button>
      <button type="button" className={btn} title="Fit to screen" aria-label="Fit to screen" onClick={() => fitView({ duration: 500, padding: FIT_PAD })}><Maximize2 className="size-4" /></button>
    </div>
  )
}

type Menu = { id: string; x: number; y: number } | null

function NodeMenu({ menu, close, focusBranch }: { menu: Menu; close: () => void; focusBranch: (id: string) => void }) {
  const first = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!menu) return
    first.current?.focus()
    const k = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); close() } }
    const away = () => close()
    window.addEventListener('keydown', k, true)
    window.addEventListener('pointerdown', away)
    return () => { window.removeEventListener('keydown', k, true); window.removeEventListener('pointerdown', away) }
  }, [menu, close])
  if (!menu) return null
  const app = useApp.getState()
  const t = app.foldTree()
  const run = (f: () => void) => () => { f(); close() }
  const item = 'flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs text-slate-100 hover:bg-white/10 focus:bg-white/10 focus:outline-none'
  return (
    <div role="menu" aria-label="Branch" className="nc-glass fixed z-50 min-w-48 rounded-xl p-1 shadow-2xl"
      style={{ left: menu.x, top: menu.y }} onPointerDown={(e) => e.stopPropagation()}>
      <button ref={first} type="button" role="menuitem" className={item}
        onClick={run(() => t && app.setFold(F.expandSubtree(t.idx, app.fold, menu.id), menu.id))}><ChevronsUpDown className="size-3.5" />Expand all below</button>
      <button type="button" role="menuitem" className={item}
        onClick={run(() => t && app.setFold(F.collapseSubtree(t.idx, app.fold, menu.id), menu.id))}><ChevronsDownUp className="size-3.5" />Collapse all below</button>
      <button type="button" role="menuitem" className={item} onClick={run(() => focusBranch(menu.id))}><Crosshair className="size-3.5" />Focus this branch</button>
    </div>
  )
}

function Flow() {
  const map = useApp((s) => s.map)
  const layout = useApp((s) => s.layout)
  const fold = useApp((s) => s.fold)
  const foldAnchor = useApp((s) => s.foldAnchor)
  const highlights = useApp((s) => s.highlights)
  const selected = useApp((s) => s.selected)
  const focusRequest = useApp((s) => s.focusRequest)
  const mapError = useApp((s) => s.mapError)
  const { fitView, getNode, getViewport, setCenter } = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CardData>>([])
  // the card that has keyboard focus: a ref, not state, so moving focus never re-renders (a commit took focus away)
  const focusedRef = useRef<string | null>(null)
  const [menu, setMenu] = useState<Menu>(null)
  const radial = layout === 'radial'
  // zoomed out to tiles, nearly every card is on screen: culling would only re-scan every node on every pan frame
  const tiles = useStore(isTiny)
  const shownOnce = useRef(false)
  const engine = useMemo(layoutEngine, [])

  const tree = useMemo(() => (map ? useApp.getState().foldTree() : null), [map])
  const visibleIds = useMemo(() => (tree ? F.visible(tree.idx, fold) : []), [tree, fold])
  const visKey = visibleIds.join('|')
  // positions depend on the tree's shape and what is open, never on counts, highlights or selection
  // biome-ignore lint/correctness/useExhaustiveDependencies: keyed on shape and the visible set on purpose
  const raw = useMemo(() => (tree ? layoutPositions(tree, visibleIds, { radial, engine }) : new Map<string, Pos>()), [tree?.shape, visKey, radial, engine])
  const hidden = useMemo(() => {
    if (!tree) return new Map<string, F.Hidden>()
    return F.hiddenSummary(tree.idx, fold, (id) => {
      const n = tree.by.get(id)
      return n && { status: n.display_status, alerts: n.counts?.open_alerts ?? 0, tasks: n.type === 'task' ? 0 : n.counts?.open_tasks ?? 0 }
    })
  }, [tree, fold])
  // a change inside a folded branch pulses the nearest card on screen
  const hot = useMemo(() => {
    const now = Date.now()
    const out = new Set<string>()
    if (!tree) return out
    for (const [id, until] of Object.entries(highlights)) {
      if (until <= now) continue
      const v = F.nearestVisible(tree.idx, fold, id)
      if (v) out.add(v)
    }
    return out
  }, [highlights, tree, fold])

  // the clicked node stays where it is on screen: shift the new layout so it lands on its old position
  const offset = useRef<Pos>({ x: 0, y: 0 })
  const shown = useRef<Map<string, Pos>>(new Map())
  const lastAnchor = useRef(0)
  const pos = useMemo(() => {
    if (foldAnchor && foldAnchor.at !== lastAnchor.current) {
      lastAnchor.current = foldAnchor.at
      const before = shown.current.get(foldAnchor.id)
      const after = raw.get(foldAnchor.id)
      if (before && after) offset.current = { x: before.x - after.x, y: before.y - after.y }
    }
    const o = offset.current
    const out = new Map<string, Pos>()
    for (const [id, p] of raw) out.set(id, { x: p.x + o.x, y: p.y + o.y })
    return out
  }, [raw, foldAnchor])

  // grow and fold: new cards start on their parent and slide out; folded ones slide into it and fade
  const anim = useRef<{ timer?: ReturnType<typeof setTimeout>; raf?: number }>({})
  const entering = useRef<Set<string>>(new Set())
  // One effect, one React Flow update per change: a fold or layout change places cards (with animation); counts,
  // highlights and selection only refresh the cards where they are. (Two effects meant two updates of every node.)
  const placed = useRef<{ pos: Map<string, Pos> | null; vis: string }>({ pos: null, vis: '' })
  // biome-ignore lint/correctness/useExhaustiveDependencies: tree, fold and radial reach here through pos and visKey
  useEffect(() => {
    if (!tree) return
    if (placed.current.pos === pos && placed.current.vis === visKey) {
      if (entering.current.size) return  // an animation is running; it finishes with fresh data
      const opts = { radial, open: (id: string) => F.isOpen(tree.idx, fold, id), hidden, hot, selected, focused: focusedRef.current ?? selected ?? tree.idx.roots[0] }
      setNodes((cur) => {
        const at = new Map(cur.map((n) => [n.id, n.position]))
        return keep(cur, buildNodes(tree, visibleIds, pos, { ...opts, position: (id) => at.get(id) }))
      })
      return
    }
    placed.current = { pos, vis: visKey }
    const prev = shown.current
    const vis = new Set(visibleIds)
    const enter = visibleIds.filter((id) => !prev.has(id))
    const leave = [...prev.keys()].filter((id) => !vis.has(id) && tree.idx.depth.has(id))
    const opts = { radial, open: (id: string) => F.isOpen(tree.idx, fold, id), hidden, hot, selected, focused: focusedRef.current ?? selected ?? tree.idx.roots[0] }
    clearTimeout(anim.current.timer)
    if (anim.current.raf) cancelAnimationFrame(anim.current.raf)
    const settle = () => {
      entering.current = new Set()
      const next = buildNodes(tree, visibleIds, pos, opts)
      setNodes((cur) => keep(cur, next))
    }
    const animate = prev.size > 0 && !reducedMotion() && enter.length + leave.length > 0 && enter.length + leave.length <= ANIM_MAX
    if (!animate) {
      settle()
    } else {
      const from = (id: string): Pos | undefined => {
        for (const a of [id, ...F.ancestors(tree.idx, id)]) { const p = prev.get(a); if (p) return p }
        return undefined
      }
      const into = (id: string): Pos | undefined => { const v = F.nearestVisible(tree.idx, fold, id); return v ? pos.get(v) : undefined }
      entering.current = new Set(enter)
      const ids = [...visibleIds, ...leave]
      const start = buildNodes(tree, ids, pos, { ...opts, position: (id) => (vis.has(id) ? (enter.includes(id) ? from(id) : prev.get(id)) : prev.get(id)),
        className: (id) => (enter.includes(id) ? 'nc-anim nc-enter' : 'nc-anim') })
      setNodes((cur) => keep(cur, start))
      anim.current.raf = requestAnimationFrame(() => {
        anim.current.raf = requestAnimationFrame(() => {
          const end = buildNodes(tree, ids, pos, { ...opts, position: (id) => (vis.has(id) ? pos.get(id) : into(id)),
            className: (id) => (vis.has(id) ? 'nc-anim' : 'nc-anim nc-exit') })
          setNodes((cur) => keep(cur, end))
          anim.current.timer = setTimeout(settle, ANIM_MS + 40)
        })
      })
    }
    shown.current = new Map(visibleIds.map((id) => [id, pos.get(id)!]))
  }, [pos, visKey, map, hidden, hot, selected])

  const edges = useMemo(() => (tree && map ? buildEdges(tree, map, visibleIds, { radial, hot, entering: entering.current }) : []), [tree, map, visibleIds, radial, hot])

  // first draw, a switch of layout and a level step: fit. Card sizes are known up front (layout.ts), so this does not
  // wait for React Flow to measure: culled cards are never measured, and waiting for them would never fit
  const wantFit = useRef(true)
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new layout or level asks for a fit
  useEffect(() => { wantFit.current = true }, [layout, fold.depth])
  // biome-ignore lint/correctness/useExhaustiveDependencies: fit when measured and asked for
  useEffect(() => {
    if (!nodes.length || !wantFit.current) return
    const first = !shownOnce.current
    wantFit.current = false
    shownOnce.current = true
    const t = setTimeout(() => fitView({ duration: first || reducedMotion() ? 0 : 450, padding: FIT_PAD, maxZoom: 1.1 }), first ? 0 : ANIM_MS)
    return () => clearTimeout(t)
  }, [nodes.length, layout, fold.depth])

  // a note landed (or "go to"): glide to what changed, as far as it is on screen
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs per focus request and per new map, not per render
  useEffect(() => {
    if (!focusRequest || !tree) return
    const ids = [...new Set(focusRequest.ids.map((id) => F.nearestVisible(tree.idx, fold, id)).filter((x): x is string => !!x))]
    if (!ids.length) return
    const t = setTimeout(() => {
      const present = ids.filter((id) => getNode(id))
      if (present.length) fitView({ nodes: present.map((id) => ({ id })), duration: reducedMotion() ? 0 : 900, padding: present.length > 1 ? 0.35 : 1.2, maxZoom: 1.15 })
    }, 420)
    return () => clearTimeout(t)
  }, [focusRequest?.at, map?.generated_at])

  const focusBranch = (id: string) => {
    if (!tree) return
    const app = useApp.getState()
    app.setFold(F.reveal(tree.idx, app.fold, id))
    setTimeout(() => {
      const inBranch = F.visible(tree.idx, useApp.getState().fold).filter((v) => v === id || F.ancestors(tree.idx, v).includes(id))
      fitView({ nodes: inBranch.map((v) => ({ id: v })), duration: reducedMotion() ? 0 : 600, padding: FIT_PAD })
    }, ANIM_MS + 80)
  }

  // keyboard: the WAI-ARIA tree pattern. Space (hold to talk) and "/" (typed note) stay with the app.
  const nodeEl = (id: string) => document.querySelector(`.react-flow__node[data-id="${CSS.escape(id)}"]`) as HTMLElement | null
  const markFocus = (id: string) => {  // roving tabindex: only the focused card is in the tab order
    const prev = focusedRef.current
    if (prev && prev !== id) nodeEl(prev)?.setAttribute('tabindex', '-1')
    nodeEl(id)?.setAttribute('tabindex', '0')
    focusedRef.current = id
  }
  const moveFocus = (id: string | undefined) => {
    if (!id) return
    markFocus(id)
    const n = getNode(id)
    if (n) {
      const vp = getViewport()
      const el = document.querySelector('.react-flow')?.getBoundingClientRect()
      const sx = n.position.x * vp.zoom + vp.x
      const sy = n.position.y * vp.zoom + vp.y
      if (el && (sx < 40 || sy < 80 || sx > el.width - 280 || sy > el.height - 160)) {
        void setCenter(n.position.x + (n.measured?.width ?? 240) / 2, n.position.y + (n.measured?.height ?? 100) / 2, { zoom: Math.max(vp.zoom, 0.7), duration: reducedMotion() ? 0 : 200 })
      }
    }
    let tries = 0  // a card scrolled into view is rendered a frame or two later
    const go = () => { const el = nodeEl(id); if (el) { el.setAttribute('tabindex', '0'); el.focus({ preventScroll: true }) } else if (tries++ < 10) requestAnimationFrame(go) }
    requestAnimationFrame(go)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!tree || (e.target as HTMLElement).closest('input, select, textarea, [role="menu"]')) return
    const f = focusedRef.current
    const cur = f && visibleIds.includes(f) ? f : (selected && visibleIds.includes(selected) ? selected : visibleIds[0])
    if (!cur) return
    const i = visibleIds.indexOf(cur)
    const app = useApp.getState()
    const foldable = (tree.idx.children.get(cur)?.length ?? 0) > 0
    const open = F.isOpen(tree.idx, fold, cur)
    let handled = true
    switch (e.key) {
      case 'ArrowDown': moveFocus(visibleIds[i + 1]); break
      case 'ArrowUp': moveFocus(visibleIds[i - 1]); break
      case 'Home': moveFocus(visibleIds[0]); break
      case 'End': moveFocus(visibleIds[visibleIds.length - 1]); break
      case 'ArrowRight':
        if (e.shiftKey && foldable) app.setFold(F.expandSubtree(tree.idx, fold, cur), cur)
        else if (foldable && !open) app.setFold(F.openNode(tree.idx, fold, cur), cur)
        else if (open) moveFocus(tree.idx.children.get(cur)?.[0])
        break
      case 'ArrowLeft':
        if (e.shiftKey && foldable) app.setFold(F.collapseSubtree(tree.idx, fold, cur), cur)
        else if (open) app.setFold(F.closeNode(tree.idx, fold, cur), cur)
        else moveFocus(tree.idx.parent.get(cur) ?? undefined)
        break
      case 'Enter': {
        const n = tree.by.get(cur)
        if (n && !n.virtual) app.select(n.type === 'task' ? n.parent_id : n.type === 'member' ? (n.person_node_id ?? null) : cur)
        break
      }
      case 'ContextMenu': {
        const el = document.querySelector(`.react-flow__node[data-id="${CSS.escape(cur)}"]`)?.getBoundingClientRect()
        if (el) setMenu({ id: cur, x: el.left + 24, y: el.bottom - 8 })
        break
      }
      default: handled = false
    }
    if (handled) { e.preventDefault(); e.stopPropagation() }
  }

  const onClick: NodeMouseHandler<Node<CardData>> = (_, n) => {
    const m = n.data.node
    markFocus(n.id)
    if (m.type === 'task') useApp.getState().select(m.parent_id)
    else if (m.type === 'member') useApp.getState().select(m.person_node_id ?? null)
    else if (!m.virtual) useApp.getState().select(m.id)
  }

  if (!map) {
    return (
      <div className="grid h-full place-items-center text-sm text-slate-400">
        {mapError ? <p className="max-w-md text-center">{mapError}</p> : <Loader2 className="size-6 animate-spin" />}
      </div>
    )
  }
  return (
    <div className="nc-map h-full w-full" role="tree" aria-label={`Mind map of ${map.workspace.name}`} onKeyDown={onKeyDown}
      onFocus={(e) => { const id = (e.target as HTMLElement).closest('.react-flow__node')?.getAttribute('data-id'); if (id && id !== focusedRef.current) markFocus(id) }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={onClick}
        onNodeContextMenu={(e, n) => { e.preventDefault(); setMenu({ id: n.id, x: e.clientX, y: e.clientY }) }}
        onPaneClick={() => useApp.getState().select(null)}
        nodesConnectable={false}
        nodesDraggable={false}
        deleteKeyCode={null}
        disableKeyboardA11y
        minZoom={0.1}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        colorMode="system"
        onlyRenderVisibleElements={!tiles || visibleIds.length < 300}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="rgba(148,163,184,0.18)" />
        {/* the overview redraws every card as SVG on each change: on very large open maps it costs more than it shows */}
        {!selected && visibleIds.length <= MINIMAP_MAX && <MiniMap pannable zoomable position="bottom-left" className="!hidden !rounded-xl !border !border-white/10 !bg-slate-900/70 sm:!block"
          maskColor="var(--nc-minimap-mask)" nodeColor={(n) => statusColor((n.data as CardData).node.display_status)} nodeStrokeWidth={0} />}
        <Toolbar />
      </ReactFlow>
      <NodeMenu menu={menu} close={() => setMenu(null)} focusBranch={focusBranch} />
    </div>
  )
}

export function MindMap() {
  return (
    <ReactFlowProvider>
      <Flow />
    </ReactFlowProvider>
  )
}
