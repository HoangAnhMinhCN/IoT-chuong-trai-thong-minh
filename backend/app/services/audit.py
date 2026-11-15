
from sqlalchemy.orm import Session

from .. import models


def get_audit_logs(
    db: Session,
    limit: int = 100,
    offset: int = 0
):
    return (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.ts.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
