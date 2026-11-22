"""Full GitHub Access & Cross-Project Graph Reasoner for Samantha OS¹.

Gives Samantha full visibility across Bambu's (`executiveusa`) GitHub repositories
(public + private when GITHUB_TOKEN/GH_TOKEN has `repo` scope), indexes every repo
into the SQLite LLM Wiki (`wiki.py`), detects cross-repo architecture & stack links,
and recommends the best ways to connect nodes and graphs across projects.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from .wiki import WikiStore

log = logging.getLogger("os1.github_graph")

ECOSYSTEM_TAGS = (
    "icm", "visionclaw", "ax022", "samantha", "os1", "hermes", "infisical",
    "tailscale", "opencode", "hostinger", "maus", "pstack", "vercel", "livekit",
    "fastapi", "electron", "vite", "react", "sqlite", "docker", "openrouter",
)


class GitHubGraphEngine:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self.owner = os.environ.get("GITHUB_OWNER", "executiveusa").strip() or "executiveusa"

    @property
    def token(self) -> str:
        return (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "samantha-os1-her/1.0",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def list_repos(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List all repositories accessible to the token (including private repos when authenticated)."""
        per_page = max(1, min(limit, 100))
        url = (
            f"https://api.github.com/user/repos?per_page={per_page}&sort=updated&affiliation=owner,collaborator,organization_member"
            if self.token
            else f"https://api.github.com/users/{self.owner}/repos?per_page={per_page}&sort=updated"
        )
        resp = await self._http().get(url, headers=self._headers())
        resp.raise_for_status()
        items = resp.json()
        return [
            {
                "name": r.get("name", ""),
                "full_name": r.get("full_name", ""),
                "private": bool(r.get("private", False)),
                "description": r.get("description") or "",
                "language": r.get("language") or "",
                "topics": list(r.get("topics") or []),
                "default_branch": r.get("default_branch") or "main",
                "html_url": r.get("html_url") or "",
                "updated_at": r.get("updated_at") or "",
            }
            for r in items
            if isinstance(r, dict)
        ]

    async def sync_repos_to_wiki(self, wiki: WikiStore, *, limit: int = 100) -> dict[str, Any]:
        """Index all GitHub repos into the SQLite LLM Wiki and link shared stacks/ecosystems."""
        repos = await self.list_repos(limit=limit)
        by_tag: dict[str, list[str]] = {}
        synced: list[str] = []

        for repo in repos:
            name = repo["name"]
            if not name:
                continue
            slug = f"github/{name}"
            blob = f"{name} {repo['description']} {repo['language']} {' '.join(repo['topics'])}".lower()
            tags = {t.lower() for t in repo["topics"]}
            if repo["language"]:
                tags.add(repo["language"].lower())
            for eco in ECOSYSTEM_TAGS:
                if eco in blob:
                    tags.add(eco)

            body = (
                f"# {repo['full_name']}\n\n"
                f"{repo['description'] or 'No description provided.'}\n\n"
                f"- **Language:** {repo['language'] or 'Unknown'}\n"
                f"- **Visibility:** {'private' if repo['private'] else 'public'}\n"
                f"- **Default branch:** {repo['default_branch']}\n"
                f"- **URL:** {repo['html_url']}\n"
                f"- **Topics/Stack:** {', '.join(sorted(tags)) or 'none'}\n"
            )
            wiki.upsert_page(
                slug=slug,
                title=repo["full_name"] or name,
                body=body,
                kind="repo",
                source_path=repo["html_url"],
                tags=sorted(tags),
                metadata=repo,
            )
            synced.append(slug)
            for tag in tags:
                by_tag.setdefault(tag, []).append(slug)

        edges_added = 0
        for tag, slugs in by_tag.items():
            if len(slugs) < 2 or len(slugs) > 25:
                continue
            for i in range(len(slugs)):
                for j in range(i + 1, len(slugs)):
                    wiki.add_edge(
                        slugs[i],
                        slugs[j],
                        relation="shared_stack",
                        weight=1.5 if tag in ECOSYSTEM_TAGS else 1.0,
                        reason=f"Shared stack/concept: {tag}",
                    )
                    edges_added += 1

        recommendations = wiki.recommend_connections(limit=12)
        return {
            "ok": True,
            "owner": self.owner,
            "authenticated": self.configured,
            "repos_indexed": len(synced),
            "edges_added": edges_added,
            "recommended_connections": recommendations,
        }
