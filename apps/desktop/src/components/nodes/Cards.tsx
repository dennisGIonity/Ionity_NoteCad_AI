// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Mind map cards: root, category (progress ring, alert badge, collapse), asset (status ring, echo dot, tasks,
// reminder badge), field (progress fill, last update, decay), task leaf, member.
import * as F from '@notecad/core/fold'
import { Handle, Position, useStore, type NodeProps, type Node, type ReactFlowState } from '@xyflow/react'
import { AlertTriangle, Bell, ChevronDown, ChevronRight, CircleDot, ListTodo, Lock, Users } from 'lucide-react'
import { memo, type MouseEvent, type ReactNode } from 'react'
import type { CardData } from '../../lib/layout'
import { useApp } from '../../lib/store'
import type { MapNode, Status } from '../../lib/types'
import { ago, cls, due, iconFor, progressLabel, STATUS_LABEL, statusColor } from '../../lib/ui'

type P = NodeProps<Node<CardData>>

/** ADR 0014: a lock and its level on a branch restricted itself; a faint lock where it is restricted from above. */
export function LockBadge({ n }: { n: MapNode }) {
  const lvl = n.eff_level ?? 3
  if (lvl >= 3) return null
  const own = (n.visibility ?? 'all') !== 'all'
  const who = lvl === 1 ? 'owners' : 'managers'
  return (
    <span data-lock={who} title={own ? `Only ${who} see this branch` : `Only ${who} see this (set on a branch above)`}
      className={cls('inline-flex shrink-0 items-center gap-0.5 rounded-full px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide',
        own ? 'bg-amber-400/20 text-amber-100' : 'text-amber-200/50')}>
      <Lock className="size-2.5" />{own && who}
    </span>
  )
}

function Handles() {
  const hide = '!size-1 !min-h-0 !min-w-0 !border-0 !bg-transparent'
  return (
    <>
      <Handle type="target" position={Position.Left} id="t" className={hide} isConnectable={false} />
      <Handle type="source" position={Position.Right} id="s" className={hide} isConnectable={false} />
      <Handle type="target" position={Position.Top} id="ct" className={hide} style={{ top: '50%', left: '50%' }} isConnectable={false} />
      <Handle type="source" position={Position.Top} id="cs" className={hide} style={{ top: '50%', left: '50%' }} isConnectable={false} />
    </>
  )
}

function Shell({ data, selected, className, children }: { data: CardData; selected?: boolean; className?: string; children: ReactNode }) {
  const st = data.node.display_status ?? 'ok'
  const hot = st === 'critical' || st === 'warning'
  return (
    <div
      className={cls('nc-card group relative rounded-2xl border px-3 py-2.5 text-slate-100 transition-[box-shadow,transform,border-color] duration-300',
        selected ? 'border-sky-400/80 ring-2 ring-sky-400/40' : hot ? 'border-white/15' : 'border-white/10',
        data.highlight && 'nc-pulse', className)}
      style={{ ['--st' as string]: statusColor(st) }}
    >
      <Handles />
      {hot && <span className="pointer-events-none absolute inset-0 rounded-2xl" style={{ boxShadow: `inset 0 0 0 1px ${statusColor(st)}55, 0 0 22px -6px ${statusColor(st)}` }} />}
      {children}
    </div>
  )
}

function EchoDot({ n }: { n: MapNode }) {
  if (!n.echo_dot || !n.echo_status) return null
  return (
    <span title={`Something under this is ${STATUS_LABEL[n.echo_status]}`} className="absolute -right-1 -top-1 flex size-3.5">
      <span className="absolute inline-flex size-full animate-ping rounded-full opacity-60" style={{ background: statusColor(n.echo_status) }} />
      <span className="relative inline-flex size-3.5 rounded-full border-2 border-slate-900" style={{ background: statusColor(n.echo_status) }} />
    </span>
  )
}

export function Ring({ pct, size = 44, stroke = 4, color = '#34d399', children }: { pct: number | null | undefined; size?: number; stroke?: number; color?: string; children?: ReactNode }) {
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const v = Math.max(0, Math.min(100, pct ?? 0))
  return (
    <div className="relative grid shrink-0 place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="rgba(148,163,184,0.18)" strokeWidth={stroke} fill="none" />
        {pct != null && (
          <circle cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: 'stroke-dashoffset 900ms cubic-bezier(.2,.8,.2,1)' }} />
        )}
      </svg>
      <div className="absolute inset-0 grid place-items-center">{children}</div>
    </div>
  )
}

