"""Runtime settings of the integrations mock (environment variables only)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    analytics_dir: Path
    delay_ms_min: int
    delay_ms_max: int
    timeout_sleep_seconds: float
    api_key: str
    as_of: str
    log_level: str


def load_settings() -> Settings:
    here = Path(__file__).resolve()
    default_dir = (here.parents[3] if len(here.parents) > 3 else here.parents[1]) / "analytics"
    return Settings(
        analytics_dir=Path(os.environ.get("ANALYTICS_DIR", str(default_dir))),
        delay_ms_min=_int("MOCK_DELAY_MS_MIN", 200),
        delay_ms_max=_int("MOCK_DELAY_MS_MAX", 800),
        timeout_sleep_seconds=_float("MOCK_TIMEOUT_SLEEP_SECONDS", 6.0),
        api_key=os.environ.get("MOCK_API_KEY", "").strip(),
        as_of=os.environ.get("MOCK_AS_OF", "").strip(),
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    )
