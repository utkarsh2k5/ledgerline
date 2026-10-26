from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def audit(db: Session, actor: str, action: str, entity: str, entity_id: Any, **details: Any) -> None:
    """Append an audit record. Caller owns the transaction."""
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            details=details,
        )
    )
