"""SQLite FTS5 LLM Wiki & Second Brain Knowledge Graph for Samantha OS¹.

Indexes Bambu's Second Brain files (`OS1_SECOND_BRAIN_DIR`), ICM workspace shelves (`icm/`),
and GitHub repository nodes into a queryable SQLite database (`wiki.db`) with:
- FTS5 full-text search + snippets
- Automatic YAML frontmatter & `[[wikilink]]` extraction
- Directed graph edges (`wikilink`, `shared_stack`, `depends_on`, `connects_to`)
- Cross-node connection recommendations (scans unlinked nodes for shared concepts/stacks)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]+)?\]\]")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{3,28}")

STOPWORDS = frozenset(
    {
        "this", "that", "with", "from", "have", "will", "your", "their", "about", "there",
        "which", "when", "what", "where", "into", "only", "also", "more", "most", "some",
        "each", "other", "than", "then", "them", "they", "been", "being", "does", "done",
        "make", "made", "used", "using", "uses", "file", "files", "path", "true", "false",
        "none", "null", "code", "docs", "readme", "context", "markdown", "title", "kind",
    }
)

SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "__pycache__", "dist", "dist-web", "out", ".vault-staging"})
INDEXABLE_EXTS = frozenset({".md", ".txt"})


def slugify(raw: str) -> str:
    s = raw.strip().lower().replace("\\", "/")
    s = re.sub(r"\.md$", "", s)
    s = re.sub(r"[^a-z0-9/_-]+", "-", s).strip("-/")
    return s or "untitled"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip().lower()
        val = v.strip().strip('"').strip("'")
        if key == "tags":
            val_clean = val.strip("[]")
            meta["tags"] = [t.strip().strip('"').strip("'") for t in val_clean.split(",") if t.strip()]
        elif key:
            meta[key] = val
    return meta, text[m.end() :]


def extract_wikilinks(text: str) -> list[str]:
    seen: list[str] = []
    for raw in WIKILINK_RE.findall(text):
        target = slugify(raw)
        if target and target not in seen:
            seen.append(target)
    return seen


def extract_keywords(text: str, *, limit: int = 24) -> set[str]:
    counts: dict[str, int] = {}
    for tok in TOKEN_RE.findall(text.lower()):
        if tok in STOPWORDS:
            continue
        counts[tok] = counts.get(tok, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {k for k, _ in ranked[:limit]}


class WikiStore:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "wiki.db"
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
        with self._conn() as c:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    slug TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'note',
                    body TEXT NOT NULL DEFAULT '',
                    source_path TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    content_hash TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS wiki_edges (
                    source_slug TEXT NOT NULL,
                    target_slug TEXT NOT NULL,
                    relation TEXT NOT NULL DEFAULT 'wikilink',
                    weight REAL NOT NULL DEFAULT 1.0,
                    reason TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source_slug, target_slug, relation)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                    slug UNINDEXED,
                    title,
                    tags,
                    body
                );
                """
            )

    def upsert_page(
        self,
        *,
        slug: str,
        title: str,
        body: str,
        kind: str = "note",
        source_path: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        norm_slug = slugify(slug)
        tag_list = sorted({t.strip().lower() for t in (tags or []) if t and t.strip()})
        meta = dict(metadata or {})
        content_hash = hashlib.sha256(f"{title}\n{kind}\n{tag_list}\n{body}".encode()).hexdigest()[:16]
        now = time.time()

        links = extract_wikilinks(body)
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO wiki_pages (slug, title, kind, body, source_path, tags_json, meta_json, content_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    kind=excluded.kind,
                    body=excluded.body,
                    source_path=excluded.source_path,
                    tags_json=excluded.tags_json,
                    meta_json=excluded.meta_json,
                    content_hash=excluded.content_hash,
                    updated_at=excluded.updated_at
                """,
                (norm_slug, title, kind, body, source_path, json.dumps(tag_list), json.dumps(meta), content_hash, now),
            )
            c.execute("DELETE FROM wiki_fts WHERE slug=?", (norm_slug,))
            c.execute(
                "INSERT INTO wiki_fts (slug, title, tags, body) VALUES (?, ?, ?, ?)",
                (norm_slug, title, " ".join(tag_list), body),
            )
            c.execute("DELETE FROM wiki_edges WHERE source_slug=? AND relation='wikilink'", (norm_slug,))
            for target in links:
                if target != norm_slug:
                    c.execute(
                        """
                        INSERT OR REPLACE INTO wiki_edges (source_slug, target_slug, relation, weight, reason)
                        VALUES (?, ?, 'wikilink', 1.0, 'Explicit [[wikilink]]')
                        """,
                        (norm_slug, target),
                    )
        return {
            "slug": norm_slug,
            "title": title,
            "kind": kind,
            "tags": tag_list,
            "links": links,
            "source_path": source_path,
            "updated_at": now,
        }

    def add_edge(self, source_slug: str, target_slug: str, *, relation: str = "connects_to", weight: float = 1.0, reason: str = "") -> None:
        s, t = slugify(source_slug), slugify(target_slug)
        if not s or not t or s == t:
            return
        with self._conn() as c:
            c.execute(
                """
                INSERT OR REPLACE INTO wiki_edges (source_slug, target_slug, relation, weight, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (s, t, relation, weight, reason),
            )

    def ingest_directory(self, directory: Path, *, kind: str = "second_brain", max_files: int = 300) -> dict[str, Any]:
        root = directory.resolve()
        if not root.exists() or not root.is_dir():
            return {"ok": False, "error": f"Directory not found: {root}", "ingested": 0}

        ingested: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if len(ingested) >= max_files:
                    break
                p = Path(dirpath) / fname
                if p.suffix.lower() not in INDEXABLE_EXTS:
                    continue
                try:
                    raw = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if not raw.strip():
                    continue
                meta, body = parse_frontmatter(raw)
                rel = p.relative_to(root).as_posix()
                title = str(meta.get("title") or p.stem.replace("_", " ").replace("-", " ").title())
                page_kind = str(meta.get("kind") or kind)
                tags = list(meta.get("tags") or [])
                if p.parent != root:
                    tags.append(p.parent.name.lower())
                res = self.upsert_page(
                    slug=rel,
                    title=title,
                    body=body[:24000],
                    kind=page_kind,
                    source_path=str(p),
                    tags=tags,
                    metadata=meta,
                )
                ingested.append(res["slug"])
        return {"ok": True, "directory": str(root), "ingested": len(ingested), "slugs": ingested[:40]}

    def list_pages(self, *, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            if kind:
                rows = c.execute(
                    "SELECT slug, title, kind, source_path, tags_json, updated_at FROM wiki_pages WHERE kind=? ORDER BY updated_at DESC LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT slug, title, kind, source_path, tags_json, updated_at FROM wiki_pages ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "slug": r["slug"],
                "title": r["title"],
                "kind": r["kind"],
                "source_path": r["source_path"],
                "tags": json.loads(r["tags_json"]),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_page(self, slug: str) -> dict[str, Any] | None:
        norm = slugify(slug)
        with self._conn() as c:
            row = c.execute("SELECT * FROM wiki_pages WHERE slug=?", (norm,)).fetchone()
            if not row:
                return None
            outgoing = c.execute(
                "SELECT target_slug, relation, weight, reason FROM wiki_edges WHERE source_slug=?",
                (norm,),
            ).fetchall()
            backlinks = c.execute(
                "SELECT source_slug, relation, weight, reason FROM wiki_edges WHERE target_slug=?",
                (norm,),
            ).fetchall()
        return {
            "slug": row["slug"],
            "title": row["title"],
            "kind": row["kind"],
            "body": row["body"],
            "source_path": row["source_path"],
            "tags": json.loads(row["tags_json"]),
            "metadata": json.loads(row["meta_json"]),
            "updated_at": row["updated_at"],
            "outgoing": [dict(r) for r in outgoing],
            "backlinks": [dict(r) for r in backlinks],
        }

    def search(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        clean = re.sub(r"[^a-zA-Z0-9_\s]+", " ", query).strip()
        if not clean:
            return []
        fts_query = " OR ".join(f"{tok}*" for tok in clean.split()[:8])
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT p.slug, p.title, p.kind, p.tags_json,
                       snippet(wiki_fts, 3, '[', ']', '...', 18) AS snippet
                FROM wiki_fts
                JOIN wiki_pages p ON p.slug = wiki_fts.slug
                WHERE wiki_fts MATCH ?
                ORDER BY bm25(wiki_fts)
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
        return [
            {
                "slug": r["slug"],
                "title": r["title"],
                "kind": r["kind"],
                "tags": json.loads(r["tags_json"]),
                "snippet": r["snippet"],
            }
            for r in rows
        ]

    def get_graph(self) -> dict[str, Any]:
        with self._conn() as c:
            nodes = [
                {
                    "id": r["slug"],
                    "title": r["title"],
                    "kind": r["kind"],
                    "tags": json.loads(r["tags_json"]),
                }
                for r in c.execute("SELECT slug, title, kind, tags_json FROM wiki_pages ORDER BY slug").fetchall()
            ]
            edges = [
                dict(r)
                for r in c.execute("SELECT source_slug AS source, target_slug AS target, relation, weight, reason FROM wiki_edges").fetchall()
            ]
        degree: dict[str, int] = {n["id"]: 0 for n in nodes}
        for e in edges:
            if e["source"] in degree:
                degree[e["source"]] += 1
            if e["target"] in degree:
                degree[e["target"]] += 1
        hubs = sorted(degree.items(), key=lambda kv: -kv[1])[:8]
        orphans = [nid for nid, deg in degree.items() if deg == 0]
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "hubs": [{"id": nid, "degree": deg} for nid, deg in hubs if deg > 0],
                "orphan_count": len(orphans),
                "orphans": orphans[:20],
            },
        }

    def recommend_connections(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """Scan all wiki/repo nodes and propose the highest-leverage unlinked connections."""
        with self._conn() as c:
            rows = c.execute("SELECT slug, title, kind, tags_json, body FROM wiki_pages").fetchall()
            existing = {
                (r["source_slug"], r["target_slug"])
                for r in c.execute("SELECT source_slug, target_slug FROM wiki_edges").fetchall()
            }

        profiles: list[tuple[str, str, str, set[str], set[str]]] = []
        for r in rows:
            tags = set(json.loads(r["tags_json"]))
            kws = extract_keywords(f"{r['title']} {r['body']}")
            profiles.append((r["slug"], r["title"], r["kind"], tags, kws))

        suggestions: list[dict[str, Any]] = []
        n = len(profiles)
        for i in range(n):
            s1, t1, k1, tags1, kw1 = profiles[i]
            for j in range(i + 1, n):
                s2, t2, k2, tags2, kw2 = profiles[j]
                if (s1, s2) in existing or (s2, s1) in existing:
                    continue
                shared_tags = sorted(tags1 & tags2)
                shared_kws = sorted(kw1 & kw2)
                score = len(shared_tags) * 2.5 + len(shared_kws) * 0.6
                if score < 2.4:
                    continue
                suggestions.append(
                    {
                        "source": s1,
                        "source_title": t1,
                        "source_kind": k1,
                        "target": s2,
                        "target_title": t2,
                        "target_kind": k2,
                        "score": round(score, 2),
                        "shared_tags": shared_tags[:8],
                        "shared_concepts": shared_kws[:8],
                        "rationale": f"Connect {t1} ↔ {t2} via shared {', '.join((shared_tags or shared_kws)[:4])}",
                    }
                )
        suggestions.sort(key=lambda item: -item["score"])
        return suggestions[:limit]
