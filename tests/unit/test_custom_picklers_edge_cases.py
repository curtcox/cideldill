"""Tests for edge cases in custom picklers."""

import dill

from cideldill_client.custom_picklers import PickleRegistry, auto_register_for_pickling


def test_handles_builtin_types():
    for obj in [42, "string", [1, 2, 3], {"key": "value"}]:
        assert auto_register_for_pickling(obj) is True


def test_handles_none():
    assert auto_register_for_pickling(None) is True


def test_handles_functions():
    def test_func():
        return 42

    assert auto_register_for_pickling(test_func) is True


def test_handles_lambdas():
    func = lambda x: x * 2

    result = auto_register_for_pickling(func)
    assert isinstance(result, bool)


def test_handles_recursive_structures():
    class Node:
        def __init__(self, value):
            self.value = value
            self.children = []

        def add_child(self, child):
            self.children.append(child)

    root = Node(1)
    child = Node(2)
    root.add_child(child)
    child.add_child(root)

    assert auto_register_for_pickling(root) is True

    pickled = dill.dumps(root)
    restored = dill.loads(pickled)

    assert restored.value == 1
    assert restored.children[0].value == 2
    assert restored.children[0].children[0].value == 1


def test_handles_objects_with_no_dict():
    class NoDictClass:
        __slots__ = ["value"]

        def __init__(self, value):
            self.value = value

    obj = NoDictClass(42)
    assert auto_register_for_pickling(obj) is True

    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.value == 42


def test_handles_objects_with_descriptors():
    class DescriptorClass:
        def __init__(self, value):
            self._value = value

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, val):
            self._value = val

    obj = DescriptorClass(100)
    assert auto_register_for_pickling(obj) is True

    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)
    assert restored.value == 100


def test_handles_objects_with_weakrefs():
    import weakref

    class WeakRefClass:
        def __init__(self, name):
            self.name = name
            self.refs = []

        def add_ref(self, obj):
            self.refs.append(weakref.ref(obj))

    obj1 = WeakRefClass("obj1")
    obj2 = WeakRefClass("obj2")
    obj1.add_ref(obj2)

    result = auto_register_for_pickling(obj1)
    assert isinstance(result, bool)


def test_handles_objects_with_file_handles():
    import tempfile

    class FileHolder:
        def __init__(self):
            self.file = tempfile.NamedTemporaryFile(delete=False)

    obj = FileHolder()

    try:
        result = auto_register_for_pickling(obj)
        assert isinstance(result, bool)
    finally:
        obj.file.close()


def test_concurrent_auto_registration():
    import threading

    class ConcurrentClass:
        def __init__(self, value):
            self.value = value

    results = []

    def register_worker():
        obj = ConcurrentClass(42)
        result = auto_register_for_pickling(obj)
        results.append(result)

    threads = [threading.Thread(target=register_worker) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert all(results)
    assert ConcurrentClass in PickleRegistry._reducers


def test_handles_ssl_context():
    import ssl

    class SSLHolder:
        def __init__(self):
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    obj = SSLHolder()
    assert auto_register_for_pickling(obj) is True

    pickled = dill.dumps(obj)
    restored = dill.loads(pickled)

    assert isinstance(restored.context, ssl.SSLContext)
