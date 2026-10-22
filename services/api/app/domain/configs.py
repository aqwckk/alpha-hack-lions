"""Loading of versioned scoring and policy configs with schema, version and sha256 checks."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Settings


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedConfig:
    config_type: str
    content: dict[str, Any]
    version: str
    sha256: str
    path: str

    @property
    def author(self) -> str | None:
        return self.content.get("author")

    @property
    def effective_from(self) -> str | None:
        return self.content.get("effective_from") or self.content.get("created_at")


def _load(path: Path, config_type: str, schema: str, expected_version: str, expected_sha: str) -> LoadedConfig:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"{config_type}: cannot read {path.name}: {exc.strerror}") from exc
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha and sha != expected_sha.lower():
        raise ConfigError(f"{config_type}: sha256 mismatch for {path.name}")
    content = json.loads(raw.decode("utf-8"))
    if content.get("schema") != schema or content.get("schema_version") != 1:
        raise ConfigError(f"{config_type}: unsupported schema {content.get('schema')}/{content.get('schema_version')}")
    version = content.get("version")
    if not version:
        raise ConfigError(f"{config_type}: version is missing")
    if expected_version and version != expected_version:
        raise ConfigError(f"{config_type}: version {version} differs from expected {expected_version}")
    return LoadedConfig(config_type, content, version, sha, path.name)


def _validate_scorecard(sc: dict[str, Any]) -> None:
    if not sc.get("factors") or not sc.get("grade_bands") or sc["grade_bands"][-1]["min_score"] is not None:
        raise ConfigError("SCORECARD: factors and grade bands ending with an open band are required")
    for factor in sc["factors"]:
        if factor["type"] not in ("numeric", "categorical") or "missing" not in factor:
            raise ConfigError(f"SCORECARD: factor {factor.get('code')} is malformed")
        if factor["type"] == "numeric":
            bins = factor["bins"]
            if bins[0]["lower"] is not None or bins[-1]["upper"] is not None:
                raise ConfigError(f"SCORECARD: bins of {factor['code']} do not cover the axis")
            for left, right in zip(bins, bins[1:], strict=False):
                if left["upper"] != right["lower"]:
                    raise ConfigError(f"SCORECARD: bins of {factor['code']} have a gap")
    if set(sc["pd_by_grade"]) != {b["grade"] for b in sc["grade_bands"]}:
        raise ConfigError("SCORECARD: pd_by_grade does not match grades")


def _validate_policy(pol: dict[str, Any]) -> None:
    required = ("products", "stop_factors", "income", "max_debt_load_by_grade", "rate_premium_by_grade", "counter_offer", "authority", "process", "rules", "reason_codes")
    missing = [k for k in required if k not in pol]
    if missing:
        raise ConfigError(f"POLICY: sections missing: {missing}")
    if [r["id"] for r in pol["rules"]] != [f"POL-0{i}" for i in range(1, 8)]:
        raise ConfigError("POLICY: rules POL-01...POL-07 are required in order")


class ConfigRegistry:
    """Active scorecard and policy; loaded once per process, reload on restart (no code change needed)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = threading.Lock()
        self.scorecard: LoadedConfig | None = None
        self.policy: LoadedConfig | None = None
        self.error: str | None = None

    def load(self) -> None:
        s = self._settings
        with self._lock:
            try:
                scorecard = _load(
                    s.analytics_artifacts_dir / s.scorecard_file, "SCORECARD", "scorecard", s.scorecard_expected_version, s.scorecard_expected_sha256
                )
                _validate_scorecard(scorecard.content)
                policy = _load(
                    s.analytics_artifacts_dir / s.policy_file, "POLICY", "credit-policy", s.policy_expected_version, s.policy_expected_sha256
                )
                _validate_policy(policy.content)
            except (ConfigError, ValueError, KeyError) as exc:
                self.error = str(exc)
                raise ConfigError(str(exc)) from exc
            self.scorecard, self.policy, self.error = scorecard, policy, None

    def require(self) -> tuple[LoadedConfig, LoadedConfig]:
        if self.scorecard is None or self.policy is None:
            try:
                self.load()
            except ConfigError:
                pass
        if self.scorecard is None or self.policy is None:
            raise ConfigError(self.error or "configs are not loaded")
        return self.scorecard, self.policy

    def policy_content(self) -> dict[str, Any]:
        return self.require()[1].content


_registry: ConfigRegistry | None = None


def get_registry(settings: Settings | None = None) -> ConfigRegistry:
    global _registry
    if _registry is None:
        from ..config import get_settings

        _registry = ConfigRegistry(settings or get_settings())
    return _registry
