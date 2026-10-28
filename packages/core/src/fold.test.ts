// Ionity NoteCad - Core | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Every fold function, and the edge cases: empty tree, single root, nodes added / moved / tombstoned while folded,
// revealing through several folded levels, a depth larger than the tree.
import { describe, expect, it } from 'vitest'
import {
  EXPAND_ALL, MAIN_AREAS, ancestors, badgeText, closeNode, collapseAll, collapseLevel, collapseSubtree, descendants,
  expandAll, expandLevel, expandSubtree, hiddenSummary, indexTree, isOpen, level, mainAreas, nearestVisible, openNode,
  parse, prune, reveal, serialize, setDepth, toggle, visible, type FoldNode,
} from './fold'

// farm
// ├── vehicles ─ tractors ─ jd1, jd2
// ├── fields ─ south ─ f704, f705 ─ f705a
// └── staff
const FARM: FoldNode[] = [
  { id: 'farm', parent_id: null },
  { id: 'vehicles', parent_id: 'farm' }, { id: 'tractors', parent_id: 'vehicles' },
  { id: 'jd1', parent_id: 'tractors' }, { id: 'jd2', parent_id: 'tractors' },
  { id: 'fields', parent_id: 'farm' }, { id: 'south', parent_id: 'fields' },
  { id: 'f704', parent_id: 'south' }, { id: 'f705', parent_id: 'south' }, { id: 'f705a', parent_id: 'f705' },
  { id: 'staff', parent_id: 'farm' },
]
const idx = indexTree(FARM)

describe('indexTree', () => {
  it('knows depths, children and the depth-first order', () => {
    expect(idx.depth.get('f705a')).toBe(4)
    expect(idx.maxDepth).toBe(4)
    expect(idx.children.get('south')).toEqual(['f704', 'f705'])
    expect(idx.order).toEqual(['farm', 'vehicles', 'tractors', 'jd1', 'jd2', 'fields', 'south', 'f704', 'f705', 'f705a', 'staff'])
  })
  it('an empty tree is empty', () => {
    const e = indexTree([])
    expect(visible(e, MAIN_AREAS)).toEqual([])
    expect(level(e, MAIN_AREAS)).toBe(0)
    expect(hiddenSummary(e, MAIN_AREAS, () => ({})).size).toBe(0)
    expect(nearestVisible(e, MAIN_AREAS, 'x')).toBeNull()
  })
  it('a single root is shown and has nothing to fold', () => {
    const one = indexTree([{ id: 'r', parent_id: null }])
    expect(visible(one, collapseAll(one))).toEqual(['r'])
    expect(isOpen(one, expandAll(one), 'r')).toBe(false)
    expect(level(one, expandAll(one))).toBe(0)
  })
  it('a tombstoned node takes its branch with it, and a parent cycle cannot hang it', () => {
    const t = indexTree(FARM.filter((n) => n.id !== 'south'))
    expect(t.depth.has('f705')).toBe(false)
    const cyc = indexTree([{ id: 'a', parent_id: 'b' }, { id: 'b', parent_id: 'a' }, { id: 'r', parent_id: null }])
    expect(cyc.order).toEqual(['r'])
  })
})

describe('levels', () => {
  it('main areas: the root and the top-level categories', () => {
    expect(visible(idx, mainAreas())).toEqual(['farm', 'vehicles', 'fields', 'staff'])
    expect(level(idx, mainAreas())).toBe(1)
  })
  it('expand one level, collapse one level, step by depth', () => {
    const two = expandLevel(idx, mainAreas())
    expect(two.depth).toBe(2)
    expect(visible(idx, two)).toEqual(['farm', 'vehicles', 'tractors', 'fields', 'south', 'staff'])
    expect(level(idx, collapseLevel(idx, two))).toBe(1)
    expect(visible(idx, setDepth(idx, 0))).toEqual(['farm'])
  })
  it('expand all and collapse all', () => {
    expect(visible(idx, expandAll(idx))).toEqual(idx.order)
    expect(visible(idx, collapseAll(idx))).toEqual(['farm'])
  })
  it('a depth larger than the tree means everything, also nodes added deeper later', () => {
    const s = setDepth(idx, 40)
    expect(s.depth).toBe(EXPAND_ALL)
    const deeper = indexTree([...FARM, { id: 'f705a1', parent_id: 'f705a' }])
    expect(visible(deeper, s)).toContain('f705a1')
    expect(level(deeper, s)).toBe(5)
  })
  it('a level step clears the per-node exceptions', () => {
    const s = openNode(idx, mainAreas(), 'fields')
    expect(expandLevel(idx, s).expanded).toEqual([])
  })
  it('collapse one level never goes below the root', () => {
    expect(collapseLevel(idx, collapseAll(idx)).depth).toBe(0)
  })
})

