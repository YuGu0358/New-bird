from __future__ import annotations

import asyncio
import time
import unittest


class AsyncTokenBucketTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_consumes_capacity_then_refills(self) -> None:
        from app.services.rate_limiter import AsyncTokenBucket, RateLimitedError

        bucket = AsyncTokenBucket(rate_per_sec=20.0, capacity=2)
        await bucket.acquire()
        await bucket.acquire()
        with self.assertRaises(RateLimitedError):
            await bucket.acquire(wait_timeout=0.0)
        await asyncio.sleep(0.08)
        await bucket.acquire(wait_timeout=0.0)

    async def test_acquire_waits_for_refill_when_timeout_allows(self) -> None:
        from app.services.rate_limiter import AsyncTokenBucket

        bucket = AsyncTokenBucket(rate_per_sec=20.0, capacity=1)
        await bucket.acquire()
        start = time.monotonic()
        await bucket.acquire(wait_timeout=1.0)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 0.04)
        self.assertLess(elapsed, 1.0)


class GuardedFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_guarded_fetch_returns_value_on_success(self) -> None:
        from app.services.rate_limiter import AsyncTokenBucket, guarded_fetch

        bucket = AsyncTokenBucket(rate_per_sec=100.0, capacity=10)
        result = await guarded_fetch(
            "test",
            limiter=bucket,
            fetch_timeout=1.0,
            acquire_timeout=1.0,
            fn=lambda x: x + 1,
            args=(41,),
        )
        self.assertEqual(result, 42)

    async def test_guarded_fetch_maps_timeout_to_upstream_timeout(self) -> None:
        from app.services.rate_limiter import (
            AsyncTokenBucket,
            UpstreamTimeoutError,
            guarded_fetch,
        )

        bucket = AsyncTokenBucket(rate_per_sec=100.0, capacity=10)

        def slow():
            time.sleep(0.2)
            return "done"

        with self.assertRaises(UpstreamTimeoutError):
            await guarded_fetch(
                "test",
                limiter=bucket,
                fetch_timeout=0.05,
                acquire_timeout=1.0,
                fn=slow,
            )


if __name__ == "__main__":
    unittest.main()
