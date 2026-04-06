"""Tests for with_retry decorator.

Why these tests matter:
- Every notifier depends on retry logic
- Broken retry = one network blip drops all notifications silently
- Wrong backoff = hammering a down service
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.utils.retry import with_retry


class TestRetry:
    async def test_succeeds_without_retry(self):
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    async def test_retries_then_succeeds(self):
        call_count = 0

        @with_retry(max_retries=3, base_delay=0.01)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("temporary failure")
            return "recovered"

        result = await fail_then_succeed()
        assert result == "recovered"
        assert call_count == 3

    async def test_exhausts_retries_raises(self):
        @with_retry(max_retries=2, base_delay=0.01)
        async def always_fail():
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            await always_fail()

    async def test_backoff_increases(self):
        """Verify sleep is called with increasing delays."""
        call_count = 0

        @with_retry(max_retries=3, base_delay=1.0, max_delay=60.0)
        async def fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("fail")

        with patch("src.utils.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(RuntimeError):
                await fail()

            delays = [call.args[0] for call in mock_sleep.call_args_list]
            assert len(delays) == 3
            # Each delay should be larger than the previous (exponential + jitter)
            # base_delay * 2^0 = 1, base_delay * 2^1 = 2, base_delay * 2^2 = 4
            # With jitter up to 50%, ranges: [1, 1.5], [2, 3], [4, 6]
            assert 1.0 <= delays[0] <= 1.5
            assert 2.0 <= delays[1] <= 3.0
            assert 4.0 <= delays[2] <= 6.0
