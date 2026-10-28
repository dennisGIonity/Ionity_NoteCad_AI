// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// The whole map, live: when a note lands, the changed nodes pulse and the view glides to them.
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, ReactFlowProvider, useNodesState, useReactFlow,
  type Node, type NodeMouseHandler,
} from '@xyflow/react'
import { AlertTriangle, Bell, ChevronsDownUp, ChevronsUpDown, Inbox, ListTodo, Loader2, Maximize2, Network, Orbit, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { ancestors, buildGraph, type CardData } from '../lib/layout'
import { useApp } from '../lib/store'
import { cls, statusColor } from '../lib/ui'
import { nodeTypes } from './nodes/Cards'

function Toolbar() {
  const { map, layout, setLayout, workspaces, ws, switchWorkspace, collapsed } = useApp()
  const { fitView, zoomIn, zoomOut } = useReactFlow()
  if (!map) return null
  const s = map.stats
  const cats = map.nodes.filter((n) => n.type === 'category' && n.depth >= 1).map((n) => n.id)
  const anyCollapsed = Object.values(collapsed).some(Boolean)
  const btn = 'grid size-8 place-items-center rounded-lg text-slate-300 hover:bg-white/10 hover:text-white'
  return (
    <div className="nc-glass pointer-events-auto absolute left-4 top-4 z-10 flex flex-wrap items-center gap-2 rounded-2xl px-3 py-2">
      {workspaces.length > 1 ? (
        <select value={ws} onChange={(e) => void switchWorkspace(e.target.value)} aria-label="Workspace"
          className="max-w-52 truncate rounded-lg bg-transparent py-1 pr-1 text-sm font-semibold text-slate-100 focus:outline-none">
          {workspaces.map((w) => <option key={w.id} value={w.id} className="bg-slate-900">{w.name}</option>)}
        </select>
      ) : <span className="text-sm font-semibold text-slate-100">{map.workspace.name}</span>}
      <div className="mx-1 h-5 w-px bg-white/10" />
      <span title="Open alerts" className="flex items-center gap-1 text-xs text-rose-200"><AlertTriangle className="size-3.5" />{s.open_alerts}</span>
      <span title="Open tasks" className="flex items-center gap-1 text-xs text-sky-200"><ListTodo className="size-3.5" />{s.open_tasks}</span>
      <span title="Overdue" className="flex items-center gap-1 text-xs text-amber-200"><Bell className="size-3.5" />{s.overdue_tasks}</span>
      {s.inbox > 0 && <span title="Waiting in the Inbox" className="flex items-center gap-1 text-xs text-amber-200"><Inbox className="size-3.5" />{s.inbox}</span>}
      <div className="mx-1 h-5 w-px bg-white/10" />
      {/* biome-ignore lint/a11y/useSemanticElements: a segmented control, not a form fieldset */}
      <div className="flex rounded-lg bg-white/5 p-0.5" role="group" aria-label="Layout">
        <button type="button" onClick={() => setLayout('tree')} title="Tree layout" aria-pressed={layout === 'tree'}
          className={cls('grid size-7 place-items-center rounded-md', layout === 'tree' ? 'bg-sky-500/25 text-sky-200' : 'text-slate-400 hover:text-white')}><Network className="size-4" /></button>
        <button type="button" onClick={() => setLayout('radial')} title="Radial layout" aria-pressed={layout === 'radial'}
          className={cls('grid size-7 place-items-center rounded-md', layout === 'radial' ? 'bg-sky-500/25 text-sky-200' : 'text-slate-400 hover:text-white')}><Orbit className="size-4" /></button>
      </div>
      <button type="button" className={btn} title={anyCollapsed ? 'Expand all' : 'Collapse categories'}
        onClick={() => useApp.setState({ collapsed: anyCollapsed ? {} : Object.fromEntries(cats.filter((id) => map.nodes.find((n) => n.id === id)!.depth >= 2).map((id) => [id, true])) })}>
        {anyCollapsed ? <ChevronsUpDown className="size-4" /> : <ChevronsDownUp className="size-4" />}
      </button>
      <button type="button" className={btn} title="Zoom out" onClick={() => zoomOut({ duration: 200 })}><ZoomOut className="size-4" /></button>
      <button type="button" className={btn} title="Zoom in" onClick={() => zoomIn({ duration: 200 })}><ZoomIn className="size-4" /></button>
      <button type="button" className={btn} title="Fit to screen" onClick={() => fitView({ duration: 500, padding: 0.12 })}><Maximize2 className="size-4" /></button>
    </div>
  )
}

function Flow() {
  const { map, layout, collapsed, highlights, selected, select, focusRequest, mapError } = useApp()
  const { fitView, getNode } = useReactFlow()
  const laid = useMemo(
    () => (map ? buildGraph(map, { collapsed, radial: layout === 'radial', highlights, selected }) : { nodes: [], edges: [] }),
    [map, collapsed, layout, highlights, selected],
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<CardData>>([])
  const first = useRef(true)

  useEffect(() => { setNodes(laid.nodes) }, [laid.nodes, setNodes])
  // biome-ignore lint/correctness/useExhaustiveDependencies: fit once per layout switch and on the first draw
  useEffect(() => {
    if (!laid.nodes.length) return
    const t = setTimeout(() => fitView({ duration: first.current ? 0 : 500, padding: 0.12 }), 30)
    first.current = false
    return () => clearTimeout(t)
  }, [layout, fitView, laid.nodes.length === 0])  // eslint-disable-line react-hooks/exhaustive-deps

  // a note landed: open collapsed branches, then glide to what changed
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs per focus request and per new map, not per render
  useEffect(() => {
    if (!focusRequest || !map) return
    const ids = focusRequest.ids.filter((id) => map.nodes.some((n) => n.id === id))
    if (!ids.length) return
    const shut = ids.flatMap((id) => ancestors(map, id)).filter((a) => collapsed[a])
    if (shut.length) useApp.setState((s) => ({ collapsed: { ...s.collapsed, ...Object.fromEntries(shut.map((a) => [a, false])) } }))
    const t = setTimeout(() => {
      const present = ids.filter((id) => getNode(id))
      if (present.length) fitView({ nodes: present.map((id) => ({ id })), duration: 900, padding: present.length > 1 ? 0.35 : 1.2, maxZoom: 1.15 })
    }, 420)
    return () => clearTimeout(t)
  }, [focusRequest?.at, map?.generated_at])  // eslint-disable-line react-hooks/exhaustive-deps

  const onClick: NodeMouseHandler<Node<CardData>> = (_, n) => {
    const m = n.data.node
    if (m.type === 'task') select(m.parent_id)
    else if (m.type === 'member') select(m.person_node_id ?? null)
    else if (!m.virtual) select(m.id)
  }

  if (!map) {
    return (
      <div className="grid h-full place-items-center text-sm text-slate-400">
        {mapError ? <p className="max-w-md text-center">{mapError}</p> : <Loader2 className="size-6 animate-spin" />}
      </div>
    )
  }
  return (
    <ReactFlow
      nodes={nodes}
      edges={laid.edges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onNodeClick={onClick}
      onPaneClick={() => select(null)}
      nodesConnectable={false}
      minZoom={0.15}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      colorMode="dark"
      onlyRenderVisibleElements
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="rgba(148,163,184,0.18)" />
      {!selected && <MiniMap pannable zoomable position="bottom-left" className="!rounded-xl !border !border-white/10 !bg-slate-900/70"
        maskColor="rgba(2,6,23,0.6)" nodeColor={(n) => statusColor((n.data as CardData).node.display_status)} nodeStrokeWidth={0} />}
      <Toolbar />
    </ReactFlow>
  )
}

export function MindMap() {
  return (
    <ReactFlowProvider>
      <Flow />
    </ReactFlowProvider>
  )
}
