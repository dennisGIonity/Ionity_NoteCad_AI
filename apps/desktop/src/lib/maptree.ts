// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The tree the map folds, from the mind map payload: kept apart from the layout engines so the store (loaded with
// the recorder HUD) can fold and reveal without loading d3 or dagre.
import { indexTree, type FoldIndex } from '@notecad/core/fold'
import type { MapNode, MindMap } from './types'

export type CardKind = 'root' | 'category' | 'asset' | 'field' | 'task' | 'member'

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

export const inline = (n: MapNode) => { const k = cardKind(n); return k === 'asset' || k === 'field' }

/** The tree the map folds: every node except tasks drawn inside their card. */
export interface MapTree {
  by: Map<string, MapNode>
  idx: FoldIndex
  tasksOf: Map<string, MapNode[]>  // open tasks per node (inline or as leaves)
  sizes: Map<string, [number, number]>
  shape: string                    // changes only when nodes, parents or card sizes change
}

export function mapTree(map: MindMap): MapTree {
  const by = new Map(map.nodes.map((n) => [n.id, n]))
  const tasksOf = new Map<string, MapNode[]>()
  for (const n of map.nodes) if (n.type === 'task' && n.parent_id) {
    const list = tasksOf.get(n.parent_id)
    if (list) list.push(n)
    else tasksOf.set(n.parent_id, [n])
  }
  const order = (a: MapNode, b: MapNode) => (a.type === 'task' ? 1 : 0) - (b.type === 'task' ? 1 : 0) || a.title.localeCompare(b.title)
  const shown = map.nodes
    .filter((n) => !(n.type === 'task' && n.parent_id && by.get(n.parent_id) && inline(by.get(n.parent_id)!)))
    .sort(order)
  const sizes = new Map(shown.map((n) => [n.id, sizeOf(cardKind(n), (tasksOf.get(n.id) ?? []).length)] as const))
  const roots = shown.filter((n) => n.id === map.root || !n.parent_id).map((n) => n.id)
  const fold = shown.map((n) => ({ id: n.id, parent_id: roots.includes(n.id) ? null : n.parent_id }))
  const idx = indexTree(fold)
  const shape = fold.map((f) => `${f.id}<${f.parent_id ?? ''}:${sizes.get(f.id)![1]}`).join('|')
  return { by, idx, tasksOf, sizes, shape }
}
