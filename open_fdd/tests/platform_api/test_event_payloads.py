# Event payload shape tests for WS events (fault.raised, crud.*, etc.)

from datetime import datetime, timezone

from open_fdd.platform.api.schemas import EventEnvelope
from open_fdd.platform.realtime.events import (
    TOPIC_FAULT_RAISED,
    TOPIC_FAULT_CLEARED,
    TOPIC_CRUD_POINT,
)


def test_event_envelope_has_type_topic_ts_data():
    env = EventEnvelope(
        type="event",
        topic="fault.raised",
        ts=datetime.now(timezone.utc).isoformat(),
        data={"site_id": "s1", "equipment_id": "e1", "fault_id": "f1"},
    )
    assert env.type == "event"
    assert env.topic == "fault.raised"
    assert "T" in env.ts
    assert env.data["fault_id"] == "f1"


def test_fault_raised_topic_constant():
    assert TOPIC_FAULT_RAISED == "fault.raised"
    assert TOPIC_FAULT_CLEARED == "fault.cleared"


def test_crud_point_topic_prefix():
    assert TOPIC_CRUD_POINT == "crud.point"
    assert TOPIC_CRUD_POINT + ".created" == "crud.point.created"