/** Zoom decides how much a visible card shows; the fold decides which cards exist. Below this zoom cards show
 *  their title, status and fold badge only. One boolean per card, so zooming re-renders a card only at the line. */
const FAR = 0.55
const isFar = (s: ReactFlowState) => s.transform[2] < FAR
export const useFar = () => useStore(isFar)
export const TINY = 0.4
export const isTiny = (s: ReactFlowState) => s.transform[2] < TINY
/** Far out (a whole farm on screen) a card is a status-coloured tile with its title: hundreds of them pan smoothly. */
function Tiny({ data, selected }: { data: CardData; selected?: boolean }) {
  const st = data.node.display_status ?? 'ok'
  const [w, h] = SIZES[data.card]
  return (
    <div className={cls('nc-tiny rounded-2xl border-4 bg-slate-900 px-3 py-2 text-lg font-semibold text-slate-100', data.highlight && 'nc-pulse')}
      style={{ width: w, height: h, borderColor: selected ? '#38bdf8' : statusColor(st === 'ok' ? null : st) }}>
      <div className="truncate">{data.node.title}</div>
      {data.hidden && !data.open && <div className="truncate text-base text-slate-400">{F.badgeText(data.hidden)}</div>}
    </div>
  )
}
const SIZES: Record<CardData['card'], [number, number]> = { root: [250, 96], category: [250, 104], asset: [260, 104], field: [260, 116], task: [230, 52], member: [210, 60] }

/** Chevron on every node with children; folded, it carries what it hides: "+14 · 2 alerts · 3 tasks" in the colour
 *  of the worst status underneath. Click: next level only. Shift+click: the whole branch. */
