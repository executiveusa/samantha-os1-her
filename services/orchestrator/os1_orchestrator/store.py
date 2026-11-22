"""SQLite-backed state store for the OS1 orchestrator.

Owns:
- User profile (including voice preferences & tweaks)
- OS1 Memory Ledger (5 Paper categories + hard delete)
- Connector Policy Table (per-app access levels & spoken status)
- Activity log ("While you were away" + Cua / trigger events)
- 60-second undo queue
- Spatial Inbox cache (numbered email tiles with Jev keeper scores)
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MEMORY_CATEGORIES = (
    "people",
    "places",
    "things_you_love",
    "things_that_hurt",
    "promises",
)

CONNECTOR_POLICIES = (
    "full_access",
    "ask_before_write",
    "read_only",
    "ask_every_time",
)

DEFAULT_PROFILE: dict[str, Any] = {
    "name": "",
    "onboarded": False,
    "voice_key": "voice_1_warm",
    "voice_speed": 0.96,
    "voice_temperature": 0.72,
    "voice_style_note": "",
    "dossier": {},
    "first_meeting_pending": False,
}

DEFAULT_CONNECTORS: list[dict[str, Any]] = [
    {"slug": "gmail", "label": "Mail", "policy": "ask_before_write", "connected": False, "account_label": ""},
    {"slug": "googlecalendar", "label": "Calendar", "policy": "full_access", "connected": False, "account_label": ""},
    {"slug": "googledrive", "label": "Files", "policy": "read_only", "connected": False, "account_label": ""},
    {"slug": "spotify", "label": "Music", "policy": "full_access", "connected": False, "account_label": ""},
    {"slug": "slack", "label": "Messages", "policy": "ask_before_write", "connected": False, "account_label": ""},
    {"slug": "stripe", "label": "Payments", "policy": "ask_every_time", "connected": False, "account_label": ""},
]

SPOKEN_POLICY = {
    "full_access": "full access",
    "ask_before_write": "asks before sending",
    "read_only": "read only",
    "ask_every_time": "asks every time",
}


def spoken_connector_status(label: str, policy: str, connected: bool) -> str:
    if not connected:
        return f"{label} · not connected"
    return f"{label} · {SPOKEN_POLICY.get(policy, policy)}"


class Os1Store:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "os1.db"
        self.profile_path = self.state_dir / "profile.json"
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'voice',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS connectors (
                    slug TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    policy TEXT NOT NULL,
                    connected INTEGER NOT NULL DEFAULT 0,
                    account_label TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS activity_log (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'done',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS undo_queue (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    undone INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS inbox_items (
                    id TEXT PRIMARY KEY,
                    number INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    snippet TEXT NOT NULL DEFAULT '',
                    received_at TEXT NOT NULL DEFAULT '',
                    keeper_score REAL NOT NULL DEFAULT 0.5,
                    is_vip INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'personal',
                    status TEXT NOT NULL DEFAULT 'active'
                );
                """
            )
            now = time.time()
            for item in DEFAULT_CONNECTORS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO connectors (slug, label, policy, connected, account_label, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["slug"],
                        item["label"],
                        item["policy"],
                        1 if item["connected"] else 0,
                        item["account_label"],
                        now,
                    ),
                )

    # ----------------------------------------------------------------- profile

    def read_profile(self) -> dict[str, Any]:
        if self.profile_path.exists():
            try:
                return {**DEFAULT_PROFILE, **json.loads(self.profile_path.read_text())}
            except json.JSONDecodeError:
                pass
        return dict(DEFAULT_PROFILE)

    def write_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        merged = {**DEFAULT_PROFILE, **profile}
        self.profile_path.write_text(json.dumps(merged, indent=2))
        return merged

    def patch_profile(self, fields: dict[str, Any]) -> dict[str, Any]:
        return self.write_profile({**self.read_profile(), **fields})

    # ---------------------------------------------------------------- memories

    def add_memory(
        self,
        *,
        category: str,
        summary: str,
        detail: str = "",
        source: str = "voice",
    ) -> dict[str, Any]:
        cat = category if category in MEMORY_CATEGORIES else "things_you_love"
        mem = {
            "id": f"mem_{uuid.uuid4().hex[:10]}",
            "category": cat,
            "summary": summary.strip(),
            "detail": detail.strip(),
            "source": source,
            "created_at": time.time(),
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, category, summary, detail, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mem["id"], mem["category"], mem["summary"], mem["detail"], mem["source"], mem["created_at"]),
            )
        return mem

    def list_memories(self, category: str | None = None, query: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list[Any] = []
        if category and category in MEMORY_CATEGORIES:
            sql += " AND category = ?"
            params.append(category)
        if query:
            q = f"%{query.strip().lower()}%"
            sql += " AND (LOWER(summary) LIKE ? OR LOWER(detail) LIKE ?)"
            params.extend([q, q])
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def memory_shortlist(self, limit: int = 12) -> list[str]:
        rows = self.list_memories(limit=limit)
        return [f"[{r['category'].replace('_', ' ')}] {r['summary']}" for r in rows]

    def forget_memory(self, memory_id: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
        """Hard-delete by exact id or substring match; returns deleted rows so Hermes can purge too."""
        with self._conn() as conn:
            if memory_id:
                rows = [dict(r) for r in conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchall()]
                if rows:
                    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                return rows
            if query and query.strip():
                q = f"%{query.strip().lower()}%"
                rows = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM memories WHERE LOWER(summary) LIKE ? OR LOWER(detail) LIKE ?", (q, q)
                    ).fetchall()
                ]
                if rows:
                    conn.execute(
                        "DELETE FROM memories WHERE LOWER(summary) LIKE ? OR LOWER(detail) LIKE ?", (q, q)
                    )
                return rows
        return []

    # -------------------------------------------------------------- connectors

    def list_connectors(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute("SELECT * FROM connectors ORDER BY rowid ASC").fetchall()]
        for r in rows:
            r["connected"] = bool(r["connected"])
            r["spoken_status"] = spoken_connector_status(r["label"], r["policy"], r["connected"])
        return rows

    def get_connector(self, slug: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM connectors WHERE slug = ?", (slug.lower(),)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["connected"] = bool(d["connected"])
        d["spoken_status"] = spoken_connector_status(d["label"], d["policy"], d["connected"])
        return d

    def upsert_connector(
        self,
        slug: str,
        *,
        policy: str | None = None,
        connected: bool | None = None,
        account_label: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        slug_norm = slug.lower().strip()
        existing = self.get_connector(slug_norm)
        now = time.time()
        new_label = label or (existing["label"] if existing else slug_norm.title())
        new_policy = policy if policy in CONNECTOR_POLICIES else (existing["policy"] if existing else "ask_before_write")
        new_connected = connected if connected is not None else (existing["connected"] if existing else False)
        new_account = account_label if account_label is not None else (existing["account_label"] if existing else "")
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO connectors (slug, label, policy, connected, account_label, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    label = excluded.label,
                    policy = excluded.policy,
                    connected = excluded.connected,
                    account_label = excluded.account_label,
                    updated_at = excluded.updated_at
                """,
                (slug_norm, new_label, new_policy, 1 if new_connected else 0, new_account, now),
            )
        return self.get_connector(slug_norm) or {}

    # ------------------------------------------------------------ activity log

    def add_activity(self, *, source: str, title: str, detail: str = "", status: str = "done") -> dict[str, Any]:
        item = {
            "id": f"act_{uuid.uuid4().hex[:10]}",
            "source": source,
            "title": title.strip(),
            "detail": detail.strip(),
            "status": status,
            "created_at": time.time(),
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO activity_log (id, source, title, detail, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (item["id"], item["source"], item["title"], item["detail"], item["status"], item["created_at"]),
            )
        return item

    def list_activity(self, source: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        sql = "SELECT * FROM activity_log"
        params: list[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # -------------------------------------------------------------- undo queue

    def push_undo(self, *, label: str, action_type: str, payload: dict[str, Any], ttl_s: float = 60.0) -> dict[str, Any]:
        now = time.time()
        entry = {
            "id": f"undo_{uuid.uuid4().hex[:10]}",
            "label": label,
            "action_type": action_type,
            "payload": payload,
            "created_at": now,
            "expires_at": now + ttl_s,
            "undone": False,
        }
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO undo_queue (id, label, action_type, payload_json, created_at, expires_at, undone)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (entry["id"], label, action_type, json.dumps(payload), now, entry["expires_at"]),
            )
        return entry

    def latest_undo(self) -> dict[str, Any] | None:
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM undo_queue WHERE undone = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                (now,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["undone"] = bool(d["undone"])
        return d

    def consume_undo(self, undo_id: str | None = None) -> dict[str, Any] | None:
        now = time.time()
        with self._conn() as conn:
            if undo_id:
                row = conn.execute(
                    "SELECT * FROM undo_queue WHERE id = ? AND undone = 0 AND expires_at > ?",
                    (undo_id, now),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM undo_queue WHERE undone = 0 AND expires_at > ? ORDER BY created_at DESC LIMIT 1",
                    (now,),
                ).fetchone()
            if not row:
                return None
            conn.execute("UPDATE undo_queue SET undone = 1 WHERE id = ?", (row["id"],))
        d = dict(row)
        d["payload"] = json.loads(d.pop("payload_json"))
        d["undone"] = True
        return d

    # ----------------------------------------------------------- spatial inbox

    def set_inbox_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conn.execute("DELETE FROM inbox_items")
            for idx, item in enumerate(items, start=1):
                conn.execute(
                    """
                    INSERT INTO inbox_items (id, number, sender, subject, snippet, received_at, keeper_score, is_vip, category, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("id") or f"msg_{idx}"),
                        int(item.get("number") or idx),
                        str(item.get("sender") or ""),
                        str(item.get("subject") or ""),
                        str(item.get("snippet") or ""),
                        str(item.get("received_at") or ""),
                        float(item.get("keeper_score", 0.5)),
                        1 if item.get("is_vip") else 0,
                        str(item.get("category") or "personal"),
                        str(item.get("status") or "active"),
                    ),
                )
        return self.list_inbox()

    def list_inbox(self, include_cleared: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM inbox_items"
        if not include_cleared:
            sql += " WHERE status = 'active'"
        sql += " ORDER BY number ASC"
        with self._conn() as conn:
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
        for r in rows:
            r["is_vip"] = bool(r["is_vip"])
        return rows

    def update_inbox_status(self, numbers: list[int], status: str) -> list[dict[str, Any]]:
        if not numbers:
            return []
        placeholders = ",".join("?" for _ in numbers)
        with self._conn() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM inbox_items WHERE number IN ({placeholders})", numbers
                ).fetchall()
            ]
            conn.execute(f"UPDATE inbox_items SET status = ? WHERE number IN ({placeholders})", [status, *numbers])
        return rows
