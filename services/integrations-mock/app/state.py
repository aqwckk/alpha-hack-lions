"""In-memory state of the mock: failure behaviour counters, outages, EDO packages and ABS operations.

The state is process-local by design (a simulator, not a system of record). A restart clears it;
the API keeps its own records and idempotency keys, so a lost mock state never duplicates a loan
on the bank side.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

FAILURES = ("TIMEOUT", "HTTP_500")


@dataclass
class BehaviorState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    counters: dict[tuple[str, str], int] = field(default_factory=dict)
    overrides: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    outages: dict[str, str] = field(default_factory=dict)
    requests_total: dict[str, int] = field(default_factory=dict)

    def reset(self) -> None:
        with self.lock:
            self.counters.clear()
            self.overrides.clear()
            self.outages.clear()

    def decide_failure(self, source: str, inn: str, configured: dict[str, Any] | None) -> str | None:
        """Register one request and return the failure to simulate (or None)."""
        with self.lock:
            self.requests_total[source] = self.requests_total.get(source, 0) + 1
            outage = self.outages.get(source)
            if outage:
                return outage
            behavior = self.overrides.get((source, inn)) or configured
            if not behavior:
                return None
            key = (source, inn)
            n = self.counters.get(key, 0) + 1
            self.counters[key] = n
            if n <= int(behavior.get("fail_first_n", 0)):
                return str(behavior.get("failure", "HTTP_500"))
            return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "outages": dict(self.outages),
                "overrides": [
                    {"source": s, "inn": i, **b} for (s, i), b in self.overrides.items()
                ],
                "counters": [{"source": s, "inn": i, "requests": n} for (s, i), n in self.counters.items()],
                "requests_total": dict(self.requests_total),
            }


@dataclass
class LedgerState:
    """EDO packages and ABS operations keyed by idempotency key."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    package_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    package_keys: dict[str, tuple[str, str]] = field(default_factory=dict)
    signatures: dict[str, dict[str, Any]] = field(default_factory=dict)
    operations: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    contract_seq: int = 0
