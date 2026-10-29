// Ionity Business Mind Map (IBMM) - Desktop | Ionity Global (Pty) Ltd | AEDI
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
import {
  Beef, Briefcase, Building2, Car, Droplets, Fence, Folder, Leaf, MapPin, Package, Sprout, Tractor, Truck, User, Users,
  Wrench, type LucideIcon,
} from 'lucide-react'
import type { MapNode, Status } from './types'

export const STATUS_COLOR: Record<Status, string> = {
  critical: '#f43f5e', warning: '#f59e0b', routine_due: '#fb923c', info: '#38bdf8', ok: '#34d399', done: '#22c55e', pending: '#94a3b8',
}
export const STATUS_LABEL: Record<Status, string> = {
  critical: 'Critical', warning: 'Warning', routine_due: 'Due', info: 'New note', ok: 'OK', done: 'Done', pending: 'Pending',
}
export const statusColor = (s?: Status | null) => STATUS_COLOR[s ?? 'ok'] ?? STATUS_COLOR.ok

const ICONS: [RegExp, LucideIcon][] = [
  [/tractor|trekker|john deere|case|magnum|harvester|combine/i, Tractor],
  [/vehicle|voertuie|bakkie|hilux|truck|lorry/i, Truck],
  [/car|motor/i, Car],
  [/field|land|block|crop|oes|bean|bone|maize|mielie|wheat|soya/i, Sprout],
  [/livestock|cattle|beeste|sheep|skape|cow|calf|vee/i, Beef],
  [/water|pump|pomp|borehole|boorgat|pivot|dam/i, Droplets],
  [/fenc|draad|heining/i, Fence],
  [/infra|building|shed|store/i, Building2],
  [/staff|people|team|personeel/i, Users],
  [/admin|finance|compliance/i, Briefcase],
  [/maintenance|workshop|onderhoud/i, Wrench],
  [/paddock|camp|kamp|place/i, MapPin],
  [/garden|tree|orchard/i, Leaf],
]

export function iconFor(n: Pick<MapNode, 'title' | 'kind' | 'type'>): LucideIcon {
  if (n.type === 'member' || n.kind === 'person') return User
  const hit = ICONS.find(([re]) => re.test(n.title))
  if (hit) return hit[1]
  if (n.kind === 'field') return Sprout
  if (n.kind === 'asset') return Package
  return Folder
}

export function ago(iso?: string | null, now = Date.now()): string {
  if (!iso) return ''
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export function due(iso?: string | null, now = Date.now()): string {
  if (!iso) return ''
  const d = new Date(iso)
  const days = Math.round((d.getTime() - now) / 86400000)
  const day = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })
  if (d.getTime() < now) return `overdue · ${day}`
  if (days <= 0) return `today ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`
  if (days === 1) return 'tomorrow'
  return day
}

export const fmtBytes = (n?: number) => (n == null ? '–' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`)

export function progressLabel(n: MapNode): string | null {
  const p = n.progress
  if (!p) return null
  const verb = p.verb && p.verb !== 'average' ? p.verb[0].toUpperCase() + p.verb.slice(1) : 'Progress'
  return `${verb} ${Math.round(p.pct)}%`
}

export const cls = (...xs: (string | false | null | undefined)[]) => xs.filter(Boolean).join(' ')
