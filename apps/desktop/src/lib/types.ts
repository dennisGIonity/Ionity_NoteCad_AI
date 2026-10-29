// Ionity NoteCad - Desktop | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
// Shapes of the brain API (services/brain/notecad_brain/mindmap.py and pipeline.py).

export type Status = 'done' | 'pending' | 'ok' | 'info' | 'routine_due' | 'warning' | 'critical'
export type MapNodeType = 'root' | 'category' | 'entity' | 'task' | 'member'

export interface Progress {
  pct: number
  source: string
  verb: string | null
  unit: string | null
  done: number | null
  total: number | null
  of?: number
}

export interface Decay {
  state: 'fresh' | 'fading' | 'settled' | 'active'
  score: number
  since?: string | null
  expires_at?: string | null
}

export interface Reminder {
  task_id: string
  title: string
  due_at: string | null
  state: 'overdue' | 'due_soon' | 'scheduled'
  priority: string
  assignee: string | null
}

export interface NoteRef {
  note_id: string
  body: string
  created_at: string
  channel: string | null
  provenance: { capture_id: string | null; author: string; router: string | null; source: string | null; recorded_at: string | null; context_node_id: string | null }
}

export interface Counts {
  open_tasks: number
  open_alerts: number
  done_tasks?: number
  overdue_tasks: number
  subtree_open_tasks?: number
  subtree_open_alerts?: number
  subtree_overdue_tasks?: number
  entities?: number
  entities_needing_work?: number
  members?: number
  delegated_open_tasks?: number
}

export interface MapNode {
  id: string
  type: MapNodeType
  kind: string
  title: string
  parent_id: string | null
  depth: number
  path?: string
  virtual?: boolean
  status?: Status
  status_reason?: string | null
  display_status?: Status
  child_worst?: Status
  echo_dot?: boolean
  echo_status?: Status | null
  decay?: Decay
  counts: Counts
  progress_pct?: number | null
  progress?: Progress | null
  reminders?: Reminder[]
  alerts?: { alert_id: string; severity: string; category: string; title: string; created_at: string; channel: string | null }[]
  recent_notes?: NoteRef[]
  channels?: { id: string; title: string; display_status: Status; open_tasks: number; open_alerts: number }[]
  attributes?: Record<string, unknown>
  updated_at?: string
  needs_work?: boolean
  // task leaves
  task_id?: string
  node_id?: string
  channel?: string | null
  priority?: string
  due_at?: string | null
  due_state?: Reminder['state']
  assignee?: string | null
  assignee_member?: string | null
  // members
  role?: string
  member_id?: string
  person_node_id?: string | null
  // ADR 0014: who may see it, and a path stub (a scoped member sees only its title)
  visibility?: 'all' | 'manager' | 'owner'
  eff_level?: number
  stub?: boolean
}

export interface MapEdge {
  id: string
  type: 'belongs_to_category' | 'has_task' | 'assigned_to' | 'related_to'
  source: string
  target: string
  relation?: string
}

export interface MindMap {
  workspace: { id: string; name: string; persona: string | null; locale: string }
  generated_at: string
  cursor: number
  root: string
  stats: { nodes: number; entities: number; open_tasks: number; open_alerts: number; overdue_tasks: number; inbox: number; progress_pct: number | null; nodes_needing_work?: number }
  nodes: MapNode[]
  edges: MapEdge[]
}

export interface Workspace { id: string; name: string; persona: string | null; created_at: string; nodes: number }

export interface LiveEvent {
  id: number
  type: string
  workspace_id: string
  at: string
  capture_id?: string
  [k: string]: unknown
}

export interface AppliedNode { id: string; title: string; kind: string; path: string; map_id: string; map_path: string }
export interface InboxOption { label: string; node_id: string }

export interface CaptureView {
  id: string
  state: 'recording' | 'uploading' | 'queued' | 'transcribing' | 'routing' | 'applied' | 'needs_review' | 'failed' | 'undone'
  kind: 'audio' | 'text'
  contextNodeId: string | null
  startedAt: number
  transcript?: string
  events: number
  resolving?: { idx: number; text: string }
  applied: { idx: number; nodes: AppliedNode[]; actions: string[]; tasks: number; alerts: number; notes: number; delegated: { to: string }[] }[]
  inbox: { inbox_id: string; idx: number; text: string; question: string; options: InboxOption[]; resolved?: string; dismissed?: boolean }[]
  error?: string
  finishedAt?: number
  /** ADR 0014: what the brain said back (a spoken admin command), and what the speaker may not do */
  answer?: string
  refused?: string[]
  proposal?: string
}

