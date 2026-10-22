"""Test harness: real PostgreSQL (DATABASE_URL), the API and the integrations mock served by uvicorn in-process.

The worker is driven synchronously (Worker.run_until_idle) so the pipeline is deterministic in tests.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

_HERE = Path(__file__).resolve()
ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parents[1]  # repository checkout or the test image (/app)
API_DIR = Path(__file__).resolve().parents[1]
MOCK_DIR = Path(os.environ.get("MOCK_APP_DIR", ROOT / "services" / "integrations-mock"))
ANALYTICS_DIR = Path(os.environ.get("ANALYTICS_DIR", ROOT / "analytics"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MOCK_PORT = _free_port()
API_PORT = _free_port()

os.environ.update(
    {
        "APP_ENV": "test",
        "DEMO_MODE": "true",
        "LOG_LEVEL": "WARNING",
        "ANALYTICS_ARTIFACTS_DIR": str(ANALYTICS_DIR / "artifacts"),
        "INTEGRATIONS_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}",
        "SOURCE_TIMEOUT_SECONDS": "0.5",
        "PREFILL_TIMEOUT_SECONDS": "2",
        "SOURCE_FAST_RETRY_DELAYS": "0",
        "ENRICHMENT_RETRY_SCHEDULE": "0,0,0,0,0",
        "OPERATION_ATTEMPTS": "2",
        "JOB_BACKOFF_BASE_SECONDS": "0",
        "TIMER_INTERVAL_SECONDS": "0",
        "SEED_HISTORY": "false",
        "MOCK_DELAY_MS_MIN": "0",
        "MOCK_DELAY_MS_MAX": "0",
        "MOCK_TIMEOUT_SLEEP_SECONDS": "0.8",
        "ANALYTICS_DIR": str(ANALYTICS_DIR),
    }
)
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://credit_test:credit_test@localhost:5432/credit_test")
sys.path.insert(0, str(API_DIR))

import httpx  # noqa: E402
import uvicorn  # noqa: E402


def _serve(app: Any, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("server did not start")
        time.sleep(0.05)
    return server


@pytest.fixture(scope="session")
def mock_app():
    """The integrations mock, loaded as package "mockapp" (the api package is also called "app")."""
    import importlib
    import types

    pkg = types.ModuleType("mockapp")
    pkg.__path__ = [str(MOCK_DIR / "app")]
    sys.modules["mockapp"] = pkg
    module = importlib.import_module("mockapp.main")
    server = _serve(module.app, MOCK_PORT)
    yield module.app
    server.should_exit = True


@pytest.fixture(scope="session")
def database(mock_app):
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    command.upgrade(cfg, "head")
    from app import seed
    from app.db import session_scope

    with session_scope() as session:
        seed.seed_users(session)
    yield


@pytest.fixture(scope="session")
def api_server(database):
    from app.main import app

    server = _serve(app, API_PORT)
    yield f"http://127.0.0.1:{API_PORT}"
    server.should_exit = True


@pytest.fixture(scope="session")
def worker(database):
    from app.worker.runner import Worker

    w = Worker("test-worker")

    def drain(rounds: int = 30) -> None:
        for _ in range(rounds):
            if w.run_until_idle() == 0:
                w.run_timers()
                if w.run_until_idle() == 0:
                    return

    w.drain = drain  # type: ignore[attr-defined]
    return w


@pytest.fixture(autouse=True)
def reset_mock(mock_app):
    mock_app.state.behavior.reset()
    yield


PASSWORDS = {"CLIENT": "Demo-Client-2026", "UNDERWRITER": "Demo-Uw-2026", "RISK_MANAGER": "Demo-Risk-2026"}
ROLE_OF = {"uw": "UNDERWRITER", "risk": "RISK_MANAGER", "client": "CLIENT"}


class Api:
    def __init__(self, base: str, login: str):
        self.http = httpx.Client(base_url=base, timeout=30)
        role = ROLE_OF[login.split(".")[0]]
        r = self.http.post("/api/v1/auth/login", json={"login": login, "password": PASSWORDS[role]})
        assert r.status_code == 200, r.text
        self.http.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        self.login = login

    def post(self, path: str, body: Any = None, *, key: str | None = "auto", expect: int | None = 200) -> httpx.Response:
        headers = {"Idempotency-Key": uuid.uuid4().hex if key == "auto" else key} if key else {}
        r = self.http.post(path, json=body, headers=headers)
        if expect is not None:
            assert r.status_code == expect, f"{path}: {r.status_code} {r.text[:600]}"
        return r

    def get(self, path: str, expect: int | None = 200) -> httpx.Response:
        r = self.http.get(path)
        if expect is not None:
            assert r.status_code == expect, f"{path}: {r.status_code} {r.text[:600]}"
        return r

    def patch(self, path: str, body: Any) -> httpx.Response:
        r = self.http.patch(path, json=body)
        assert r.status_code == 200, r.text[:600]
        return r

    def put(self, path: str, body: Any = None) -> httpx.Response:
        r = self.http.put(path, json=body)
        assert r.status_code == 200, r.text[:600]
        return r


@pytest.fixture(scope="session")
def login(api_server):
    cache: dict[str, Api] = {}

    def get(name: str) -> Api:
        if name not in cache:
            cache[name] = Api(api_server, name)
        return cache[name]

    return get


PROFILES = {
    "S1": ("client.irina", "002000010193", {"product_code": "EXPRESS", "purpose": "EQUIPMENT", "amount": "1200000", "term_months": 24},
           {"representative_role": "OWNER", "monthly_revenue_declared": "1500000", "existing_monthly_payments_declared": "0"}, []),
    "S3": ("client.marina", "0010003018", {"product_code": "INVESTMENT", "purpose": "EQUIPMENT", "amount": "40000000", "term_months": 60},
           {"representative_role": "CFO", "monthly_revenue_declared": "6750000", "existing_monthly_payments_declared": "600000", "owner_guarantee_agreed": True,
            "collateral_type": "PURCHASED_ASSET", "collateral_description": "Линия упаковки, приобретаемая по договору", "collateral_value": "48000000",
            "collateral_owner": "APPLICANT", "investment_project_description": "Вторая линия упаковки под контракт с торговой сетью"},
           ["COLLATERAL_DOCUMENTS", "SUPPLIER_QUOTE"]),
    "S5": ("client.oleg", "0010005015", {"product_code": "EXPRESS", "purpose": "INVENTORY", "amount": "3000000", "term_months": 24},
           {"representative_role": "FINANCE_MANAGER", "monthly_revenue_declared": "6000000", "existing_monthly_payments_declared": "300000", "owner_guarantee_agreed": True}, []),
}
PDF = b"%PDF-1.4\n%%EOF\n"


@pytest.fixture(scope="session")
def draft_ready(login):
    """Create a draft for a demo profile with all fields, documents and consents; returns (client, view)."""

    def make(profile: str) -> tuple[Api, dict[str, Any]]:
        user, inn, create, fields, docs = PROFILES[profile]
        client = login(user)
        for item in client.get("/api/v1/applications?page_size=100").json()["items"]:
            view = client.get(f"/api/v1/applications/{item['id']}").json()
            if "WITHDRAW" in view["available_actions"]:
                client.post(f"/api/v1/applications/{item['id']}/withdraw", {"expected_version": view["version"]})
            elif "DECLINE_OFFER" in view["available_actions"]:
                client.post(f"/api/v1/applications/{item['id']}/offer/decline", {"expected_version": view["version"]})
        view = client.post("/api/v1/applications", create, expect=201).json()
        view = client.post(f"/api/v1/applications/{view['id']}/prefill", {"expected_version": view["version"], "inn": inn}, key=None).json()["application"]
        view = client.patch(f"/api/v1/applications/{view['id']}", {"expected_version": view["version"], **fields}).json()["application"]
        for doc in docs:
            r = client.http.post(f"/api/v1/applications/{view['id']}/documents", data={"document_type": doc}, files={"file": (f"{doc}.pdf", PDF, "application/pdf")})
            assert r.status_code == 201, r.text
            view = r.json()
        for consent in ("CONSENT_PERSONAL_DATA", "CONSENT_CREDIT_BUREAU", "AUTHORITY_CONFIRMATION"):
            view = client.put(f"/api/v1/applications/{view['id']}/consents/{consent}", {"expected_version": view["version"]}).json()
        return client, view

    return make
