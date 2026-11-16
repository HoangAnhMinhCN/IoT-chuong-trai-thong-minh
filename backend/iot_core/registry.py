
"""
MySQL Device Registry using SQLAlchemy synchronous ORM
with asyncio.to_thread().

Each database operation runs in a worker thread.
Each operation creates and closes its own SQLAlchemy Session.
"""

from __future__ import annotations

import asyncio
import json

from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ._storage import dumps, load_row

from .models import (
    Device,
    Registration,
    RegistrationStatus,
)

from app.database import SessionLocal

from app.models import (
    Device as DeviceORM,
    Registration as RegistrationORM,
)


# =========================================================
# DEVICE REGISTRY INTERFACE
# =========================================================

class DeviceRegistry(ABC):

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    @abstractmethod
    async def get_device(self, device_id: str) -> Device | None:
        ...

    @abstractmethod
    async def get_device_by_hw_id(self, hw_id: str) -> Device | None:
        ...

    @abstractmethod
    async def list_devices(self) -> list[Device]:
        ...

    @abstractmethod
    async def save_device(self, device: Device) -> None:
        ...

    @abstractmethod
    async def delete_device(self, device_id: str) -> None:
        ...

    @abstractmethod
    async def touch(
        self,
        device_id: str,
        at: datetime,
        online: bool | None = None
    ) -> None:
        ...

    @abstractmethod
    async def get_registration(
        self,
        hw_id: str
    ) -> Registration | None:
        ...

    @abstractmethod
    async def list_registrations(
        self,
        status: RegistrationStatus | None = None
    ) -> list[Registration]:
        ...

    @abstractmethod
    async def save_registration(
        self,
        registration: Registration
    ) -> None:
        ...


# =========================================================
# MYSQL IMPLEMENTATION
# =========================================================

