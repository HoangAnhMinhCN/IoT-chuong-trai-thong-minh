"""SQLite JSON serialization shared by the two stores."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum



from .models import SensorSpec


def utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


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



def load_row(raw: str, cls):
    data = json.loads(raw)
    for key in ('last_seen', 'registered_at', 'requested_at', 'updated_at'):
        if data.get(key):
            data[key] = datetime.fromisoformat(data[key])
    data['sensors'] = [SensorSpec.from_dict(s) for s in data['sensors']]
    if 'status' in data:
        from .models import RegistrationStatus
        data['status'] = RegistrationStatus(data['status'])
    return cls(**data)
