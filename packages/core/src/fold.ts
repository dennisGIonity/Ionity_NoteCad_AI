// Ionity NoteCad - Core | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Folding the mind map: which nodes exist on screen. Pure functions over a parent/child tree, shared by the desktop
// map and the phone's context picker. The state is view state for this device and lens, never data: it is kept in
// local storage and never written to the action log or synced.
//
// A node is open when it is listed in `expanded`, or when it sits above the default `depth` and is not listed in
// `collapsed`. depth 0 = only the root; 1 = the main areas (Vehicles, Fields, Livestock ...); EXPAND_ALL = everything.
// Level operations set the depth and clear the per-node exceptions; per-node operations only touch the exceptions,
// so the state stays a handful of ids however large the farm.

export interface FoldNode { id: string; parent_id?: string | null }
export interface FoldState { depth: number; expanded: string[]; collapsed: string[] }
export interface FoldIndex {
  roots: string[]
  parent: Map<string, string | null>
  children: Map<string, string[]>
  depth: Map<string, number>
  order: string[]  // every reachable node, depth-first, children in the given order
  maxDepth: number
}
export interface NodeStats { status?: string | null; alerts?: number; tasks?: number }
export interface Hidden { count: number; alerts: number; tasks: number; worst: string }

export const EXPAND_ALL = 999
export const MAIN_AREAS: FoldState = { depth: 1, expanded: [], collapsed: [] }

/** done < pending < ok < info < routine_due < warning < critical, as in the brain (common.STATUS_RANK). */
export const STATUS_RANK: Record<string, number> = { done: 0, pending: 1, ok: 2, info: 3, routine_due: 4, warning: 5, critical: 6 }
const worse = (a: string, b?: string | null) => (b && (STATUS_RANK[b] ?? 2) > (STATUS_RANK[a] ?? 2) ? b : a)

/** Parent/child index. Nodes whose parent is missing (tombstoned) are left out with their whole branch; a parent
 *  cycle cannot hang it, because only nodes reached from a root are indexed. */
export function indexTree(nodes: readonly FoldNode[]): FoldIndex {
  const ids = new Set(nodes.map((n) => n.id))
  const children = new Map<string, string[]>()
  const roots: string[] = []
  for (const n of nodes) {
    const p = n.parent_id ?? null
    if (p === null) roots.push(n.id)
    else if (ids.has(p)) {
      const list = children.get(p)
      if (list) list.push(n.id)
      else children.set(p, [n.id])
    }
  }
  const parent = new Map<string, string | null>()
  const depth = new Map<string, number>()
  const order: string[] = []
  let maxDepth = 0
  const stack: [string, string | null, number][] = roots.slice().reverse().map((r) => [r, null, 0])
  while (stack.length) {
    const [id, p, d] = stack.pop()!
    if (depth.has(id)) continue
    parent.set(id, p)
    depth.set(id, d)
    order.push(id)
    if (d > maxDepth) maxDepth = d
    const kids = children.get(id) ?? []
    for (let i = kids.length - 1; i >= 0; i--) stack.push([kids[i], id, d + 1])
  }
  return { roots, parent, children, depth, order, maxDepth }
}

const hasKids = (idx: FoldIndex, id: string) => (idx.children.get(id)?.length ?? 0) > 0

function sets(s: FoldState) {
  return { open: new Set(s.expanded), shut: new Set(s.collapsed) }
}

function openIn(idx: FoldIndex, s: FoldState, x: ReturnType<typeof sets>, id: string): boolean {
  if (!hasKids(idx, id)) return false
  if (x.shut.has(id)) return false
  if (x.open.has(id)) return true
  return (idx.depth.get(id) ?? Number.POSITIVE_INFINITY) < s.depth
}

export function isOpen(idx: FoldIndex, s: FoldState, id: string): boolean {
  return openIn(idx, s, sets(s), id)
}

/** The nodes on screen, depth-first (the keyboard's up/down order). */
export function visible(idx: FoldIndex, s: FoldState): string[] {
  const x = sets(s)
  const out: string[] = []
  const stack = idx.roots.slice().reverse()
  while (stack.length) {
    const id = stack.pop()!
    if (!idx.depth.has(id)) continue
    out.push(id)
    if (openIn(idx, s, x, id)) {
      const kids = idx.children.get(id) ?? []
      for (let i = kids.length - 1; i >= 0; i--) stack.push(kids[i])
    }
  }
  return out
}

/** The deepest level on screen: what the level stepper shows ("Level 2"). */
export function level(idx: FoldIndex, s: FoldState): number {
  let deepest = 0
  for (const id of visible(idx, s)) deepest = Math.max(deepest, idx.depth.get(id) ?? 0)
  return deepest
}

/** Show levels 0..d. A depth beyond the tree means "everything", also nodes added deeper later. */
export function setDepth(idx: FoldIndex, d: number): FoldState {
  const depth = d >= idx.maxDepth ? EXPAND_ALL : Math.max(0, Math.floor(d))
  return { depth, expanded: [], collapsed: [] }
}
export const expandLevel = (idx: FoldIndex, s: FoldState) => setDepth(idx, level(idx, s) + 1)
export const collapseLevel = (idx: FoldIndex, s: FoldState) => setDepth(idx, level(idx, s) - 1)
export const expandAll = (idx: FoldIndex) => setDepth(idx, EXPAND_ALL)
export const collapseAll = (idx: FoldIndex) => setDepth(idx, 0)
export const mainAreas = (): FoldState => ({ ...MAIN_AREAS })

