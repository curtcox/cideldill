import logging
import warnings

import pytest

from cideldill_client.custom_picklers import UnpicklablePlaceholder
from cideldill_client.exceptions import DebugSerializationError
from cideldill_client.serialization import (
    _safe_dumps,
    deserialize,
    serialize,
    set_verbose_serialization_warnings,
)
import cideldill_client.serialization_common as serialization_common


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


class MixedStateContainer:
    def __init__(self):
        self.payload = {
            "ok": {"nested": [1, 2, 3]},
            "bad": ExplodingState(),
            "items": [10, ExplodingState(), {"deep": "value"}],
        }

    def __getstate__(self):
        raise TypeError("mixed container boom")


def test_serialize_degrades_to_placeholder_with_attribute_snapshot():
    data = serialize(UnpicklableContainer())
    restored = deserialize(data)

    assert isinstance(restored, UnpicklablePlaceholder)
    assert restored.type_name == "UnpicklableContainer"
    assert restored.object_name == "UnpicklableContainer"
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


def test_serialize_captures_mixed_serializable_parts_inside_nested_containers():
    data = serialize(MixedStateContainer())
    restored = deserialize(data)

    assert isinstance(restored, UnpicklablePlaceholder)
    payload = restored.attributes["payload"]
    assert isinstance(payload, UnpicklablePlaceholder)
    assert payload.type_name == "dict"

    assert payload.attributes["ok"] == {"nested": [1, 2, 3]}

    bad_value = payload.attributes["bad"]
    assert isinstance(bad_value, UnpicklablePlaceholder)
    assert "TypeError" in bad_value.pickle_error

    items_value = payload.attributes["items"]
    assert isinstance(items_value, UnpicklablePlaceholder)
    assert items_value.type_name == "list"
    assert items_value.attributes["[0]"] == 10
    assert items_value.attributes["[2]"] == {"deep": "value"}
    assert isinstance(items_value.attributes["[1]"], UnpicklablePlaceholder)


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
    assert any(
        getattr(record, "object_module") == UnpicklableContainer.__module__
        for record in records
    )
    assert any(
        getattr(record, "object_name") == "UnpicklableContainer"
        for record in records
    )


def test_serialize_suppresses_pickling_warnings_by_default(monkeypatch):
    original_dumps = serialization_common.dill.dumps

    def noisy_dumps(obj, *args, **kwargs):  # type: ignore[no-untyped-def]
        warnings.warn("noisy", category=serialization_common.dill.PicklingWarning)
        return original_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(serialization_common.dill, "dumps", noisy_dumps)

    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        serialize({"ok": True})

    assert not captured


def test_serialize_logs_pickling_warnings_when_verbose(monkeypatch):
    original_dumps = serialization_common.dill.dumps

    def noisy_dumps(obj, *args, **kwargs):  # type: ignore[no-untyped-def]
        warnings.warn("noisy", category=serialization_common.dill.PicklingWarning)
        return original_dumps(obj, *args, **kwargs)

    monkeypatch.setattr(serialization_common.dill, "dumps", noisy_dumps)

    set_verbose_serialization_warnings(True)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", category=serialization_common.dill.PicklingWarning)
            serialize({"ok": True})
    finally:
        set_verbose_serialization_warnings(False)

    assert any(
        isinstance(w.message, serialization_common.dill.PicklingWarning)
        for w in captured
    )
