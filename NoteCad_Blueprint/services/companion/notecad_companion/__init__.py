"""NoteCad Companion: a small on-device model that learns its owner.

Layers of learning (see docs/adr/0007-owner-companion-model.md):
  1. Memory     - facts, episodic memories with embeddings, vocabulary, daily rhythm.
  2. Behaviour  - reply style chosen by Thompson sampling, updated from feedback and edits.
  3. Weights    - accepted / edited replies exported for a per-owner LoRA adapter.
"""

__version__ = "0.1.0"
PROVENANCE = {"pipeline": f"notecad-companion {__version__}"}
