"""Start the local ERP UI against the approved homologation database only."""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

from pymongo.uri_parser import parse_uri


EXPECTED_DB = "kuryos_erp_homologacao"
HML_HOST_FRAGMENT = "yxj58uo"
PRODUCTION_HOST_FRAGMENT = "h2hedhh"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def assert_homologation(uri: str, database: str) -> None:
    hosts = [host for host, _ in parse_uri(uri).get("nodelist", [])]
    if database != EXPECTED_DB:
        raise RuntimeError("Database is not the approved homologation database")
    if any(PRODUCTION_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Production host detected; startup refused")
    if not any(HML_HOST_FRAGMENT in host for host in hosts):
        raise RuntimeError("Approved homologation host not detected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="firebase-migration-hml.env")
    parser.add_argument("--backend-only", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    values = load_env(root / args.env)
    uri = values["ERP_HML_MONGO_URI"]
    database = values["ERP_HML_DB_NAME"]
    assert_homologation(uri, database)

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    backend_env = os.environ.copy()
    backend_env.update({
        "MONGO_URL": uri,
        "DB_NAME": database,
        "ENVIRONMENT": "development",
        "SEED_DEMO_USERS": "false",
        "FRONTEND_URL": "http://localhost:3000",
        "CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
        "JWT_SECRET": secrets.token_urlsafe(48),
    })

    backend_out = (root / "backend.hml.out.log").open("a", encoding="utf-8")
    backend_err = (root / "backend.hml.err.log").open("a", encoding="utf-8")
    backend = subprocess.Popen(
        [sys.executable, "start_server.py"],
        cwd=root,
        env=backend_env,
        stdin=subprocess.DEVNULL,
        stdout=backend_out,
        stderr=backend_err,
        creationflags=creationflags,
    )
    if args.backend_only:
        print(f"backend_pid={backend.pid} target=HOMOLOGATION")
        return 0

    frontend_out = (root / "frontend.hml.out.log").open("a", encoding="utf-8")
    frontend_err = (root / "frontend.hml.err.log").open("a", encoding="utf-8")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    frontend = subprocess.Popen(
        [npm, "start", "--", "--host", "0.0.0.0", "--port", "3000"],
        cwd=root / "frontend",
        stdin=subprocess.DEVNULL,
        stdout=frontend_out,
        stderr=frontend_err,
        creationflags=creationflags,
    )
    print(f"backend_pid={backend.pid} frontend_pid={frontend.pid} target=HOMOLOGATION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
