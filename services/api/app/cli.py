"""Commands of the image: api, worker, migrate (alembic upgrade + seed), seed, export-openapi.

Usage: python -m app.cli <command>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "api"
    from .config import get_settings
    from .logging_setup import configure_logging

    settings = get_settings()
    if command == "export-openapi":
        from .main import create_app

        out = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n"
        if len(argv) > 2:
            Path(argv[2]).write_text(out, encoding="utf-8")
        else:
            sys.stdout.write(out)
        return 0
    configure_logging(command, settings.log_level)
    if command in ("migrate", "seed"):
        if command == "migrate":
            from alembic import command as alembic_command
            from alembic.config import Config

            cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
            alembic_command.upgrade(cfg, "head")
        from . import seed

        seed.run()
        return 0
    if command == "worker":
        from .worker.runner import Worker

        Worker().run_forever()
        return 0
    if command == "api":
        import uvicorn

        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*", log_config=None, access_log=False)
        return 0
    sys.stderr.write(f"unknown command {command}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
