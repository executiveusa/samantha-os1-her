# OS1-HER Agent & Contributor Safety Rules

Every rule below is backed by an enforced control in code, git hooks, or CI—not prose alone.

| Rule | Enforced by | Safe command |
|---|---|---|
| Never commit `.env`, `desktop.env`, `*.db`, `*.tgz`, `*.b64`, or live keys | `.gitignore` + `.githooks/pre-commit` (`git config core.hooksPath .githooks`) | `git status -s` |
| Never run tests against remote/production DBs or live `.env` | `services/orchestrator/tests/conftest.py` & `services/voice/tests/conftest.py` abort on non-local hosts or non-temp `OS1_STATE_DIR` | `(cd services/orchestrator && uv run pytest -q)` · `(cd services/voice && uv run pytest -q)` |
| Never deploy or restart live Orgo services accidentally | `scripts/deploy_orgo.py` defaults to `--dry-run` and prints a live-VM hazard warning | `python3 scripts/deploy_orgo.py` (dry-run) · `python3 scripts/deploy_orgo.py --apply` (explicit deploy) |
| Never execute write/message/payment tools without human confirmation & caps | `hermes/plugins/os1_composio/__init__.py` enforces `OS1_MAX_PAYMENT_USD`, explicit `currency` + `amount_cents`/`amount_usd`, `OS1_ALLOWED_RECIPIENTS`, and server-verified one-time `approval_id` (`/os1/approvals/{id}/verify`) | Configure via Connectors (`13`) or `.env` |
| Never expose unauthenticated orchestrator or unsigned Composio webhooks | `services/orchestrator/os1_orchestrator/app.py` fails closed when `OS1_CLIENT_TOKEN` or `COMPOSIO_WEBHOOK_SECRET` is unset | Set both in `.env` |
| Never run unbounded actions on the user's Mac | `apps/desktop/src/main/cuaHost.ts` enforces v3 bounded allowlist (`~/Desktop`, `~/Documents`, `~/Downloads`, no Terminal/Keychain/1Password) + global `Cmd+Shift+Escape` kill switch | Say `"Let me drive"` or press `Cmd+Shift+Escape` |
| Never self-update without Lauren Tan's `pstack` verification gates | `.pstack/principles.md`, `.pstack/playbooks.yaml`, and `services/orchestrator/os1_orchestrator/pstack_engine.py` route updates to isolated branches and require pytest + typecheck + build pass | `POST /os1/pstack/plan` · `POST /os1/pstack/run` |
| Never expose raw vault secrets or run unapproved Maus Bot mutations | `services/orchestrator/os1_orchestrator/vault.py` never returns secret values over HTTP; `ops_bridge.py` + `app.py` gate `restart`/`start`/`stop` behind one-time `approval_id` | `python scripts/bootstrap_vault.py` · `GET /os1/vault/status` · `GET /os1/ops/status` |
| All code Samantha writes MUST obey the 10 ICM invariants | `icm/CONTEXT.md`, `icm/_shared/ICM_RULES.md`, `icm/skills/icm-architect/SKILL.md`, and `pstack_engine.py` enforce one-folder-one-job, `CONTEXT.md` contracts, `[[wikilinks]]`, and L0-L4 policy gates | `GET /os1/wiki/graph` · `POST /os1/github/sync-wiki` · `GET /os1/vision/status` |
