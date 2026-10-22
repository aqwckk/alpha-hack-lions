"""Effective process parameters: policy.process values, optionally shortened by environment for demos."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ..domain.configs import get_registry


@dataclass(frozen=True)
class ProcessParams:
    offer_ttl_seconds: float
    info_request_ttl_seconds: float
    draft_ttl_seconds: float
    review_sla_seconds: float
    max_auto_info_cycles: int
    underwriter_authority_limit: str
    override_requires_risk_approval: bool


def process_params() -> ProcessParams:
    s = get_settings()
    pol = get_registry().policy_content()
    proc = pol["process"]
    return ProcessParams(
        offer_ttl_seconds=s.offer_ttl_seconds or proc["offer_ttl_days"] * 86400,
        info_request_ttl_seconds=s.info_request_ttl_seconds or proc["info_response_ttl_days"] * 86400,
        draft_ttl_seconds=s.draft_ttl_seconds or proc["draft_ttl_days"] * 86400,
        review_sla_seconds=s.manual_review_sla_seconds or proc["manual_review_sla_hours"] * 3600,
        max_auto_info_cycles=int(proc["max_auto_info_cycles"]),
        underwriter_authority_limit=pol["authority"]["underwriter_authority_limit"],
        override_requires_risk_approval=bool(pol["authority"]["override_requires_risk_approval"]),
    )
