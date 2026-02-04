"""Example demonstrating automatic handling of unpicklable objects.

This example shows how CID el Dill automatically handles objects that
can't be pickled using standard mechanisms.
"""

from cideldill_client import with_debug


class MetaclassRegistry(type):
    """Metaclass that maintains a registry (can cause pickle issues)."""

    _instances = {}

    def __call__(cls, *args, **kwargs):
        key = (cls.__name__, args)
        if key not in cls._instances:
            cls._instances[key] = super().__call__(*args, **kwargs)
        return cls._instances[key]


class ConfigSchema(metaclass=MetaclassRegistry):
    """Configuration schema with singleton-like behavior."""

    def __init__(self, name: str):
        self.name = name
        self.rules = []

    def __reduce_ex__(self, protocol):
        raise TypeError("Not picklable by default")

    def add_rule(self, rule: str) -> None:
        self.rules.append(rule)

    def validate(self, data: dict) -> bool:
        print(f"Validating {data} against schema '{self.name}'")
        return True


def main() -> None:
    print("=" * 60)
    print("Unpicklable Objects Example")
    print("=" * 60)
    print()

    with_debug("ON")

    schema = ConfigSchema("user_schema")
    schema.add_rule("required: username")
    schema.add_rule("required: email")

    print("Wrapping unpicklable object...")
    wrapped_schema = with_debug(schema)
    print(f"Successfully wrapped: {type(schema).__name__}")
    print(f"  CID: {wrapped_schema.cid[:16]}...")
    print()

    print("Using wrapped object:")
    wrapped_schema.add_rule("optional: phone")
    result = wrapped_schema.validate({"username": "alice", "email": "alice@example.com"})
    print(f"  Validation result: {result}")
    print()

    schema2 = ConfigSchema("user_schema")
    wrapped_schema2 = with_debug(schema2)

    print(f"Same instance? {schema is schema2}")
    print(f"Same CID? {wrapped_schema.cid == wrapped_schema2.cid}")
    print()

    print("=" * 60)
    print("All operations completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
