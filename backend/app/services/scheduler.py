
import asyncio
import calendar

from datetime import datetime, timezone, timedelta
from sqlalchemy import update

from ..database import SessionLocal
from .. import models


def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def calculate_next_run(current_run_at, repeat_type):
    if repeat_type == "daily":
        return current_run_at + timedelta(days=1)

    if repeat_type == "weekly":
        return current_run_at + timedelta(weeks=1)

    if repeat_type == "monthly":
        year = current_run_at.year
        month = current_run_at.month

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

        last_day = calendar.monthrange(year, month)[1]
        day = min(current_run_at.day, last_day)

        return current_run_at.replace(
            year=year,
            month=month,
            day=day
        )

    return None


# =========================================================
# DATABASE OPERATIONS - SYNCHRONOUS
# =========================================================

def claim_event_sync(event_id: str):
    """
    Atomically claim a pending event.
    Return event data or None if another worker claimed it.
    """

    db = SessionLocal()

    try:
        result = db.execute(
            update(models.ScheduledEvent)
            .where(
                models.ScheduledEvent.id == event_id,
                models.ScheduledEvent.status == "pending",
                models.ScheduledEvent.run_at <= utc_now_naive()
            )
            .values(status="running")
        )

        db.commit()

        if result.rowcount != 1:
            return None

        event = db.get(models.ScheduledEvent, event_id)

        if event is None:
            return None

        # Return plain data, not a detached ORM object.
        return {
            "device_id": event.device_id,
            "command_name": event.command_name,
            "args": event.args,
            "current_run_at": event.run_at,
            "repeat_type": event.repeat_type
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def update_event_result_sync(
    event_id: str,
    event_data: dict,
    success: bool,
    error: str | None = None
):
    db = SessionLocal()

    try:
        event = db.get(models.ScheduledEvent, event_id)

        if event is None:
            return

        if success:
            repeat_type = event_data["repeat_type"]

            if repeat_type == "once":
                event.status = "succeeded"

            else:
                next_run = calculate_next_run(
                    event_data["current_run_at"],
                    repeat_type
                )

                if next_run is not None:
                    event.run_at = next_run
                    event.status = "pending"
                    event.error = None
                else:
                    event.status = "failed"
                    event.error = "Invalid repeat type"

        else:
            event.status = "failed"
            event.error = error

        event.executed_at = utc_now_naive()

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def get_due_events_sync():
    db = SessionLocal()

    try:
        events = db.query(
            models.ScheduledEvent.id
        ).filter(
            models.ScheduledEvent.status == "pending",
            models.ScheduledEvent.run_at <= utc_now_naive()
        ).all()

        return [event.id for event in events]

    finally:
        db.close()


# =========================================================
# ASYNC OPERATIONS
# =========================================================

async def execute_event(app, event_id: str):

    # Run SQLAlchemy in a worker thread.
    event_data = await asyncio.to_thread(
        claim_event_sync,
        event_id
    )

    if event_data is None:
        return

    # No database Session is held while waiting for MQTT.
    try:
        await app.state.gateway.send_command(
            event_data["device_id"],
            event_data["command_name"],
            event_data["args"]
        )

        success = True
        error = None

    except asyncio.CancelledError:
        # Event remains running and needs recovery after restart.
        raise

    except Exception as exc:
        success = False
        error = str(exc) or type(exc).__name__

    # Update database in a worker thread.
    await asyncio.to_thread(
        update_event_result_sync,
        event_id,
        event_data,
        success,
        error
    )


async def scheduler_loop(app):

    while True:
        try:
            event_ids = await asyncio.to_thread(
                get_due_events_sync
            )

            for event_id in event_ids:
                try:
                    await execute_event(app, event_id)

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    print(
                        f"Scheduled event {event_id} failed: {exc}"
                    )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(f"Scheduler loop error: {exc}")

        await asyncio.sleep(1)
