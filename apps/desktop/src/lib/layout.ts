// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Mind map payload -> React Flow nodes and edges, laid out as a left-to-right tree (Dagre) or radially.
// Tasks on things (assets, fields) are drawn inside their card; tasks on categories are their own leaves.
import dagre from '@dagrejs/dagre'
import type { Edge, Node } from '@xyflow/react'
import type { MapNode, MindMap } from './types'
import { statusColor } from './ui'

export type CardKind = 'root' | 'category' | 'asset' | 'field' | 'task' | 'member'
export interface CardData extends Record<string, unknown> {
  node: MapNode
  card: CardKind
  tasks: MapNode[]
  highlight: boolean
  collapsed: boolean
  hidden: number
  kids: number
  radial: boolean
}

const SIZE: Record<CardKind, [number, number]> = {
  root: [250, 96], category: [250, 104], asset: [260, 104], field: [260, 116], task: [230, 52], member: [210, 60],
}

export function cardKind(n: MapNode): CardKind {
  if (n.type === 'root') return 'root'
  if (n.type === 'category') return 'category'
  if (n.type === 'task') return 'task'
  if (n.type === 'member') return 'member'
  if (n.kind === 'field' || n.progress?.unit === 'ha') return 'field'
  return 'asset'
}

export function sizeOf(card: CardKind, tasks = 0): [number, number] {
  const [w, h] = SIZE[card]
  return card === 'asset' ? [w, h + Math.min(tasks, 2) * 22] : [w, h]
}

export function ancestors(map: MindMap, id: string): string[] {
  const by = new Map(map.nodes.map((n) => [n.id, n]))
  const out: string[] = []
  let n = by.get(id)
  while (n?.parent_id) {
    out.push(n.parent_id)
    n = by.get(n.parent_id)
  }
  return out
}

export function buildGraph(map: MindMap, opts: { collapsed: Record<string, boolean>; radial: boolean; highlights: Record<string, number>; selected: string | null }) {
  const by = new Map(map.nodes.map((n) => [n.id, n]))
  const kids = new Map<string, MapNode[]>()
  for (const n of map.nodes) if (n.parent_id) kids.set(n.parent_id, [...(kids.get(n.parent_id) ?? []), n])
  const inline = (n: MapNode) => cardKind(n) === 'asset' || cardKind(n) === 'field'
  const order = (a: MapNode, b: MapNode) => (a.type === 'task' ? 1 : 0) - (b.type === 'task' ? 1 : 0) || a.title.localeCompare(b.title)

  // visible tree, honouring collapsed branches
  const visible: MapNode[] = []
  const shownKids = new Map<string, MapNode[]>()
  const countAll = (id: string): number => (kids.get(id) ?? []).reduce((s, k) => s + 1 + countAll(k.id), 0)
  const walk = (n: MapNode) => {
    visible.push(n)
    const ks = (kids.get(n.id) ?? []).filter((k) => !(k.type === 'task' && inline(n))).sort(order)
    if (opts.collapsed[n.id]) return
    shownKids.set(n.id, ks)
    ks.forEach(walk)
  }
  const root = by.get(map.root)
  if (!root) return { nodes: [] as Node<CardData>[], edges: [] as Edge[] }
  walk(root)
  const vis = new Set(visible.map((n) => n.id))

  // positions
  const pos = new Map<string, { x: number; y: number }>()
  const sizes = new Map(visible.map((n) => {
    const card = cardKind(n)
    return [n.id, sizeOf(card, (kids.get(n.id) ?? []).filter((k) => k.type === 'task').length)] as const
  }))
  if (!opts.radial) {
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', nodesep: 16, ranksep: 90, marginx: 40, marginy: 40 })
    g.setDefaultEdgeLabel(() => ({}))
    for (const n of visible) {
      const [w, h] = sizes.get(n.id)!
      g.setNode(n.id, { width: w, height: h })
    }
    for (const n of visible) if (n.parent_id && vis.has(n.parent_id)) g.setEdge(n.parent_id, n.id)
    dagre.layout(g)
    for (const n of visible) {
      const p = g.node(n.id)
      const [w, h] = sizes.get(n.id)!
      pos.set(n.id, { x: p.x - w / 2, y: p.y - h / 2 })
    }
  } else {
    const weight = new Map<string, number>()
    const wt = (n: MapNode): number => {
      const ks = shownKids.get(n.id) ?? []
      const v = ks.length ? ks.reduce((s, k) => s + wt(k), 0) : 1
      weight.set(n.id, v)
      return v
    }
    wt(root)
    const ring = (d: number) => (d === 0 ? 0 : 330 + (d - 1) * 300)
    const place = (n: MapNode, d: number, a0: number, a1: number) => {
      const a = (a0 + a1) / 2
      const [w, h] = sizes.get(n.id)!
      const r = ring(d)
      pos.set(n.id, { x: r * Math.cos(a) - w / 2, y: r * Math.sin(a) - h / 2 })
      let cur = a0
      const total = weight.get(n.id) ?? 1
      for (const k of shownKids.get(n.id) ?? []) {
        const span = ((a1 - a0) * (weight.get(k.id) ?? 1)) / total
        place(k, d + 1, cur, cur + span)
        cur += span
      }
    }
    place(root, 0, -Math.PI, Math.PI)
  }

  const now = Date.now()
  const nodes: Node<CardData>[] = visible.map((n) => {
    const card = cardKind(n)
    return {
      id: n.id,
      type: card,
      position: pos.get(n.id)!,
      selected: opts.selected === n.id,
      data: {
        node: n, card, radial: opts.radial,
        tasks: (kids.get(n.id) ?? []).filter((k) => k.type === 'task'),
        highlight: (opts.highlights[n.id] ?? 0) > now,
        collapsed: !!opts.collapsed[n.id],
        hidden: opts.collapsed[n.id] ? countAll(n.id) : 0,
        kids: (kids.get(n.id) ?? []).filter((k) => !(k.type === 'task' && inline(n))).length,
      },
    }
  })

  const handles = opts.radial ? { sourceHandle: 'cs', targetHandle: 'ct' } : { sourceHandle: 's', targetHandle: 't' }
  const edges: Edge[] = []
  for (const n of visible) {
    if (!n.parent_id || !vis.has(n.parent_id)) continue
    const st = n.type === 'task' ? (n.due_state === 'overdue' ? 'critical' : 'info') : n.display_status
    const hot = (opts.highlights[n.id] ?? 0) > now
    const quiet = !st || st === 'ok' || st === 'done'
    edges.push({
      id: `t:${n.id}`, source: n.parent_id, target: n.id, ...handles, type: opts.radial ? 'straight' : 'default',
      animated: hot,
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
  return { nodes, edges }
}
