"""Application settings from environment variables (12-factor). Safe demo defaults, no secrets in code."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_HERE = Path(__file__).resolve()
# repository checkout: services/api/app/config.py; container: /app/app/config.py
REPO_ROOT = _HERE.parents[3] if len(_HERE.parents) > 3 else _HERE.parents[1]


def _seconds_list(value: str) -> list[float]:
    return [float(x) for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: str = "demo"
    demo_mode: bool = True
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://credit_app:credit_app@localhost:5432/credit"
    db_pool_size: int = 10
    db_statement_timeout_ms: int = 15000

    # analytics artifacts (configs, demo data, synthetic history)
    analytics_artifacts_dir: Path = REPO_ROOT / "analytics" / "artifacts"
    scorecard_file: str = "scorecard.v1.json"
    policy_file: str = "policy.v1.json"
    scorecard_expected_version: str = ""
    scorecard_expected_sha256: str = ""
    policy_expected_version: str = ""
    policy_expected_sha256: str = ""
    seed_history: bool = True

    # auth
    jwt_secret: str = ""
    jwt_issuer: str = "credit-api"
    jwt_audience: str = "credit-web"
    access_token_ttl_seconds: int = 1800
    refresh_token_ttl_seconds: int = 43200
    refresh_cookie_secure: bool = False
    login_max_failures: int = 5
    login_lockout_seconds: int = 60
    cors_origins: str = "http://localhost:8080,http://localhost:5173"

    # integrations
    integrations_base_url: str = "http://localhost:8090"
    integrations_api_key: str = ""
    source_timeout_seconds: float = 5.0
    source_fast_retry_delays: str = "1,2,4"
    source_attempts: int = 3
    enrichment_retry_schedule: str = "30,60,120,300,600"
    source_cache_ttl_seconds: int = 86400
    prefill_timeout_seconds: float = 5.0
    operation_attempts: int = 3
    operation_timeout_seconds: float = 10.0

    # process timers (empty: value from policy.process)
    offer_ttl_seconds: int | None = None
    info_request_ttl_seconds: int | None = None
    draft_ttl_seconds: int | None = None
    manual_review_sla_seconds: int | None = None
    offer_expiring_notice_seconds: int = 86400
    signing_code_ttl_seconds: int = 300
    signing_code_max_attempts: int = 3
    signing_codes_per_hour: int = 5
    consent_bki_ttl_days: int = 183

    # worker
    worker_poll_interval_seconds: float = 1.0
    timer_interval_seconds: float = 15.0
    job_max_attempts: int = 5
    job_backoff_base_seconds: float = 2.0
    job_lease_seconds: int = 300
    worker_metrics_port: int = 9100

    # documents
    max_document_bytes: int = 10 * 1024 * 1024
    max_documents_per_application: int = 20
    max_json_body_bytes: int = 1024 * 1024

    # optional AI (Ollama, open-weight model)
    ollama_url: str = ""
    ollama_model: str = "qwen2.5:1.5b-instruct"
    ai_timeout_seconds: float = 10.0

    @field_validator("offer_ttl_seconds", "info_request_ttl_seconds", "draft_ttl_seconds", "manual_review_sla_seconds", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v in ("", None) else v

    @property
    def fast_retry_delays(self) -> list[float]:
        return _seconds_list(self.source_fast_retry_delays)

    @property
    def retry_schedule(self) -> list[float]:
        return _seconds_list(self.enrichment_retry_schedule)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    jwt_algorithm: str = Field(default="HS256", frozen=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
