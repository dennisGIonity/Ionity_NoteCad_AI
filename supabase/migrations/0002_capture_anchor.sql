-- Ionity NoteCad | Ionity Global (Pty) Ltd | AEDI
-- Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
-- Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
-- Phase 2: context-anchored recording. The node the owner had open on the mind map while recording; the brain
-- boosts it and its 1-hop neighbours when it picks where the note goes. Same column as services/brain db.py.

alter table captures add column if not exists anchor_node_id text references nodes(id) on delete set null;
create index if not exists captures_anchor on captures(anchor_node_id) where anchor_node_id is not null;
