-- Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
-- Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
-- Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-- Phase 6 (ADR 0013): indexes for the queries the roll-up, the mind map, retrieval, Undo and sync status run on
-- every note. Same statements as migration 6 in services/brain/notecad_brain/db.py (tests/test_phase6.py checks).
create index if not exists tasks_node on tasks(node_id, state);
create index if not exists alerts_node on alerts(node_id, resolved_at);
create index if not exists nodes_parent on nodes(parent_id);
create index if not exists edges_dst on edges(dst_id);
create index if not exists inbox_capture on inbox(capture_id);
create index if not exists action_log_unsynced on action_log(workspace_id, synced_at);
