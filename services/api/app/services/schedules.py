"""Read the fixed schedule of a prepared document package, including older packages."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DocumentPackage, GeneratedDocument, IntegrationRequest


def package_schedule(session: Session, package: DocumentPackage) -> list[dict[str, Any]]:
    intent = session.get(IntegrationRequest, f"EDO:{package.application_id}:{package.offer_option_id}")
    if intent is not None and intent.request.get("schedule"):
        return intent.request["schedule"]
    content = session.execute(select(GeneratedDocument.content).where(
        GeneratedDocument.package_id == package.id, GeneratedDocument.document_type == "PAYMENT_SCHEDULE",
    )).scalar_one()
    rows = []
    for line in content.splitlines():
        columns = [c.strip() for c in line.split("|")]
        if len(columns) == 6 and columns[0].isdigit():
            rows.append(dict(zip(("n", "date", "payment", "interest", "principal", "balance"), [int(columns[0]), *columns[1:]], strict=True)))
    if not rows:
        raise ValueError("The prepared package has no payment schedule")
    return rows
