"""Source responses: demo companies from analytics artifacts and the shared deterministic generator.

The generator is not re-implemented here: analytics/src/mockgen.py (stdlib only) is imported
as is, so the mock and the analytics population share one data-generating process.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

SOURCES = ("REGISTRY", "FNS", "FINANCIAL_STATEMENTS", "CREDIT_BUREAU", "BANK_TURNOVER")

W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
W12_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights)) % 11 % 10


def inn_is_valid(inn: str) -> bool:
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return _check_digit(inn[:9], W10) == int(inn[9])
    if len(inn) == 12:
        return _check_digit(inn[:10], W12_1) == int(inn[10]) and _check_digit(inn[:11], W12_2) == int(inn[11])
    return False


class ProfileStore:
    def __init__(self, analytics_dir: Path):
        if str(analytics_dir) not in sys.path:
            sys.path.insert(0, str(analytics_dir))
        from src import mockgen  # noqa: PLC0415  (analytics generator, imported from the shared directory)

        self._mockgen = mockgen
        raw = json.loads((analytics_dir / "artifacts" / "demo_companies.json").read_text(encoding="utf-8"))
        self.version = raw.get("version")
        self.companies: dict[str, dict[str, Any]] = {c["inn"]: c for c in raw["companies"]}

    def mock_behavior(self, inn: str) -> dict[str, Any]:
        company = self.companies.get(inn)
        return dict(company.get("mock_behavior") or {}) if company else {}

    def profile(self, inn: str, as_of: date) -> dict[str, Any]:
        """Bodies of all five sources for the INN on the given date."""
        company = self.companies.get(inn)
        if company is None:
            return self._mockgen.generate_profile(inn, as_of)
        sources = copy.deepcopy(company["sources"])
        reg = sources.get("REGISTRY") or {}
        if reg.get("found") and company.get("registration_months_ago") is not None:
            reg["registration_date"] = self._mockgen.sub_months(as_of, int(company["registration_months_ago"])).isoformat()
        return sources

    @staticmethod
    def month_labels(as_of: date) -> list[str]:
        """Labels of the 12 last full months, from old to new (matches inflow_by_month)."""
        labels = []
        y, m = as_of.year, as_of.month
        for _ in range(12):
            m -= 1
            if m == 0:
                y, m = y - 1, 12
            labels.append(f"{y:04d}-{m:02d}")
        return list(reversed(labels))
