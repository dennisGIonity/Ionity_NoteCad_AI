-- Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
-- Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
-- Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-- Phase 3: sync readiness. A change in action_log is pending until another worker has it (Phase 4 multi-worker sync).
-- The desktop shows the pending count in its corner indicator. Same column as services/brain db.py.

alter table action_log add column if not exists synced_at text;
create index if not exists action_log_unsynced on action_log(workspace_id) where synced_at is null;
