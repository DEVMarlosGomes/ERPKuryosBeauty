"""
conftest.py — Configuração de testes do KURYOS.

Dois problemas resolvidos aqui:

1. ASGITransport (httpx) não dispara eventos lifespan do FastAPI, então
   init_cq / init_estoque / etc. nunca são chamados → get_current_user = None.
   Fix: chamar startup() explicitamente em fixture autouse de sessão.

2. pytest-asyncio por padrão cria um event loop por função de teste. Fixtures
   de sessão (admin_client) criam objetos no loop de sessão; testes tentam
   usá-los em loops de função → "Future attached to a different loop".
   Fix: sobrescrever event_loop com escopo de sessão.
"""

import asyncio
import os
import sys

# Env vars devem ser definidas ANTES de importar server.py
os.environ.setdefault("DB_NAME", "kuryos_cq_test")
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("JWT_SECRET", "cq-test-jwt-secret-not-for-production-only")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import pytest
import pytest_asyncio
from server import startup, shutdown


@pytest.fixture(scope="session")
def event_loop():
    """Loop de sessão único — evita 'Future attached to a different loop'."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def app_lifespan(event_loop):
    """Dispara startup() antes dos testes (substitui o lifespan do ASGI)."""
    await startup()
    yield
    await shutdown()
