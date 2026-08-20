"""Helpers for backend integration tests that require a running API server.

These tests intentionally hit a real HTTP server via requests. In local Windows
workspaces the historical `/app/frontend/.env` path does not exist, so URL
resolution must be cross-platform and skip cleanly when no target server is set.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_backend_url_from_env_file(path: Path) -> str:
    if not path.exists():
        return ""

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "REACT_APP_BACKEND_URL":
            return value.strip().strip('"').strip("'").rstrip("/")
    return ""


def get_backend_url() -> str:
    """Return REACT_APP_BACKEND_URL from env or known .env locations."""
    env_url = os.environ.get("REACT_APP_BACKEND_URL", "").strip().rstrip("/")
    if env_url:
        return env_url

    candidates = []
    explicit_env_file = os.environ.get("FRONTEND_ENV_FILE", "").strip()
    if explicit_env_file:
        candidates.append(Path(explicit_env_file))

    repo = _repo_root()
    candidates.extend(
        [
            repo / "frontend" / ".env",
            repo / ".env",
            Path("/app/frontend/.env"),
        ]
    )

    for candidate in candidates:
        url = _read_backend_url_from_env_file(candidate)
        if url:
            return url
    return ""


NO_BACKEND_URL_REASON = (
    "integration test skipped: set REACT_APP_BACKEND_URL or create frontend/.env"
)


def skip_without_backend_url(url: str | None = None):
    """Return a module-level skip marker while preserving test collection."""
    resolved_url = get_backend_url() if url is None else url
    return pytest.mark.skipif(not resolved_url, reason=NO_BACKEND_URL_REASON)
