---
title: Second Brain & Cross-Project Knowledge Map
owner: Bambu (Bambú)
kind: icm-map
---

# Second Brain & GitHub Knowledge Map

- **Inputs:** Bambu's Second Brain markdown directory (`OS1_SECOND_BRAIN_DIR`), this repo's `icm/` and `docs/` shelves, and all `executiveusa/*` GitHub repositories.
- **Process:** `services/orchestrator/os1_orchestrator/wiki.py` indexes every note and repository into SQLite (`wiki.db`) with FTS5 search and directed graph edges (`wikilink`, `shared_stack`, `depends_on`, `icm_compatible`). `github_graph.py` scans cross-repo connections and proposes high-leverage node links.
- **Outputs:** Queryable SQLite LLM Wiki (`/os1/wiki/*`), cross-project graph recommendations (`/os1/github/connections`), and visual cards in OS¹.
- **Linked Nodes:** [[icm/context/PRODUCT.md]], [[icm/context/ARCHITECTURE.md]], [[icm/_shared/ICM_RULES.md]]
