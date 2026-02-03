"""Async with_debug usage example."""

import asyncio

from cideldill_client import with_debug


class AsyncCalculator:
    async def add(self, x: int, y: int) -> int:
        await asyncio.sleep(0.1)
        return x + y


async def main() -> None:
    with_debug("ON")
    calculator = with_debug(AsyncCalculator())
    result = await calculator.add(3, 4)
    print(f"3 + 4 = {result}")


if __name__ == "__main__":
    asyncio.run(main())
