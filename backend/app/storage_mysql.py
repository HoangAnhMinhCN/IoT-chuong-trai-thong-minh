"""MySQL implementations of the iot_core storage interfaces.

iot_core stays independent of this app: it only defines DeviceRegistry and
TelemetryStore. app/main.py injects these classes into DeviceGateway when
DATABASE_URL is configured; otherwise iot_core's SQLite stores are used.

Each database operation runs in a worker thread (asyncio.to_thread) with its
own SQLAlchemy Session.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import text
from sqlalchemy.orm import Session

from iot_core._storage import load_row
from iot_core.models import (Device, Readings, Registration, RegistrationStatus,
                             TelemetryRecord)
from iot_core.registry import DeviceRegistry
from iot_core.telemetry import TelemetryStore

from .database import SessionLocal
from .models import Device as DeviceORM
from .models import Registration as RegistrationORM
from .models import Telemetry as TelemetryORM


# JSON helpers for ORM <-> domain conversion. Unlike iot_core._storage.dumps,
# these also accept plain dicts/lists (the ORM rows are converted via dicts).
def encode(value):
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def dumps(value):
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)

    return json.dumps(
        value,
        default=encode,
        ensure_ascii=False
    )


# =========================================================
# MYSQL DEVICE REGISTRY
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

            # iot_core keeps the plain password only while the registration
            # is pending (the broker account is created on approval) and sets
            # it to None itself on approve/reject. Storing None here breaks
            # approval with "Registration has no password".
            row.password = registration.password

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


# =========================================================
# MYSQL TELEMETRY STORE
# =========================================================

class MySQLTelemetryStore(TelemetryStore):

    def __init__(self, keep_per_device: int = 10_000):
        self.keep_per_device = keep_per_device

    # =====================================================
    # CONVERSION HELPERS
    # =====================================================

    @staticmethod
    def _json_value(value):
        if value is None:
            return {}

        return json.loads(dumps(value))

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is not None:
            return value.astimezone(
                timezone.utc
            ).replace(tzinfo=None)

        return value

    @staticmethod
    def _to_domain(row: TelemetryORM) -> TelemetryRecord:

        readings_data = row.readings or {}

        readings = Readings(**readings_data)

        return TelemetryRecord(
            device_id=row.device_id,
            received_at=row.received_at,
            device_ts=row.device_ts,
            readings=readings
        )

    # =====================================================
    # DATABASE OPERATIONS - SYNCHRONOUS
    # =====================================================

    @staticmethod
    def _open_sync():
        db: Session = SessionLocal()

        try:
            db.execute(text("SELECT 1"))
            print("MySQL TelemetryStore connected successfully.")

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    @staticmethod
    def _append_sync(record, keep_per_device):

        db = SessionLocal()

        try:
            row = TelemetryORM(
                device_id=record.device_id,
                received_at=MySQLTelemetryStore._normalize_datetime(
                    record.received_at
                ),
                device_ts=record.device_ts,
                readings=MySQLTelemetryStore._json_value(
                    record.readings
                )
            )

            db.add(row)
            db.flush()

            old_ids = (
                db.query(TelemetryORM.id)
                .filter(
                    TelemetryORM.device_id == record.device_id
                )
                .order_by(
                    TelemetryORM.received_at.desc(),
                    TelemetryORM.id.desc()
                )
                .offset(keep_per_device)
                .all()
            )

            if old_ids:
                ids = [item[0] for item in old_ids]

                db.query(TelemetryORM).filter(
                    TelemetryORM.id.in_(ids)
                ).delete(synchronize_session=False)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    @staticmethod
    def _latest_sync(device_id: str):

        db = SessionLocal()

        try:
            row = (
                db.query(TelemetryORM)
                .filter(
                    TelemetryORM.device_id == device_id
                )
                .order_by(
                    TelemetryORM.received_at.desc(),
                    TelemetryORM.id.desc()
                )
                .first()
            )

            if row is None:
                return None

            return MySQLTelemetryStore._to_domain(row)

        finally:
            db.close()

    @staticmethod
    def _history_sync(device_id, limit, since):

        db = SessionLocal()

        try:
            query = db.query(TelemetryORM).filter(
                TelemetryORM.device_id == device_id
            )

            if since is not None:
                query = query.filter(
                    TelemetryORM.received_at >=
                    MySQLTelemetryStore._normalize_datetime(since)
                )

            rows = (
                query
                .order_by(
                    TelemetryORM.received_at.desc(),
                    TelemetryORM.id.desc()
                )
                .limit(limit)
                .all()
            )

            return [
                MySQLTelemetryStore._to_domain(row)
                for row in rows
            ]

        finally:
            db.close()

    @staticmethod
    def _delete_device_sync(device_id: str):

        db = SessionLocal()

        try:
            db.query(TelemetryORM).filter(
                TelemetryORM.device_id == device_id
            ).delete(synchronize_session=False)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            db.close()

    # =====================================================
    # ASYNC INTERFACE
    # =====================================================

    async def open(self) -> None:

        if self.keep_per_device < 1:
            raise ValueError(
                "keep_per_device must be positive"
            )

        await asyncio.to_thread(
            self._open_sync
        )

    async def close(self) -> None:
        pass

    async def append(self, record: TelemetryRecord) -> None:

        await asyncio.to_thread(
            self._append_sync,
            record,
            self.keep_per_device
        )

    async def latest(
        self,
        device_id: str
    ) -> TelemetryRecord | None:

        return await asyncio.to_thread(
            self._latest_sync,
            device_id
        )

    async def history(
        self,
        device_id: str,
        limit: int = 100,
        since: datetime | None = None
    ) -> list[TelemetryRecord]:

        if limit < 1:
            raise ValueError("limit must be positive")

        return await asyncio.to_thread(
            self._history_sync,
            device_id,
            limit,
            since
        )

    async def delete_device(self, device_id: str) -> None:

        await asyncio.to_thread(
            self._delete_device_sync,
            device_id
        )
