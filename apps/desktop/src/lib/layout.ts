// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Mind map payload -> the fold tree, positions for the visible nodes, and React Flow nodes and edges.
// Tasks on things (assets, fields) are drawn inside their card; tasks on categories are their own leaves.
// Layout engines (ADR 0013): d3-hierarchy's tidy tree (3 ms for 2,000 nodes), dagre as a fallback
// (localStorage notecad.layoutEngine = "dagre"), and the radial view. Positions depend only on the tree's shape,
// so selection, highlights and live counts never run the layout again.
import dagre from '@dagrejs/dagre'
import type { Hidden } from '@notecad/core/fold'
import { type Edge, type Node, type NodeHandle, Position } from '@xyflow/react'
import { hierarchy, tree as tidyTree } from 'd3-hierarchy'
import { cardKind, inline, type CardKind, type MapTree } from './maptree'
import type { MapNode, MindMap } from './types'
import { statusColor } from './ui'

export type Engine = 'tidy' | 'dagre'
export type Pos = { x: number; y: number }
export interface CardData extends Record<string, unknown> {
  node: MapNode
  card: CardKind
  tasks: MapNode[]
  highlight: boolean
  foldable: boolean
  open: boolean
  hidden: Hidden | null
  level: number
  radial: boolean
}

const GAP_Y = 16
const GAP_X = 90

/** Top-left positions of the visible nodes. */
export function layoutPositions(t: MapTree, visibleIds: string[], opts: { radial: boolean; engine: Engine }): Map<string, Pos> {
  const vis = new Set(visibleIds)
  const pos = new Map<string, Pos>()
  const kidsOf = (id: string) => (t.idx.children.get(id) ?? []).filter((k) => vis.has(k))
  const rootId = t.idx.roots.find((r) => vis.has(r))
  if (!rootId) return pos
  const size = (id: string) => t.sizes.get(id) ?? [240, 100]
  if (opts.radial) {
    const weight = new Map<string, number>()
    const wt = (id: string): number => {
      const ks = kidsOf(id)
      const v = ks.length ? ks.reduce((s, k) => s + wt(k), 0) : 1
      weight.set(id, v)
      return v
    }
    wt(rootId)
    const ring = (d: number) => (d === 0 ? 0 : 330 + (d - 1) * 300)
    const place = (id: string, d: number, a0: number, a1: number) => {
      const a = (a0 + a1) / 2
      const [w, h] = size(id)
      pos.set(id, { x: ring(d) * Math.cos(a) - w / 2, y: ring(d) * Math.sin(a) - h / 2 })
      let cur = a0
      const total = weight.get(id) ?? 1
      for (const k of kidsOf(id)) {
        const span = ((a1 - a0) * (weight.get(k) ?? 1)) / total
        place(k, d + 1, cur, cur + span)
        cur += span
      }
    }
    place(rootId, 0, -Math.PI, Math.PI)
    return pos
  }
  if (opts.engine === 'dagre') {
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', nodesep: GAP_Y, ranksep: GAP_X, marginx: 40, marginy: 40 })
    g.setDefaultEdgeLabel(() => ({}))
    for (const id of visibleIds) { const [w, h] = size(id); g.setNode(id, { width: w, height: h }) }
    for (const id of visibleIds) { const p = t.idx.parent.get(id); if (p && vis.has(p)) g.setEdge(p, id) }
    dagre.layout(g)
    for (const id of visibleIds) { const p = g.node(id); const [w, h] = size(id); pos.set(id, { x: p.x - w / 2, y: p.y - h / 2 }) }
    return pos
  }
  // tidy tree, left to right: d3's x is our vertical axis. Separation in pixels from each pair's card heights.
  type D = { id: string; children: D[] }
  const build = (id: string): D => ({ id, children: kidsOf(id).map(build) })
  const root = hierarchy<D>(build(rootId))
  const colX = new Map<number, number>()  // column left edge per depth: the widest card of the column decides
  let x = 0
  for (let d = 0; d <= t.idx.maxDepth; d++) {
    colX.set(d, x)
    let widest = 0
    for (const id of visibleIds) if (t.idx.depth.get(id) === d) widest = Math.max(widest, size(id)[0])
    x += (widest || 240) + GAP_X
  }
  tidyTree<D>().nodeSize([1, 1]).separation((a, b) => (size(a.data.id)[1] + size(b.data.id)[1]) / 2 + (a.parent === b.parent ? GAP_Y : GAP_Y * 2))(root)
  root.each((n) => {
    const [, h] = size(n.data.id)
    pos.set(n.data.id, { x: colX.get(n.depth) ?? n.depth * 340, y: (n.x ?? 0) - h / 2 })
  })
  return pos
}

