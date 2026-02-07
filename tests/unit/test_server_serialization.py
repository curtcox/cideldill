from cideldill_server.serialization import CIDCache, Serializer, compute_cid, deserialize, serialize


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


def test_serialize_roundtrip():
    payload = {"items": [1, 2, 3]}
    data = serialize(payload)
    assert deserialize(data) == payload