export interface NodeDetail {
  id: string
  title: string
  kind: string
  status: Status
  display_status: Status
  path_titles: string
  attributes: Record<string, unknown>
  aliases: string[]
  notes: { id: string; body: string; created_at: string; author: string; capture_id: string | null; node_id: string }[]
  tasks: { id: string; title: string; state: string; due_at: string | null; priority: string; assignee_member: string | null; assignee_hint: string | null; node_id: string }[]
  alerts: { id: string; title: string; severity: string; resolved_at: string | null; created_at: string; node_id: string }[]
  children: { id: string; title: string; kind: string; display_status: Status }[]
}

export interface HistoryItem {
  id: string
  at: string
  type: string
  capture_id: string | null
  actor: string
  router: string | null
  undone: boolean
  capture_text: string | null
  source: string | null
  audio?: boolean
  channel: string | null
  detail: Record<string, unknown>
}

export interface SyncStatus {
  db: string
  ok: boolean
  integrity: string
  journal_mode?: string
  size_bytes?: number
  wal_bytes?: number
  pending: { sync_events: number; jobs_queued: number; jobs_failed: number; notifications_unsent: number; inbox_open: number; captures_in_flight: number }
  last_event_id: number
  worker: boolean
  sync?: SyncPeerStatus
  sync_target?: string | null
  checked_ms: number
  at: string
}

/** Multi-worker sync (Phase 5): this brain against the Edge AI Node or Supabase. */
export interface SyncPeerStatus {
  worker_id: string
  target: string | null
  peer: string | null
  interval_s: number | null
  workspaces: string[] | null
  pending_changes: number | null
  journal_seq: number
  last_sync_at: string | null
  last_error: string | null
  pushed: number
  pulled: number
}

export interface SyncRunResult {
  ok: boolean
  error?: string
  pushed?: number
  pulled?: number
  applied?: number
}

/** GET /api/v1/pairing - shown on this PC only. */
export interface Pairing {
  lan: boolean
  token_set: boolean
  urls: string[]
  workspace: string | null
  workspaces: { id: string; name: string }[]
  links: string[]
  ready: boolean
  hint: string | null
}

// ---------------------------------------------------------------- roles, seats, people (ADR 0014)
export type Outcome = 'allow' | 'confirm' | 'propose' | 'refuse'
export interface Me {
  workspace_id: string
  member_id: string | null
  name: string | null
  level: number
  role: 'system' | 'owner' | 'manager' | 'employee'
  read_only: boolean
  scopes: string[]
  device_id: string | null
  capabilities: Record<string, Outcome>
}
export interface Member {
  id: string; display_name: string; role: string; level: number; status: string; contact: string | null
  person_node_id: string | null; seat_id: string | null; read_only: number
}
/** POPIA: how long a workspace keeps things (days; null keeps until deleted). */
export interface Retention { audio_days: number | null; transcript_days: number | null; log_days: number | null }
export interface PrivacyNotice {
  version: number; business: string; owners: string[]; contact: string | null; accepted_at: string | null
  retention: Retention; retention_text: string; recommended: Retention
  cloud: { claude: boolean; deepgram: boolean; sync: string | null }; my_ack_at: string | null; is_owner: boolean
}
export interface Seat { id: string; role_level: number; status: string; assigned_member_id?: string | null; member_name?: string | null }
export interface Invite {
  id: string; seat_id: string; created_by: string | null; created_at: string; expires_at: string; used_at: string | null
  revoked_at: string | null; profile: { name: string; role: string; contact?: string | null; scope_node_ids?: string[] }
}
export interface Device {
  id: string; member_id: string; member_name?: string | null; name: string; platform: string | null; created_at: string
  last_seen_at: string | null; revoked_at: string | null; wipe_acked_at: string | null
}
export interface InboxItem {
  id: string; kind: 'place' | 'approval' | 'sync'; question: string; event_text: string | null; capture_id: string | null
  options: string | InboxOption[]; author_member_id: string | null; created_at: string
}