class MySQLDeviceRegistry(DeviceRegistry):

    # =====================================================
    # DATABASE HELPERS
    # =====================================================

    @staticmethod
    def _json_value(value):
        if value is None:
            return {}

        return json.loads(dumps(value))

    @staticmethod
    def _device_to_domain(row: DeviceORM) -> Device:

        data = {
            "device_id": row.device_id,
            "hw_id": row.hw_id,

            "name": row.name or "",
            "model": row.model or "",
            "fw": row.fw or "",

            "sensors": row.sensors or [],
            "commands": row.commands or [],

            "interval_s": row.interval_s,

            "online": row.status == "online",

            "last_seen": row.last_seen,
            "registered_at": row.registered_at,
        }

        return load_row(dumps(data), Device)

    @staticmethod
    def _registration_to_domain(
        row: RegistrationORM
    ) -> Registration:

        data = {
            "hw_id": row.hw_id,

            "status": row.status,

            "requested_at": row.requested_at,
            "updated_at": row.updated_at,

            "model": row.model or "",
            "fw": row.fw or "",

            "sensors": row.sensors or [],
            "commands": row.commands or [],

            "device_id": row.device_id,

            "reason": row.reason,

            "password": row.password,
            "password_hash": row.password_hash,
        }

        return load_row(dumps(data), Registration)

    # =====================================================
    # OPEN / CLOSE
    # =====================================================

    @staticmethod
    def _open_sync():

        db: Session = SessionLocal()

        try:
            db.execute(text("SELECT 1"))

            print(
                "MySQL DeviceRegistry connected successfully."
            )

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def open(self) -> None:

        await asyncio.to_thread(
            self._open_sync
        )

    async def close(self) -> None:
        # No persistent Session is maintained.
        pass

    # =====================================================
    # DEVICE OPERATIONS
    # =====================================================

    @staticmethod
    def _get_device_sync(
        device_id: str
    ) -> Device | None:

        db = SessionLocal()

        try:
            row = db.get(
                DeviceORM,
                device_id
            )

            if row is None:
                return None

            # Convert before closing Session.
            return MySQLDeviceRegistry._device_to_domain(row)

        finally:
            db.close()

    async def get_device(
        self,
        device_id: str
    ) -> Device | None:

        return await asyncio.to_thread(
            self._get_device_sync,
            device_id
        )

    @staticmethod
    def _get_device_by_hw_id_sync(
        hw_id: str
    ) -> Device | None:

        db = SessionLocal()

        try:
            row = (
                db.query(DeviceORM)
                .filter(DeviceORM.hw_id == hw_id)
                .first()
            )

            if row is None:
                return None

            return MySQLDeviceRegistry._device_to_domain(row)

        finally:
            db.close()

    async def get_device_by_hw_id(
        self,
        hw_id: str
    ) -> Device | None:

        return await asyncio.to_thread(
            self._get_device_by_hw_id_sync,
            hw_id
        )

    @staticmethod
    def _list_devices_sync() -> list[Device]:

        db = SessionLocal()

        try:
            rows = (
                db.query(DeviceORM)
                .order_by(DeviceORM.device_id)
                .all()
            )

            return [
                MySQLDeviceRegistry._device_to_domain(row)
                for row in rows
            ]

        finally:
            db.close()

    async def list_devices(self) -> list[Device]:

        return await asyncio.to_thread(
            self._list_devices_sync
        )

    @staticmethod
    def _save_device_sync(device: Device) -> None:

        db = SessionLocal()

        try:
            row = db.get(
                DeviceORM,
                device.device_id
            )

            if row is None:
                row = DeviceORM(
                    device_id=device.device_id
                )

                db.add(row)

            row.hw_id = device.hw_id

            row.name = device.name
            row.model = device.model
            row.fw = device.fw

            row.sensors = MySQLDeviceRegistry._json_value(
                device.sensors
            )

            row.commands = MySQLDeviceRegistry._json_value(
                device.commands
            )

            row.interval_s = device.interval_s

            row.status = (
                "online" if device.online else "offline"
            )

            row.last_seen = device.last_seen
            row.registered_at = device.registered_at

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def save_device(self, device: Device) -> None:

        await asyncio.to_thread(
            self._save_device_sync,
            device
        )

    @staticmethod
    def _delete_device_sync(device_id: str) -> None:

        db = SessionLocal()

        try:
            row = db.get(
                DeviceORM,
                device_id
            )

            if row is not None:
                db.delete(row)
                db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def delete_device(
        self,
        device_id: str
    ) -> None:

        await asyncio.to_thread(
            self._delete_device_sync,
            device_id
        )

    @staticmethod
    def _touch_sync(
        device_id: str,
        at: datetime,
        online: bool | None = None
    ) -> None:

        db = SessionLocal()

        try:
            row = db.get(
                DeviceORM,
                device_id
            )

            if row is not None:

                row.last_seen = at

                if online is not None:
                    row.status = (
                        "online" if online else "offline"
                    )

                db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def touch(
        self,
        device_id: str,
        at: datetime,
        online: bool | None = None
    ) -> None:

        await asyncio.to_thread(
            self._touch_sync,
            device_id,
            at,
            online
        )

    # =====================================================
    # REGISTRATION OPERATIONS
    # =====================================================

    @staticmethod
    def _get_registration_sync(
        hw_id: str
    ) -> Registration | None:

        db = SessionLocal()

        try:
            row = db.get(
                RegistrationORM,
                hw_id
            )

            if row is None:
                return None

            return MySQLDeviceRegistry._registration_to_domain(row)

        finally:
            db.close()

    async def get_registration(
        self,
        hw_id: str
    ) -> Registration | None:

        return await asyncio.to_thread(
            self._get_registration_sync,
            hw_id
        )

    @staticmethod
    def _list_registrations_sync(
        status: RegistrationStatus | None = None
    ) -> list[Registration]:

        db = SessionLocal()

        try:
            query = db.query(RegistrationORM)

            if status is not None:
                query = query.filter(
                    RegistrationORM.status == status.value
                )

            rows = (
                query
                .order_by(RegistrationORM.hw_id)
                .all()
            )

            return [
                MySQLDeviceRegistry._registration_to_domain(row)
                for row in rows
            ]

        finally:
            db.close()

    async def list_registrations(
        self,
        status: RegistrationStatus | None = None
    ) -> list[Registration]:

        return await asyncio.to_thread(
            self._list_registrations_sync,
            status
        )

    @staticmethod
    def _save_registration_sync(
        registration: Registration
    ) -> None:

        db = SessionLocal()

        try:
            row = db.get(
                RegistrationORM,
                registration.hw_id
            )

            if row is None:
                row = RegistrationORM(
                    hw_id=registration.hw_id
                )

                db.add(row)

            row.status = registration.status.value

            row.requested_at = registration.requested_at
            row.updated_at = registration.updated_at

            row.model = registration.model
            row.fw = registration.fw

            row.sensors = MySQLDeviceRegistry._json_value(
                registration.sensors
            )

            row.commands = MySQLDeviceRegistry._json_value(
                registration.commands
            )

            row.device_id = registration.device_id

            row.reason = registration.reason

            # Do not persist plaintext passwords.
            # This requires the ORM column to allow NULL.
            row.password = None

            row.password_hash = registration.password_hash

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    async def save_registration(
        self,
        registration: Registration
    ) -> None:

        await asyncio.to_thread(
            self._save_registration_sync,
            registration
        )
