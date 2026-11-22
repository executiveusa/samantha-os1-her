"""Hermes plugin: os1_composio — runtime policy-enforced Composio actions + Spatial Inbox sync.

Security controls (server-enforced, never trusted to model booleans):
- Per-call payment cap (`OS1_MAX_PAYMENT_USD`, default 25.00 USD) with explicit currency & unit check.
- Recipient allowlist (`OS1_ALLOWED_RECIPIENTS`) checked before outbound email/message sends.
- Write/message/payment calls require a server-verified, one-time human `approval_id` minted ONLY
  when the user approves the PendingAction modal on the orchestrator (`/os1/approvals/{id}/verify`).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

WRITE_HINTS = ("send", "create", "delete", "trash", "update", "modify", "post", "pay", "charge", "book", "archive", "transfer")
PAYMENT_HINTS = ("pay", "charge", "transfer", "refund", "invoice", "checkout", "payout")
MESSAGE_HINTS = ("send_email", "send_message", "post_message", "reply", "dm", "sms")
DEFAULT_MAX_PAYMENT_USD = 25.0


def _orch(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8787").rstrip("/")
    token = os.environ.get("OS1_CLIENT_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode()[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def _policy_for(toolkit: str) -> dict[str, Any]:
    data = _orch("GET", "/os1/connectors")
    for item in data.get("items", []):
        if item.get("slug") == toolkit.lower():
            return item
    return {"slug": toolkit.lower(), "policy": "ask_before_write", "connected": False}


def _check_payment_guard(toolkit: str, action_slug: str, arguments: dict[str, Any]) -> str | None:
    """Enforce explicit currency + units and a hard per-call USD cap on payment/money actions."""
    is_payment = toolkit == "stripe" or any(h in action_slug.lower() for h in PAYMENT_HINTS)
    if not is_payment:
        return None
    cap_usd = float(os.environ.get("OS1_MAX_PAYMENT_USD", str(DEFAULT_MAX_PAYMENT_USD)))
    currency = str(arguments.get("currency") or "").upper()
    has_cents = "amount_cents" in arguments
    has_usd = "amount_usd" in arguments
    if not currency or not (has_cents or has_usd):
        return (
            "WARNING: Payment actions MUST specify explicit `currency` (e.g. 'USD') AND `amount_cents` "
            "(integer cents) or `amount_usd` (explicit USD float) — ambiguous `amount` values are rejected."
        )
    if currency != "USD":
        return f"Only USD payments are permitted under OS1_MAX_PAYMENT_USD cap (got currency={currency!r})."
    try:
        usd = (int(arguments["amount_cents"]) / 100.0) if has_cents else float(arguments["amount_usd"])
    except (TypeError, ValueError):
        return "Invalid numeric payment amount."
    if usd <= 0:
        return "Payment amount must be positive."
    if usd > cap_usd:
        return f"WARNING: Payment of ${usd:.2f} USD exceeds per-call cap OS1_MAX_PAYMENT_USD=${cap_usd:.2f}."
    return None


def _check_recipient_allowlist(action_slug: str, arguments: dict[str, Any]) -> str | None:
    """When OS1_ALLOWED_RECIPIENTS is set, block outbound messages to recipients outside the allowlist."""
    if not any(h in action_slug.lower() for h in MESSAGE_HINTS):
        return None
    raw_allow = os.environ.get("OS1_ALLOWED_RECIPIENTS", "").strip()
    if not raw_allow:
        return None
    allowed = {r.strip().lower() for r in raw_allow.split(",") if r.strip()}
    recipient = str(
        arguments.get("recipient_email")
        or arguments.get("to")
        or arguments.get("recipient")
        or arguments.get("channel")
        or ""
    ).strip().lower()
    if not recipient:
        return "Outbound message requires an explicit recipient field (`to`, `recipient_email`, or `channel`)."
    if recipient not in allowed:
        return f"WARNING: Recipient '{recipient}' is not in OS1_ALLOWED_RECIPIENTS allowlist."
    return None


def _execute_composio(action_slug: str, arguments: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "error": "COMPOSIO_API_KEY is not configured yet. Open Connectors in OS1 or add COMPOSIO_API_KEY to .env.",
        }
    user_id = os.environ.get("OS1_SESSION_KEY", "os1-primary")
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    try:
        sess_req = urllib.request.Request(
            "https://backend.composio.dev/api/v3/tool_router/session",
            data=json.dumps({"user_id": user_id}).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(sess_req, timeout=15) as r:
            sid = json.loads(r.read().decode())["session_id"]
        exec_req = urllib.request.Request(
            f"https://backend.composio.dev/api/v3/tool_router/session/{sid}/execute",
            data=json.dumps({"tool_slug": action_slug, "arguments": arguments}).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(exec_req, timeout=25) as resp:
            return {"ok": True, "data": json.loads(resp.read().decode() or "{}")}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode()[:400]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def handle_composio_action(args: dict[str, Any], **_kwargs: Any) -> str:
    toolkit = str(args.get("toolkit", "")).lower()
    action_slug = str(args.get("action_slug", ""))
    arguments = args.get("arguments") or {}
    is_payment = toolkit == "stripe" or any(h in action_slug.lower() for h in PAYMENT_HINTS)
    is_message = any(h in action_slug.lower() for h in MESSAGE_HINTS)
    is_write = bool(args.get("is_write")) or is_payment or is_message or any(h in action_slug.lower() for h in WRITE_HINTS)

    # 1. Hard safety caps & allowlists (cannot be overridden by policy or model).
    if err := _check_payment_guard(toolkit, action_slug, arguments):
        return json.dumps({"ok": False, "blocked_by_cap": True, "error": err})
    if err := _check_recipient_allowlist(action_slug, arguments):
        return json.dumps({"ok": False, "blocked_by_allowlist": True, "error": err})

    # 2. Live per-app policy table enforcement.
    conn = _policy_for(toolkit)
    policy = conn.get("policy", "ask_before_write")

    if policy == "read_only" and is_write:
        return json.dumps(
            {
                "ok": False,
                "blocked_by_policy": True,
                "error": f"{toolkit} is set to read-only in OS1 Connectors. Ask the user if they want to allow writes.",
            }
        )

    # Payments ALWAYS require human confirmation regardless of toolkit policy.
    needs_approval = is_payment or (policy == "ask_before_write" and is_write) or policy == "ask_every_time"
    if needs_approval:
        approval_id = str(args.get("approval_id") or "").strip()
        if not approval_id:
            stakes = "money" if is_payment else "shared"
            summary = [f"Action: {action_slug}", f"Args: {json.dumps(arguments)[:180]}"]
            if is_payment:
                summary.insert(0, "WARNING: This moves money. Read back amount and recipient before confirming.")
            pa = _orch(
                "POST",
                "/os1/approvals",
                {
                    "source": "composio",
                    "title": f"{conn.get('label', toolkit)}: {action_slug}",
                    "summaryLines": summary,
                    "stakes": stakes,
                    "options": [
                        {"phrase": "Confirm it" if is_payment else "Go ahead", "choice": "allow"},
                        {"phrase": "Don't do it", "choice": "deny"},
                    ],
                },
            )
            return json.dumps({"ok": False, "requires_approval": True, "pending_action": pa})

        # Verify & consume the server-minted one-time human approval token.
        verified = _orch("POST", f"/os1/approvals/{approval_id}/verify", {"expected_source": "composio"})
        if not verified.get("approved"):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Approval token was not confirmed by the user, expired, or already used.",
                }
            )

    return json.dumps(_execute_composio(action_slug, arguments))


def handle_sync_inbox(args: dict[str, Any], **_kwargs: Any) -> str:
    items = args.get("items")
    if items is None:
        res = _execute_composio("GMAIL_FETCH_EMAILS", {"max_results": int(args.get("limit", 12)), "query": "in:inbox"})
        if not res.get("ok"):
            return json.dumps(res)
        raw_msgs = res.get("data", {}).get("data", {}).get("messages", []) or []
        items = [
            {
                "id": m.get("messageId") or m.get("id"),
                "sender": m.get("sender") or m.get("from", "Unknown"),
                "subject": m.get("subject", "(No subject)"),
                "snippet": m.get("preview", {}).get("body") if isinstance(m.get("preview"), dict) else m.get("snippet", ""),
                "received_at": m.get("messageTimestamp", ""),
            }
            for m in raw_msgs
        ]
    return json.dumps(_orch("POST", "/os1/inbox/sync", {"items": items}))


def register(ctx: Any) -> None:
    ctx.register_tool(
        name="os1_composio_action",
        toolset="os1",
        description=(
            "Execute a Composio connector action enforcing OS1 runtime connector policy, per-call payment caps "
            "(explicit currency + amount_cents/amount_usd required), recipient allowlist, and one-time human approval_id."
        ),
        schema={
            "name": "os1_composio_action",
            "description": "Policy-checked, cap-checked Composio tool execution.",
            "parameters": {
                "type": "object",
                "properties": {
                    "toolkit": {"type": "string", "description": "e.g. gmail, googlecalendar, googledrive, spotify, slack, stripe"},
                    "action_slug": {"type": "string", "description": "e.g. GMAIL_FETCH_EMAILS, GMAIL_SEND_EMAIL"},
                    "arguments": {"type": "object"},
                    "is_write": {"type": "boolean", "default": False},
                    "approval_id": {
                        "type": "string",
                        "description": "Server-minted PendingAction ID returned after the user explicitly confirmed.",
                    },
                },
                "required": ["toolkit", "action_slug"],
            },
        },
        handler=handle_composio_action,
    )
    ctx.register_tool(
        name="os1_composio_sync_inbox",
        toolset="os1",
        description="Sync emails into the OS1 Spatial Inbox with Jev keeper scoring.",
        schema={
            "name": "os1_composio_sync_inbox",
            "description": "Fetch or push emails to the OS1 Spatial Inbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 12},
                    "items": {"type": "array", "items": {"type": "object"}},
                },
            },
        },
        handler=handle_sync_inbox,
    )