// where Cards.tsx puts its handles: left / right middle for the tree, the centre for the radial view
function handlesFor(w: number, h: number): NodeHandle[] {
  return [
    { id: 't', type: 'target', position: Position.Left, x: 0, y: h / 2 },
    { id: 's', type: 'source', position: Position.Right, x: w, y: h / 2 },
    { id: 'ct', type: 'target', position: Position.Top, x: w / 2, y: h / 2 },
    { id: 'cs', type: 'source', position: Position.Top, x: w / 2, y: h / 2 },
  ]
}

export function buildNodes(t: MapTree, visibleIds: string[], pos: Map<string, Pos>, opts: {
  radial: boolean; open: (id: string) => boolean; hidden: Map<string, Hidden>; hot: Set<string>; selected: string | null;
  focused: string | null; className?: (id: string) => string | undefined; position?: (id: string) => Pos | undefined
}): Node<CardData>[] {
  return visibleIds.map((id) => {
    const n = t.by.get(id)!
    const card = cardKind(n)
    const foldable = (t.idx.children.get(id)?.length ?? 0) > 0
    const open = foldable && opts.open(id)
    const level = (t.idx.depth.get(id) ?? 0) + 1
    const [w, h] = t.sizes.get(id) ?? [240, 100]
    return {
      id, type: card, position: opts.position?.(id) ?? pos.get(id) ?? { x: 0, y: 0 },
      // the card's size and its handles are known before it is drawn, so React Flow never has to render a card just
      // to measure it: off-screen cards stay out of the DOM even when 2,000 appear at once (Expand all), and a card
      // is never hidden (taking the keyboard focus with it) while it is measured
      initialWidth: w, initialHeight: h, measured: { width: w, height: h }, handles: handlesFor(w, h),
      selected: opts.selected === id,
      className: opts.className?.(id),
      ariaRole: 'treeitem',
      ariaLabel: n.title,
      domAttributes: {
        tabIndex: opts.focused === id ? 0 : -1,
        'aria-level': level,
        'aria-expanded': foldable ? open : undefined,
        'aria-selected': opts.selected === id,
      },
      data: {
        node: n, card, radial: opts.radial, tasks: (t.tasksOf.get(id) ?? []).filter(() => inline(n)),
        highlight: opts.hot.has(id), foldable, open, hidden: opts.hidden.get(id) ?? null, level,
      },
    }
  })
}

export function buildEdges(t: MapTree, map: MindMap, visibleIds: string[], opts: { radial: boolean; hot: Set<string>; entering?: Set<string> }): Edge[] {
  const vis = new Set(visibleIds)
  const handles = opts.radial ? { sourceHandle: 'cs', targetHandle: 'ct' } : { sourceHandle: 's', targetHandle: 't' }
  const edges: Edge[] = []
  for (const id of visibleIds) {
    const p = t.idx.parent.get(id)
    if (!p || !vis.has(p)) continue
    const n = t.by.get(id)!
    const st = n.type === 'task' ? (n.due_state === 'overdue' ? 'critical' : 'info') : n.display_status
    const hot = opts.hot.has(id)
    const quiet = !st || st === 'ok' || st === 'done'
    edges.push({
      id: `t:${id}`, source: p, target: id, ...handles, type: opts.radial ? 'straight' : 'default', animated: hot,
      className: opts.entering?.has(id) ? 'nc-edge-enter' : undefined,
      style: { stroke: hot ? '#38bdf8' : quiet ? 'rgba(148,163,184,0.35)' : statusColor(st), strokeWidth: hot ? 2.4 : quiet ? 1.4 : 1.8 },
    })
  }
  const tree = new Set(edges.map((e) => `${e.source}>${e.target}`))
  for (const e of map.edges) {
    if (e.type === 'belongs_to_category' || e.type === 'has_task') continue
    if (!vis.has(e.source) || !vis.has(e.target) || tree.has(`${e.source}>${e.target}`) || tree.has(`${e.target}>${e.source}`)) continue
    edges.push({
      id: `x:${e.id}`, source: e.source, target: e.target, sourceHandle: 'cs', targetHandle: 'ct', type: 'straight',
      label: e.relation === 'same_person' ? undefined : (e.relation ?? e.type).replace('_', ' '),
      labelStyle: { fill: '#94a3b8', fontSize: 10 }, labelBgStyle: { fill: 'rgba(15,23,42,0.8)' },
      style: { stroke: e.type === 'assigned_to' ? 'rgba(167,139,250,0.55)' : 'rgba(148,163,184,0.35)', strokeDasharray: '4 4', strokeWidth: 1.2 },
    })
  }
  return edges
}

export function layoutEngine(): Engine {
  try { return localStorage.getItem('notecad.layoutEngine') === 'dagre' ? 'dagre' : 'tidy' } catch { return 'tidy' }
}
