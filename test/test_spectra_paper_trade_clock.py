import asyncio
import math

import pytest
from hummingbot.core.time_iterator import TimeIterator

from services.unified_connector_service import UnifiedConnectorService


@pytest.mark.asyncio
async def test_managed_paper_trade_clock_ticks_and_stops_cleanly():
    service = object.__new__(UnifiedConnectorService)
    service._paper_trade_clock = None
    service._paper_trade_clock_task = None
    service._paper_trade_clock_lock = asyncio.Lock()

    iterator = TimeIterator()
    await service._start_paper_trade_clock(iterator)
    # TimeIterator starts at NaN; wait for the managed realtime clock's
    # first tick before comparing subsequent progress.
    for _ in range(50):
        first_tick = iterator.current_timestamp
        if math.isfinite(first_tick):
            break
        await asyncio.sleep(0.1)
    assert math.isfinite(first_tick), "paper clock never produced its first tick"

    await asyncio.sleep(2.2)

    assert iterator.current_timestamp > first_tick
    assert iterator in service._paper_trade_clock.child_iterators

    await service._stop_paper_trade_clock(iterator)

    assert service._paper_trade_clock is None
    assert service._paper_trade_clock_task is None
