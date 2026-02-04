"""Unit tests for CIDStore behavior."""

import hashlib

import pytest

from cideldill_server.cid_store import CIDStore
from cideldill_server.exceptions import DebugCIDMismatchError


def test_get_many_empty_returns_empty_dict() -> None:
    store = CIDStore()
    assert store.get_many([]) == {}


def test_missing_empty_returns_empty_list() -> None:
    store = CIDStore()
    assert store.missing([]) == []


def test_store_many_raises_on_mismatch() -> None:
    store = CIDStore()
    good_data = b"good"
    bad_data = b"bad"
    good_cid = hashlib.sha256(good_data).hexdigest()
    bad_cid = "0" * 64

    with pytest.raises(DebugCIDMismatchError):
        store.store_many({good_cid: good_data, bad_cid: bad_data})


def test_stats_reports_counts_and_size() -> None:
    store = CIDStore()
    data_one = b"one"
    data_two = b"two"
    cid_one = hashlib.sha256(data_one).hexdigest()
    cid_two = hashlib.sha256(data_two).hexdigest()

    store.store(cid_one, data_one)
    store.store(cid_two, data_two)

    stats = store.stats()
    assert stats["count"] == 2
    assert stats["total_size_bytes"] >= len(data_one) + len(data_two)
