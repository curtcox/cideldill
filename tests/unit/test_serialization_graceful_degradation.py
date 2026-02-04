import logging

import pytest

from cideldill_client.custom_picklers import UnpicklablePlaceholder
from cideldill_client.exceptions import DebugSerializationError
from cideldill_client.serialization import _safe_dumps, deserialize, serialize


class ExplodingState:
    def __getstate__(self):
        raise TypeError("no state for you")


class UnpicklableContainer:
    def __init__(self):
        self.ok = 123
        self.bad = ExplodingState()
        self.loop = self

    def __getstate__(self):
        raise TypeError("container boom")


def test_serialize_degrades_to_placeholder_with_attribute_snapshot():
    data = serialize(UnpicklableContainer())
    restored = deserialize(data)

    assert isinstance(restored, UnpicklablePlaceholder)
    assert restored.type_name == "UnpicklableContainer"
    assert restored.attributes["ok"] == 123
    assert "bad" in restored.failed_attributes
    assert "TypeError" in restored.failed_attributes["bad"]


def test_safe_dumps_respects_depth_limit():
    data = _safe_dumps(UnpicklableContainer(), max_depth=0)
    restored = deserialize(data)

    assert isinstance(restored, UnpicklablePlaceholder)
    assert restored.depth == 0
    assert restored.attributes == {}


def test_circular_reference_becomes_placeholder():
    data = serialize(UnpicklableContainer())
    restored = deserialize(data)

    loop_value = restored.attributes["loop"]
    assert isinstance(loop_value, UnpicklablePlaceholder)
    assert "circular" in loop_value.pickle_error.lower()


def test_serialize_strict_raises_debug_serialization_error():
    with pytest.raises(DebugSerializationError):
        serialize(UnpicklableContainer(), strict=True)


def test_safe_dumps_logging_extra_does_not_overwrite_logrecord(caplog):
    with caplog.at_level(logging.INFO, logger="cideldill_client.serialization"):
        data = _safe_dumps(UnpicklableContainer())

    assert data
    records = [
        record
        for record in caplog.records
        if record.message == "Serialization degraded to placeholder"
    ]
    assert records
    assert getattr(records[0], "object_module") == UnpicklableContainer.__module__
