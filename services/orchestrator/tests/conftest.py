"""Safety guard for orchestrator tests: abort if any DB/service URL is non-local or state isn't temp."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import pytest

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
URL_VARS = ("DATABASE_URL", "HERMES_API_URL", "ORCHESTRATOR_URL", "ORCHESTRATOR_PUBLIC_URL", "BRAIN_PUBLIC_URL")


def _assert_local_test_env() -> None:
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
    state_dir = os.environ.get("OS1_STATE_DIR", "").strip()
    if state_dir:
        resolved = Path(state_dir).resolve()
        tmp_root = Path(tempfile.gettempdir()).resolve()
        if not str(resolved).startswith(str(tmp_root)):
            raise pytest.UsageError(
                f"ABORTING TESTS: OS1_STATE_DIR={resolved} is outside system temp dir {tmp_root}."
            )


def pytest_configure(config: pytest.Config) -> None:
    _assert_local_test_env()
