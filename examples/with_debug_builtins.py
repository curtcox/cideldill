"""Built-in type wrapping example."""

from cideldill import with_debug


def main() -> None:
    with_debug("ON")

    numbers = with_debug([1, 2, 3])
    numbers.append(4)
    print(f"Numbers: {numbers}")

    mapping = with_debug({"a": 1})
    mapping["b"] = 2
    print(f"Mapping keys: {list(mapping.keys())}")


if __name__ == "__main__":
    main()
