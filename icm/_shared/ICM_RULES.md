---
title: ICM Architecture Rules & Policy Tiers
kind: icm-rules
---

# ICM Rules (Mandatory for All Code Samantha Writes)

Every module, folder, and self-update produced by Samantha OS¹ MUST enforce the 10 ICM invariants:

1. **One folder, one job.** Each directory has a single responsibility and documents it in `CONTEXT.md`.
2. **Small, stable catalog.** Root routing files (`AGENTS.md`, `icm/CONTEXT.md`) stay concise and point to shelves rather than stuffing content.
3. **Numbering encodes order.** Pipeline stages use `01_`..`05_` prefixes.
4. **Explicit folder contracts.** Every stage/module folder defines Inputs, Process, Outputs, and Verification Gate in `CONTEXT.md`.
5. **Factory vs. product.** Reusable rules, schemas, templates, and skills stay separate from per-run outputs and state.
6. **Every output is an edit surface.** Plans, wiki pages, and graph reports are plain Markdown + YAML frontmatter Bambu can inspect and edit.
7. **Load only what the step needs.** Keep per-step context lean (2k–8k tokens).
8. **Plain text, linkable, queryable.** Use `[[wikilinks]]` and YAML frontmatter so the SQLite LLM Wiki indexes every node and edge cleanly.
9. **Filesystem is the state machine.** Status is observable from files and SQLite state, never hidden memory.
10. **Policy-tiered action gates (L0–L4):**
    - **L0 (Read/Classify):** Gesture classification, wiki search, GitHub read, bot status/logs — immediate.
    - **L1 (Reversible Local):** Surface switch, undoable triage — immediate with 60 s undo.
    - **L2 (Standing Policy):** Approved connectors and scheduled summaries.
    - **L3 (Human Approval):** Outbound messages, Maus Bot restarts/deploys, destructive git/ops — requires server-verified one-time `approval_id`.
    - **L4 (Hard Deny):** Secret exfiltration, unapproved shell/keychain access, destructive DB drops.
