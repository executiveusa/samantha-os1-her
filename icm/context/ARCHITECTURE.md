---
title: Samantha OS1 — Architecture & Stage Contracts
owner: Bambu (Bambú)
kind: icm-context
---

# Architecture Context

- **Edge / Public Web:** Vercel multi-service (`vercel.json` → `desktop`, `orchestrator`, `voice`).
- **24/7 Stateful Core:** Hostinger Ubuntu VPS (`docker-compose.vps.yml` → Infisical, LiveKit, OpenCode, Orchestrator, Voice Worker, Brain Server, VisionClaw AX-022 Gateway, Tailscale).
- **Self-Evolution:** Lauren Tan's `pstack` (`.pstack/`) + ICM invariants (`icm/_shared/ICM_RULES.md`) enforced on every self-update branch.
- **Knowledge Store:** SQLite FTS5 LLM Wiki (`wiki.db`) + SQLite OS¹ state store (`os1.db`).
