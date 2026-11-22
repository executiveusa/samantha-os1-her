"""Safety guard for voice tests: abort if any DB/service URL points to a non-local host."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
URL_VARS = ("DATABASE_URL", "HERMES_API_URL", "ORCHESTRATOR_URL", "ORCHESTRATOR_PUBLIC_URL", "BRAIN_PUBLIC_URL")


def pytest_configure(config: pytest.Config) -> None:
    os.environ["OS1_SKIP_DOTENV"] = "1"
    for var in URL_VARS:
        val = os.environ.get(var, "").strip()
        if not val:
            continue
        host = (urlparse(val).hostname or "").lower()
        if host not in LOCAL_HOSTS:
            raise pytest.UsageError(
                f"ABORTING TESTS: {var} points to non-local host {host!r}. "
                "Unset remote/production URLs before running pytest."
            )
