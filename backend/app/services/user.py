
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from .auth import hash_password


def get_users(db: Session):
    return db.query(models.User).order_by(
        models.User.username
    ).all()


def create_user(db: Session, body):
    existing_user = db.query(models.User).filter(
        models.User.username == body.username
    ).first()

    if existing_user:
        raise HTTPException(409, "Username already exists")

    new_user = models.User(
        id=str(__import__("uuid").uuid4()),
        username=body.username,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        status="active"
    )

    db.add(new_user)

    try:
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        raise

    return new_user


def update_user(db: Session, user_id: str, body):
    target_user = db.query(models.User).filter(
        models.User.id == user_id
    ).first()

    if not target_user:
        raise HTTPException(404, "User not found")

    if body.role is not None:
        if body.role not in ["Admin", "Operator", "Viewer"]:
            raise HTTPException(400, "Invalid role")

        target_user.role = body.role

    if body.status is not None:
        if body.status not in ["active", "locked"]:
            raise HTTPException(400, "Invalid account status")

        target_user.status = body.status

    db.commit()
    db.refresh(target_user)

    return target_user
