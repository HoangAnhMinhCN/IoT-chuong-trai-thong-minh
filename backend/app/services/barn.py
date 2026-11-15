
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models


def get_barns(db: Session, current_user):
    if current_user.role == "Admin":
        return db.query(models.Barn).all()

    return (
        db.query(models.Barn)
        .join(
            models.BarnAssignment,
            models.Barn.id == models.BarnAssignment.barn_id
        )
        .filter(
            models.BarnAssignment.user_id == current_user.id
        )
        .all()
    )


def create_barn(db: Session, body):
    new_barn = models.Barn(
        id=str(uuid.uuid4()),
        name=body.name,
        zone=body.zone,
        animal_type=body.animal_type
    )

    db.add(new_barn)

    try:
        db.commit()
        db.refresh(new_barn)
    except Exception:
        db.rollback()
        raise

    return new_barn


def assign_users(db: Session, barn_id: str, body):
    target_barn = db.query(models.Barn).filter(
        models.Barn.id == barn_id
    ).first()

    if not target_barn:
        raise HTTPException(404, "Barn not found")

    # Assumes body contains user_id and access_level
    target_user = db.query(models.User).filter(
        models.User.id == body.user_id
    ).first()

    if not target_user:
        raise HTTPException(404, "User not found")

    if target_user.role not in ["Operator", "Viewer"]:
        raise HTTPException(
            400,
            "Only Operator or Viewer can be assigned to a barn"
        )

    if body.access_level not in ["Operator", "Viewer"]:
        raise HTTPException(400, "Invalid access level")

    if target_user.role != body.access_level:
        raise HTTPException(
            400,
            "Access level must match the user's role"
        )

    assignment = db.query(models.BarnAssignment).filter(
        models.BarnAssignment.user_id == body.user_id,
        models.BarnAssignment.barn_id == barn_id
    ).first()

    if assignment:
        assignment.access_level = body.access_level
    else:
        assignment = models.BarnAssignment(
            user_id=body.user_id,
            barn_id=barn_id,
            access_level=body.access_level
        )
        db.add(assignment)

    db.commit()

    return {
        "message": "User assigned successfully",
        "barn_id": barn_id,
        "user_id": body.user_id,
        "access_level": body.access_level
    }
