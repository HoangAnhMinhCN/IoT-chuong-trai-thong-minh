from .database import SessionLocal
from . import models
import bcrypt
import uuid


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


db = SessionLocal()

try:
    # Check whether username already exists
    existing_user = db.query(models.User).filter(
        models.User.username == "admin"
    ).first()

    if existing_user:
        print("Admin account already exists!")

    else:
        admin = models.User(
            id=str(uuid.uuid4()),
            username="admin",
            password_hash=hash_password("Admin@123456"),
            full_name="System Administrator",
            role="Admin",
            status="active"
        )

        db.add(admin)
        db.commit()

        print("Admin account created successfully!")

except Exception as e:
    db.rollback()
    print("Error:", e)

finally:
    db.close()