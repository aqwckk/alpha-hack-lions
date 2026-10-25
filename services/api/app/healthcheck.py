"""Container readiness: configuration integrity, database access and worker progress."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from .config import get_settings
from .domain.configs import get_registry

HEARTBEAT = Path("/tmp/credit-worker-heartbeat")


def main() -> int:
    settings = get_settings()
    try:
        get_registry().load()
        engine = create_engine(settings.database_url, poolclass=NullPool, connect_args={"connect_timeout": 2, "options": "-c statement_timeout=1500"})
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT id FROM jobs LIMIT 0"))
        finally:
            engine.dispose()
        if len(sys.argv) > 1 and sys.argv[1] == "worker":
            age = time.time() - HEARTBEAT.stat().st_mtime
            if age < -5 or age > settings.job_lease_seconds:
                return 1
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
