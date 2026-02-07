import hashlib

from cideldill_client.serialization import Serializer as ClientSerializer
from cideldill_client.serialization import compute_cid as client_compute_cid
from cideldill_client.serialization import serialize as client_serialize
from cideldill_server.cid_store import CIDStore
from cideldill_server.exceptions import DebugCIDMismatchError
from cideldill_server.serialization import Serializer as ServerSerializer
from cideldill_server.serialization import compute_cid as server_compute_cid
from cideldill_server.serialization import serialize as server_serialize


def test_client_compute_cid_uses_sha512():
    payload = {"a": 1, "b": [2, 3]}
    expected = hashlib.sha512(client_serialize(payload)).hexdigest()
    assert client_compute_cid(payload) == expected


def test_server_compute_cid_uses_sha512():
    payload = {"a": 1, "b": [2, 3]}
    expected = hashlib.sha512(server_serialize(payload)).hexdigest()
    assert server_compute_cid(payload) == expected


def test_client_verify_cid_uses_sha512():
    payload = {"hello": "world"}
    data_base64 = ClientSerializer().force_serialize_with_data(payload).data_base64
    assert data_base64 is not None
    expected = hashlib.sha512(client_serialize(payload)).hexdigest()
    assert ClientSerializer.verify_cid(data_base64, expected) is True


def test_server_verify_cid_uses_sha512():
    payload = {"hello": "world"}
    data_base64 = ServerSerializer().force_serialize_with_data(payload).data_base64
    assert data_base64 is not None
    expected = hashlib.sha512(server_serialize(payload)).hexdigest()
    assert ServerSerializer.verify_cid(data_base64, expected) is True


def test_cid_store_validates_with_sha512():
    store = CIDStore(":memory:")
    data = b"payload"
    good_cid = hashlib.sha512(data).hexdigest()
    store.store(good_cid, data)

    bad_cid = "0" * 128
    try:
        store.store(bad_cid, data)
        assert False, "Expected DebugCIDMismatchError"
    except DebugCIDMismatchError:
        assert True
