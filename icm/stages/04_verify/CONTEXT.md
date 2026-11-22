---
title: Stage 04 — Verify
stage: "04_verify"
---
# 04 Verify
- **Inputs:** Stage 03 diff.
- **Process:** Run `pytest`, `ruff check`, `npm run typecheck`, `npm run build`, `npm run build:web`, and secret scan.
- **Outputs:** Green test/lint/build proof.
- **Human/Gate Check:** Zero failures or unexplained regressions.