function Fold({ data }: { data: CardData }) {
  if (!data.foldable) return null
  const id = data.node.id
  const h = data.hidden
  const act = (e: MouseEvent) => {
    e.stopPropagation()
    const app = useApp.getState()
    const t = app.foldTree()
    if (!t) return
    const s = app.fold
    const next = e.shiftKey ? (data.open ? F.collapseSubtree(t.idx, s, id) : F.expandSubtree(t.idx, s, id)) : F.toggle(t.idx, s, id)
    app.setFold(next, id)
  }
  const tone = h && STATUS_RANK_HOT.has(h.worst) ? statusColor(h.worst as Status) : undefined
  return (
    <button
      type="button"
      tabIndex={-1}
      data-fold-toggle={id}
      onClick={act}
      aria-label={data.open ? `Fold ${data.node.title}` : `Show what is under ${data.node.title}${h ? `: ${F.badgeText(h)}` : ''}`}
      title={data.open ? 'Fold (Shift: the whole branch)' : 'Show the next level (Shift: the whole branch)'}
      className={cls('nodrag absolute -right-3 top-1/2 flex h-6 -translate-y-1/2 items-center gap-1 rounded-full border bg-slate-800 px-1 text-[10px] font-semibold text-slate-200 shadow hover:bg-slate-700',
        tone ? 'border-transparent' : 'border-white/15')}
      style={tone ? { boxShadow: `0 0 0 1.5px ${tone}` } : undefined}
    >
      {!data.open && h && <span data-fold-badge className="whitespace-nowrap pl-1">{F.badgeText(h)}</span>}
      {data.open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
    </button>
  )
}
const STATUS_RANK_HOT = new Set(['critical', 'warning', 'routine_due'])

function Badge({ icon, n, tone, title }: { icon: ReactNode; n: number; tone: 'alert' | 'task' | 'due'; title: string }) {
  if (!n) return null
  const c = tone === 'alert' ? 'bg-rose-500/20 text-rose-200' : tone === 'due' ? 'bg-amber-400/20 text-amber-100' : 'bg-sky-400/15 text-sky-100'
  return <span title={title} className={cls('flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold', c)}>{icon}{n}</span>
}

export const RootCard = memo(({ data, selected }: P) => {
  const n = data.node
  const Icon = iconFor(n)
  return (
    <Shell data={data} selected={selected} className="nc-root w-[250px] bg-gradient-to-br from-sky-500/20 via-slate-900/80 to-emerald-500/15 px-4 py-3">
      <div className="flex items-center gap-3">
        <Ring pct={n.progress_pct} size={52} stroke={5}><Icon className="size-5 text-sky-200" /></Ring>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold">{n.title}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge icon={<AlertTriangle className="size-3" />} n={n.counts.subtree_open_alerts ?? 0} tone="alert" title="Open alerts" />
            <Badge icon={<ListTodo className="size-3" />} n={n.counts.subtree_open_tasks ?? 0} tone="task" title="Open tasks" />
            <Badge icon={<Bell className="size-3" />} n={n.counts.subtree_overdue_tasks ?? 0} tone="due" title="Overdue" />
          </div>
        </div>
      </div>
      <EchoDot n={n} />
      <Fold data={data} />
    </Shell>
  )
})

export const CategoryCard = memo(({ data, selected }: P) => {
  const n = data.node
  const Icon = n.virtual ? Users : iconFor(n)
  const st = n.display_status ?? 'ok'
  const things = n.virtual ? `${n.counts.members ?? 0} people · ${n.counts.delegated_open_tasks ?? 0} delegated` : `${n.counts.entities ?? 0} asset${n.counts.entities === 1 ? '' : 's'}`
  return (
    <Shell data={data} selected={selected} className="w-[250px] bg-slate-900/85">
      <div className="flex items-center gap-3">
        <Ring pct={n.progress_pct} color="#34d399">
          <div className="grid size-8 place-items-center rounded-full" style={{ background: `${statusColor(st)}22` }}>
            <Icon className="size-4 text-slate-300" style={st === 'ok' || st === 'info' ? undefined : { color: statusColor(st) }} />
          </div>
        </Ring>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1"><span className="truncate text-sm font-semibold">{n.title}</span><LockBadge n={n} /></div>
          <div className="truncate text-[11px] text-slate-400">{things}{n.progress_pct != null && ` · ${Math.round(n.progress_pct)}%`}</div>
          <div className="mt-1 flex gap-1">
            <Badge icon={<AlertTriangle className="size-3" />} n={n.counts.subtree_open_alerts ?? 0} tone="alert" title="Open alerts under this" />
            <Badge icon={<ListTodo className="size-3" />} n={n.counts.subtree_open_tasks ?? 0} tone="task" title="Open tasks under this" />
            <Badge icon={<Bell className="size-3" />} n={n.counts.subtree_overdue_tasks ?? 0} tone="due" title="Overdue" />
          </div>
        </div>
      </div>
      <EchoDot n={n} />
      <Fold data={data} />
    </Shell>
  )
})

export const AssetCard = memo(({ data, selected }: P) => {
  const far = useFar()
  const n = data.node
  const Icon = iconFor(n)
  const st = n.display_status ?? 'ok'
  const reminders = n.reminders ?? []
  const overdue = reminders.filter((r) => r.state === 'overdue').length
  return (
    <Shell data={data} selected={selected} className="w-[260px] bg-slate-900/85">
      <div className="flex items-center gap-3">
        <div className="relative grid size-11 shrink-0 place-items-center rounded-full bg-slate-800" style={{ boxShadow: `0 0 0 3px ${statusColor(st)}` }}>
          <Icon className="size-5 text-slate-200" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1"><span className="truncate text-sm font-semibold" title={n.title}>{n.title}</span><LockBadge n={n} /></div>
          <div className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span style={{ color: statusColor(st) }}>{STATUS_LABEL[st]}</span>
            {n.channels?.some((c) => c.open_alerts) && <span>· {n.channels.find((c) => c.open_alerts)!.title}</span>}
          </div>
        </div>
        {reminders.length > 0 && (
          <span title={reminders.map((r) => `${r.title} (${due(r.due_at)})`).join('\n')}
            className={cls('flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-semibold', overdue ? 'bg-rose-500/25 text-rose-100' : 'bg-amber-400/20 text-amber-100')}>
            <Bell className="size-3" />{reminders.length}
          </span>
        )}
      </div>
      {data.tasks.length > 0 && !far && (
        <ul className="mt-2 space-y-1">
          {data.tasks.slice(0, 2).map((t) => (
            <li key={t.id} className="flex items-center gap-1.5 truncate text-[11px] text-slate-300">
              <CircleDot className={cls('size-3 shrink-0', t.due_state === 'overdue' ? 'text-rose-400' : t.priority === 'urgent' ? 'text-amber-300' : 'text-sky-300')} />
              <span className="truncate">{t.title}</span>
              {t.assignee && <span className="ml-auto shrink-0 rounded bg-white/5 px-1 text-[10px] text-slate-400">{t.assignee.split(' ')[0]}</span>}
            </li>
          ))}
          {data.tasks.length > 2 && <li className="pl-4 text-[10px] text-slate-500">+{data.tasks.length - 2} more</li>}
        </ul>
      )}
      <EchoDot n={n} />
      <Fold data={data} />
    </Shell>
  )
})

export const FieldCard = memo(({ data, selected }: P) => {
  const n = data.node
  const p = n.progress
  const pct = p?.pct ?? 0
  const label = progressLabel(n) ?? 'No progress yet'
  const st = n.display_status ?? 'ok'
  const decay = n.decay
  const area = typeof n.attributes?.area_ha === 'number' ? `${n.attributes.area_ha} ha` : null
  return (
    <Shell data={data} selected={selected} className="w-[260px] bg-slate-900/85">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-1"><span className="truncate text-sm font-semibold">{n.title}</span><LockBadge n={n} /></div>
          <div className="text-[11px] text-slate-400">{[area, n.attributes?.phase as string | undefined].filter(Boolean).join(' · ') || n.kind}</div>
        </div>
        {decay && decay.state !== 'settled' && (
          <span title={decay.state === 'active' ? STATUS_LABEL[st] : `Fresh update, fades ${decay.expires_at ? ago(decay.expires_at).replace(' ago', '') : ''}`}
            className="relative size-3 shrink-0 rounded-full" style={{ background: statusColor(decay.state === 'active' ? st : 'info'), opacity: 0.35 + 0.65 * decay.score }} />
        )}
      </div>
      <div className="mt-2.5">
        <div className="mb-1 flex items-baseline justify-between text-[11px]">
          <span className={cls('font-semibold', pct >= 100 ? 'text-emerald-300' : 'text-slate-200')}>{label}</span>
          {p?.done != null && p.total != null && p.unit && p.unit !== '%' && <span className="text-slate-400">{p.done} / {p.total} {p.unit}</span>}
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-white/10">
          <div className="nc-fill h-full rounded-full" style={{ width: `${Math.min(100, pct)}%`, background: pct >= 100 ? 'linear-gradient(90deg,#22c55e,#34d399)' : 'linear-gradient(90deg,#38bdf8,#34d399)' }} />
        </div>
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-500">
        <span>Updated {ago(n.updated_at)}</span>
        {data.tasks.length > 0 && <span className="flex items-center gap-1 text-sky-300"><ListTodo className="size-3" />{data.tasks.length}</span>}
      </div>
      <EchoDot n={n} />
      <Fold data={data} />
    </Shell>
  )
})

export const TaskCard = memo(({ data, selected }: P) => {
  const n = data.node
  const over = n.due_state === 'overdue'
  return (
    <div className={cls('nc-card relative flex w-[230px] items-center gap-2 rounded-xl border bg-slate-900/80 px-2.5 py-2 text-slate-200',
      selected ? 'border-sky-400/80' : over ? 'border-rose-400/40' : 'border-white/10', data.highlight && 'nc-pulse')}>
      <Handles />
      <CircleDot className={cls('size-3.5 shrink-0', over ? 'text-rose-400' : n.priority === 'urgent' ? 'text-amber-300' : 'text-sky-300')} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs">{n.title}</div>
        <div className="truncate text-[10px] text-slate-500">{[n.assignee, n.due_at && due(n.due_at), n.channel].filter(Boolean).join(' · ') || 'open task'}</div>
      </div>
    </div>
  )
})

export const MemberCard = memo(({ data, selected }: P) => {
  const n = data.node
  const initials = n.title.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div className={cls('nc-card relative flex w-[210px] items-center gap-2.5 rounded-xl border bg-slate-900/80 px-2.5 py-2',
      selected ? 'border-sky-400/80' : 'border-white/10', data.highlight && 'nc-pulse')}>
      <Handles />
      <div className="grid size-9 shrink-0 place-items-center rounded-full bg-violet-500/25 text-xs font-semibold text-violet-100">{initials}</div>
      <div className="min-w-0">
        <div className="truncate text-xs font-semibold text-slate-100">{n.title}</div>
        <div className="text-[10px] text-slate-400">{n.role} · {n.counts.open_tasks} open{n.counts.overdue_tasks ? ` · ${n.counts.overdue_tasks} overdue` : ''}</div>
      </div>
    </div>
  )
})

/** The tile far out, the full card from TINY zoom in; one boolean per card, so zooming re-renders at the line only. */
function withTiny(Full: (p: P) => ReactNode) {
  return memo((p: P) => (useStore(isTiny) ? <Tiny data={p.data} selected={p.selected} /> : <Full {...p} />))
}

export const nodeTypes = {
  root: withTiny(RootCard), category: withTiny(CategoryCard), asset: withTiny(AssetCard), field: withTiny(FieldCard),
  task: withTiny(TaskCard), member: withTiny(MemberCard),
}
