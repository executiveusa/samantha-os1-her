"""pstack Self-Building & Self-Updating Engine for Samantha OS¹.

Loads Lauren Tan's (@poteto) adapted playbooks and principles from `.pstack/`
and dispatches self-evolution tasks to OpenCode (`anomalyco/opencode`) or Hermes.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("os1.pstack")

REPO_ROOT = Path(__file__).resolve().parents[3]
PSTACK_DIR = REPO_ROOT / ".pstack"

PLAYBOOK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bugfix": ("bug", "fix", "broken", "crash", "error", "desync", "leak", "regression"),
    "architect": ("design", "architect", "architecture", "system", "plan", "migrate", "refactor"),
    "tdd": ("test", "tdd", "coverage", "spec", "assert"),
    "unslop": ("clean", "unslop", "simplify", "dead code", "audit"),
    "self-update": ("update yourself", "self-update", "upgrade", "evolve", "add feature", "build"),
}


def load_pstack_manifest() -> dict[str, Any]:
    principles_path = PSTACK_DIR / "principles.md"
    playbooks_path = PSTACK_DIR / "playbooks.yaml"
    principles_text = principles_path.read_text(encoding="utf-8") if principles_path.exists() else ""
    playbooks_raw = playbooks_path.read_text(encoding="utf-8") if playbooks_path.exists() else ""
    playbook_names = re.findall(r"^  ([a-z][a-z0-9-]+):\s*$", playbooks_raw, flags=re.MULTILINE)
    return {
        "installed": principles_path.exists() and playbooks_path.exists(),
        "path": str(PSTACK_DIR),
        "playbooks": playbook_names or ["poteto-mode", "architect", "bugfix", "tdd", "self-update", "unslop"],
        "principles_count": len(re.findall(r"^\d+\.\s+\*\*", principles_text, flags=re.MULTILINE)),
    }


def route_poteto_mode(goal: str) -> dict[str, Any]:
    """Classify a goal into the best pstack playbook and assemble a rigorous execution brief."""
    low = goal.lower()
    chosen = "poteto-mode"
    for playbook, keywords in PLAYBOOK_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            chosen = playbook
            break

    branch_slug = re.sub(r"[^a-z0-9]+", "-", low).strip("-")[:36] or "update"
    return {
        "router": "poteto-mode",
        "playbook": chosen,
        "branch": f"self-update/{branch_slug}",
        "goal": goal,
        "required_gates": [
            "cd services/orchestrator && uv run pytest -q",
            "cd services/voice && uv run pytest -q",
            "npm run typecheck",
            "npm run build && npm run build:web",
        ],
        "principles": [
            "principle-prove-it-works",
            "principle-fix-root-causes",
            "principle-sequence-verifiable-units",
            "principle-subtract-before-you-add",
            "principle-make-operations-idempotent",
        ],
    }


class PstackSelfUpdater:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self.opencode_url = os.environ.get("OPENCODE_BASE_URL", "http://opencode:4096").rstrip("/")
        self.opencode_password = os.environ.get("OPENCODE_SERVER_PASSWORD", "").strip()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    def status(self) -> dict[str, Any]:
        return {
            **load_pstack_manifest(),
            "opencode_url": self.opencode_url,
            "opencode_configured": bool(self.opencode_url),
        }

    async def dispatch_to_opencode(self, goal: str, *, dry_run: bool = False) -> dict[str, Any]:
        brief = route_poteto_mode(goal)
        if dry_run:
            return {"ok": True, "dry_run": True, "brief": brief, "opencode_url": self.opencode_url}

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.opencode_password:
            headers["Authorization"] = f"Bearer {self.opencode_password}"

        prompt = (
            f"Run pstack playbook `{brief['playbook']}` on branch `{brief['branch']}`.\n"
            f"Goal: {goal}\n"
            f"Principles: {', '.join(brief['principles'])}\n"
            "ICM Architecture Mandate (NON-NEGOTIABLE): All code and folders written MUST follow "
            "the 10 ICM invariants in `icm/_shared/ICM_RULES.md` and `icm/skills/icm-architect/SKILL.md` "
            "(one folder one job, explicit CONTEXT.md contracts, small root catalog, [[wikilinks]] + YAML frontmatter, "
            "factory vs product separation, filesystem as state machine).\n"
            f"Verification gates (must all pass): {'; '.join(brief['required_gates'])}"
        )
        try:
            sess = await self._http().post(f"{self.opencode_url}/session", headers=headers, json={"title": f"pstack: {goal[:60]}"})
            sess.raise_for_status()
            session_id = sess.json().get("id")
            msg = await self._http().post(
                f"{self.opencode_url}/session/{session_id}/message",
                headers=headers,
                json={"parts": [{"type": "text", "text": prompt}]},
            )
            msg.raise_for_status()
            return {"ok": True, "session_id": session_id, "brief": brief}
        except Exception as exc:  # noqa: BLE001
            log.warning("opencode dispatch unavailable (%s); returning structured pstack brief", exc)
            return {"ok": False, "error": str(exc), "brief": brief}
