
from __future__ import annotations

import asyncio

from datetime import datetime, timezone
from abc import ABC, abstractmethod
import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from ._storage import dumps
from .models import Readings, TelemetryRecord

from app.database import SessionLocal
from app.models import Telemetry as TelemetryORM


class TelemetryStore(ABC):

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    @abstractmethod
    async def append(self, record: TelemetryRecord) -> None:
        ...

    @abstractmethod
    async def latest(self, device_id: str) -> TelemetryRecord | None:
        ...

    @abstractmethod
    async def history(
        self,
        device_id: str,
        limit: int = 100,
        since: datetime | None = None
    ) -> list[TelemetryRecord]:
        ...

    @abstractmethod
    async def delete_device(self, device_id: str) -> None:
        ...


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