describe('one node', () => {
  it('opening a node shows only its next level', () => {
    const s = openNode(idx, mainAreas(), 'fields')
    expect(visible(idx, s)).toEqual(['farm', 'vehicles', 'fields', 'south', 'staff'])
    expect(s).toEqual({ depth: 1, expanded: ['fields'], collapsed: [] })
  })
  it('closing a node that is open by default records the exception', () => {
    const s = closeNode(idx, setDepth(idx, 2), 'vehicles')
    expect(visible(idx, s)).toEqual(['farm', 'vehicles', 'fields', 'south', 'staff'])
    expect(s.collapsed).toEqual(['vehicles'])
  })
  it('toggle flips, and leaves leaves alone', () => {
    const s = toggle(idx, mainAreas(), 'vehicles')
    expect(isOpen(idx, s, 'vehicles')).toBe(true)
    expect(isOpen(idx, toggle(idx, s, 'vehicles'), 'vehicles')).toBe(false)
    expect(toggle(idx, s, 'staff')).toEqual(s)  // no children: nothing to fold
  })
  it('expand all below opens the whole subtree; collapse all below folds it again', () => {
    const open = expandSubtree(idx, mainAreas(), 'fields')
    expect(visible(idx, open)).toEqual(['farm', 'vehicles', 'fields', 'south', 'f704', 'f705', 'f705a', 'staff'])
    const shut = collapseSubtree(idx, open, 'fields')
    expect(visible(idx, shut)).toEqual(['farm', 'vehicles', 'fields', 'staff'])
    expect(visible(idx, openNode(idx, shut, 'fields'))).toEqual(['farm', 'vehicles', 'fields', 'south', 'staff'])  // one level
  })
  it('collapse all below also folds children that were open by default', () => {
    const s = collapseSubtree(idx, expandAll(idx), 'fields')
    expect(visible(idx, openNode(idx, s, 'fields'))).toEqual(['farm', 'vehicles', 'tractors', 'jd1', 'jd2', 'fields', 'south', 'staff'])
  })
})

describe('revealing a node', () => {
  it('opens only the path, through several folded levels', () => {
    const s = reveal(idx, collapseAll(idx), 'f705a')
    expect(visible(idx, s)).toEqual(['farm', 'vehicles', 'fields', 'south', 'f704', 'f705', 'f705a', 'staff'])
    expect(isOpen(idx, s, 'vehicles')).toBe(false)
  })
  it('ancestors and descendants', () => {
    expect(ancestors(idx, 'f705a')).toEqual(['f705', 'south', 'fields', 'farm'])
    expect(descendants(idx, 'south').sort()).toEqual(['f704', 'f705', 'f705a'])
  })
  it('a node that is gone changes nothing', () => {
    const s = mainAreas()
    expect(reveal(idx, s, 'nope')).toBe(s)
  })
})

describe('live changes in folded branches', () => {
  it('the nearest visible ancestor is where a hidden change shows', () => {
    expect(nearestVisible(idx, mainAreas(), 'f705a')).toBe('fields')
    expect(nearestVisible(idx, collapseAll(idx), 'jd1')).toBe('farm')
    expect(nearestVisible(idx, expandAll(idx), 'jd1')).toBe('jd1')
  })
  it('a node added while folded stays hidden and counts in the badge', () => {
    const s = mainAreas()
    const before = hiddenSummary(idx, s, () => ({})).get('fields')!.count
    const grown = indexTree([...FARM, { id: 'f706', parent_id: 'south' }])
    expect(visible(grown, s)).not.toContain('f706')
    expect(hiddenSummary(grown, s, () => ({})).get('fields')!.count).toBe(before + 1)
  })
  it('a node moved while folded goes where its new parent is', () => {
    const s = openNode(idx, mainAreas(), 'vehicles')
    const moved = indexTree(FARM.map((n) => (n.id === 'tractors' ? { ...n, parent_id: 'staff' } : n)))
    expect(visible(moved, s)).not.toContain('tractors')  // staff is folded
    expect(nearestVisible(moved, s, 'jd1')).toBe('staff')
    expect(visible(moved, openNode(moved, s, 'staff'))).toContain('tractors')
  })
  it('state that names tombstoned nodes is pruned', () => {
    const s = { depth: 1, expanded: ['fields', 'south', 'gone'], collapsed: ['farm', 'gone2'] }
    const t = indexTree(FARM.filter((n) => n.id !== 'south' && n.parent_id !== 'south' && n.id !== 'f705a'))
    expect(prune(t, s)).toEqual({ depth: 1, expanded: ['fields'].filter(() => (t.children.get('fields')?.length ?? 0) > 0), collapsed: ['farm'] })
    expect(prune(idx, s)).toEqual({ depth: 1, expanded: ['fields', 'south'], collapsed: ['farm'] })
  })
})

describe('hidden summary', () => {
  const stats = (id: string) => ({ jd2: { status: 'critical', alerts: 1, tasks: 2 }, f705a: { status: 'warning', tasks: 1 },
    f704: { status: 'done' } } as Record<string, { status?: string; alerts?: number; tasks?: number }>)[id]
  it('counts what a folded node hides and keeps the worst status', () => {
    const h = hiddenSummary(idx, mainAreas(), stats)
    expect(h.get('vehicles')).toEqual({ count: 3, alerts: 1, tasks: 2, worst: 'critical' })
    expect(h.get('fields')).toEqual({ count: 4, alerts: 0, tasks: 1, worst: 'warning' })
    expect(h.has('staff')).toBe(false)  // nothing under it
    expect(h.has('farm')).toBe(false)   // open
  })
  it('badge text', () => {
    expect(badgeText({ count: 14, alerts: 2, tasks: 3, worst: 'ok' })).toBe('+14 · 2 alerts · 3 tasks')
    expect(badgeText({ count: 1, alerts: 1, tasks: 0, worst: 'ok' })).toBe('+1 · 1 alert')
  })
})

describe('storage', () => {
  it('serialises small and reads back', () => {
    const s = openNode(idx, collapseSubtree(idx, setDepth(idx, 2), 'vehicles'), 'south')
    const text = serialize(s)
    expect(text.length).toBeLessThan(80)
    expect(parse(text)).toEqual(s)
  })
  it('rejects anything that is not a fold state', () => {
    for (const bad of [null, '', 'nope', '{"v":2}', '{"v":1,"d":"x","e":[],"c":[]}', '[]']) expect(parse(bad)).toBeNull()
    expect(parse('{"v":1,"d":-4,"e":[1,"a"],"c":[]}')).toEqual({ depth: 0, expanded: ['a'], collapsed: [] })
  })
})
