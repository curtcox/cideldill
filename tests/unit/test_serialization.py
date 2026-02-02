import base64

import dill

from cideldill.cid_store import CIDStore
from cideldill.decomposition import ObjectDecomposer, reassemble
from cideldill.serialization import CIDCache, CIDRef, Serializer, compute_cid, process_request_object


def test_compute_cid_returns_128_char_hex():
    cid = compute_cid({"a": 1})
    assert len(cid) == 128
    int(cid, 16)


def test_cidcache_mark_and_is_sent():
    cache = CIDCache()
    cid = "a" * 128
    assert cache.is_sent(cid) is False
    cache.mark_sent(cid)
    assert cache.is_sent(cid) is True


def test_serializer_cached_object_excludes_data():
    serializer = Serializer()
    result = serializer.serialize({"hello": "world"})
    assert result.data_base64 is not None

    cached = serializer.serialize({"hello": "world"})
    assert cached.data_base64 is None
    assert cached.components == {}


def test_serializer_decomposes_large_list():
    serializer = Serializer()
    serializer.MIN_DECOMPOSE_SIZE = 10
    large_value = "x" * 50
    payload = [large_value, large_value]

    result = serializer.serialize(payload)

    assert isinstance(dill.loads(result.data), list)
    assert result.components
    assert all(isinstance(value, CIDRef) for value in dill.loads(result.data))


def test_process_request_object_roundtrip():
    serializer = Serializer()
    serializer.MIN_DECOMPOSE_SIZE = 10
    payload = {"items": ["y" * 50, "z" * 50]}

    request = serializer.to_json_dict(payload)
    store = CIDStore()
    resolved = process_request_object(request, store)

    assert resolved == payload


def test_object_decomposer_reassemble():
    decomposer = ObjectDecomposer()
    decomposer.MIN_DECOMPOSE_SIZE = 10
    payload = {"items": ["a" * 50, "b" * 50]}

    decomposed = decomposer.decompose(payload)
    store = CIDStore()

    def _store_component(component):
        data = base64.b64decode(component.shell_data)
        store.store(component.cid, data)
        for nested in component.components.values():
            _store_component(nested)

    _store_component(decomposed)

    result = reassemble(decomposed, store)
    assert result == payload
