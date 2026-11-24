import asyncio

import pytest

from worker.time_limit import ClaudeTimeoutError, run_with_time_limit


def test_run_with_time_limit_returns_result():
    async def quick():
        return "sid", "done"

    assert run_with_time_limit(quick(), 5) == ("sid", "done")


def test_run_with_time_limit_cancels_and_raises_on_timeout():
    cancelled = []

    async def hang():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    with pytest.raises(ClaudeTimeoutError, match="0.01秒"):
        run_with_time_limit(hang(), 0.01)
    assert cancelled == [True]
