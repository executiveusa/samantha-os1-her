# pstack Engineering Principles for Samantha OS¹

Adapted from Lauren Tan's (`@poteto`) open-source **pstack** (`cursor/plugins/pstack`) so Samantha builds, audits, and updates herself with senior-staff engineering rigor instead of shipping AI slop.

## Core Principles

1. **Prove It Works (`principle-prove-it-works`)** — Never claim a fix or feature works without running tests, typechecks, builds, or runtime probes that directly exercise the changed behavior.
2. **Fix Root Causes (`principle-fix-root-causes`)** — Trace failures to the underlying invariant violation; never mask symptoms with retry loops or swallowed exceptions.
3. **Sequence Verifiable Units (`principle-sequence-verifiable-units`)** — Break self-updates into small, independently testable increments; verify each unit before moving to the next.
4. **Subtract Before You Add (`principle-subtract-before-you-add`)** — Prefer deleting dead paths, simplifying state machines, and reusing existing modules over adding parallel abstractions.
5. **Boundary Discipline (`principle-boundary-discipline`)** — Enforce strict ownership boundaries: Client renders, Voice handles turns, Orchestrator owns canonical state & approvals, Vault owns secrets, Ops Bridge owns infrastructure.
6. **Make Operations Idempotent (`principle-make-operations-idempotent`)** — Every bootstrap, vault sync, deployment script, and bot control command must be safe to re-run.
7. **Test Behavior, Not Implementation (`principle-test-behavior-not-implementation`)** — Assert public contracts, HTTP responses, state transitions, and failover outcomes rather than private method internals.
8. **Type System Discipline (`principle-type-system-discipline`)** — Keep TypeScript (`strict`) and Python type annotations clean; reject `any`-heavy glue code.
9. **Encode Lessons in Structure (`principle-encode-lessons-in-structure`)** — Turn every incident or bug into a regression test, pre-commit hook, or schema constraint so it cannot recur.
10. **Guard the Context Window (`principle-guard-the-context-window`)** — Keep voice prompts lean, cache static persona rules, and compress repo memory in `docs/agent-context.md`.
11. **Never Block on the Human (`principle-never-block-on-the-human`)** — Resolve everything answerable from the repo, tests, and vault autonomously; escalate only at hard safety/risk gates.
12. **Blast Radius Awareness (`blast-radius`)** — Before modifying shared infrastructure, auth, vault, or fleet controllers, enumerate affected services and verify rollback paths.
