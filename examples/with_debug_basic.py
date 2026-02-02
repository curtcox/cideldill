"""Basic with_debug usage example."""

from cideldill import with_debug


class Calculator:
    def add(self, x: int, y: int) -> int:
        return x + y


def main() -> None:
    with_debug("ON")

    calculator = with_debug(Calculator())
    result = calculator.add(1, 2)
    print(f"1 + 2 = {result}")


if __name__ == "__main__":
    main()
