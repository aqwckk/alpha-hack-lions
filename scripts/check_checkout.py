"""Verify checkout bytes used by Linux containers, including core.autocrlf=true checkouts."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    defaults = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#") and "=" in line)
    for name, key in (("scorecard.v1.json", "SCORECARD_EXPECTED_SHA256"), ("policy.v1.json", "POLICY_EXPECTED_SHA256")):
        data = (ROOT / "analytics" / "artifacts" / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != defaults[key]:
            raise SystemExit(f"{name}: checksum mismatch; check LF checkout and configured SHA256")
        print(f"{name}: checksum OK")
    for path in (ROOT / "deploy").rglob("*.sh"):
        if b"\r" in path.read_bytes():
            raise SystemExit(f"{path.relative_to(ROOT)}: expected LF line endings")
    print("Deployment scripts: LF OK")


if __name__ == "__main__":
    main()