function withOpen(idx: FoldIndex, s: FoldState, ids: Iterable<string>, open: boolean): FoldState {
  const x = sets(s)
  for (const id of ids) {
    if (!hasKids(idx, id)) continue
    const byDefault = (idx.depth.get(id) ?? Number.POSITIVE_INFINITY) < s.depth
    x.open.delete(id)
    x.shut.delete(id)
    if (open && !byDefault) x.open.add(id)
    if (!open && byDefault) x.shut.add(id)
  }
  return { depth: s.depth, expanded: [...x.open], collapsed: [...x.shut] }
}

export const openNode = (idx: FoldIndex, s: FoldState, id: string) => withOpen(idx, s, [id], true)
export const closeNode = (idx: FoldIndex, s: FoldState, id: string) => withOpen(idx, s, [id], false)
export const toggle = (idx: FoldIndex, s: FoldState, id: string) => withOpen(idx, s, [id], !isOpen(idx, s, id))

export function descendants(idx: FoldIndex, id: string): string[] {
  const out: string[] = []
  const stack = [...(idx.children.get(id) ?? [])]
  while (stack.length) {
    const c = stack.pop()!
    out.push(c)
    stack.push(...(idx.children.get(c) ?? []))
  }
  return out
}

/** Shift+click, "Expand all below". */
export const expandSubtree = (idx: FoldIndex, s: FoldState, id: string) => withOpen(idx, s, [id, ...descendants(idx, id)], true)
/** "Collapse all below": the node and everything under it; opening it again shows one level. */
export const collapseSubtree = (idx: FoldIndex, s: FoldState, id: string) => withOpen(idx, s, [id, ...descendants(idx, id)], false)

export function ancestors(idx: FoldIndex, id: string): string[] {
  const out: string[] = []
  let p = idx.parent.get(id) ?? null
  while (p !== null && p !== undefined) {
    out.push(p)
    p = idx.parent.get(p) ?? null
  }
  return out
}

/** Open only the path to a node (toast "Open", Inbox, search), nothing beside it. */
export const reveal = (idx: FoldIndex, s: FoldState, id: string) => (idx.depth.has(id) ? withOpen(idx, s, ancestors(idx, id), true) : s)

/** The node itself if it is on screen, else its nearest ancestor that is: where a hidden change pulses. */
export function nearestVisible(idx: FoldIndex, s: FoldState, id: string): string | null {
  if (!idx.depth.has(id)) return null
  const x = sets(s)
  const chain = [id, ...ancestors(idx, id)]  // node first, root last
  let shown: string | null = chain[chain.length - 1]
  for (let i = chain.length - 1; i > 0; i--) {
    if (!openIn(idx, s, x, chain[i])) return shown
    shown = chain[i - 1]
  }
  return shown
}

/** What each folded node hides: how many nodes, their alerts and tasks, and the worst status among them, so a
 *  problem deep in a folded branch still shows on the node you can see. */
export function hiddenSummary(idx: FoldIndex, s: FoldState, stats: (id: string) => NodeStats | undefined): Map<string, Hidden> {
  const below = new Map<string, Hidden>()  // over each node's descendants (not itself)
  for (let i = idx.order.length - 1; i >= 0; i--) {
    const id = idx.order[i]
    const acc: Hidden = { count: 0, alerts: 0, tasks: 0, worst: 'ok' }
    for (const c of idx.children.get(id) ?? []) {
      const cs = stats(c) ?? {}
      const cb = below.get(c)!
      acc.count += 1 + cb.count
      acc.alerts += (cs.alerts ?? 0) + cb.alerts
      acc.tasks += (cs.tasks ?? 0) + cb.tasks
      acc.worst = worse(worse(acc.worst, cs.status), cb.worst)
    }
    below.set(id, acc)
  }
  const out = new Map<string, Hidden>()
  const x = sets(s)
  for (const id of visible(idx, s)) if (hasKids(idx, id) && !openIn(idx, s, x, id)) out.set(id, below.get(id)!)
  return out
}

/** "+14 · 2 alerts · 3 tasks" */
export function badgeText(h: Hidden): string {
  const bits = [`+${h.count}`]
  if (h.alerts) bits.push(`${h.alerts} alert${h.alerts === 1 ? '' : 's'}`)
  if (h.tasks) bits.push(`${h.tasks} task${h.tasks === 1 ? '' : 's'}`)
  return bits.join(' · ')
}

/** Drop ids that are no longer in the tree (deleted, or synced away) and exceptions that match the default. */
export function prune(idx: FoldIndex, s: FoldState): FoldState {
  const keep = (id: string, open: boolean) => idx.depth.has(id) && hasKids(idx, id) && ((idx.depth.get(id)! < s.depth) !== open)
  return { depth: s.depth, expanded: s.expanded.filter((id) => keep(id, true)), collapsed: s.collapsed.filter((id) => keep(id, false)) }
}

export function serialize(s: FoldState): string {
  return JSON.stringify({ v: 1, d: s.depth, e: s.expanded, c: s.collapsed })
}

export function parse(text: string | null | undefined): FoldState | null {
  if (!text) return null
  try {
    const j = JSON.parse(text)
    if (j?.v !== 1 || typeof j.d !== 'number' || !Array.isArray(j.e) || !Array.isArray(j.c)) return null
    const ids = (a: unknown[]) => a.filter((x): x is string => typeof x === 'string').slice(0, 5000)
    return { depth: Math.max(0, Math.min(EXPAND_ALL, Math.floor(j.d))), expanded: ids(j.e), collapsed: ids(j.c) }
  } catch {
    return null
  }
}
