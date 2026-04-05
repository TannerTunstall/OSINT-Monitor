import asyncio
import functools
import logging
import random

logger = logging.getLogger(__name__)


def with_retry(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """Decorator for async functions with exponential backoff + jitter."""

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.5)
                    wait = delay + jitter
                    logger.warning(
                        "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                        func.__name__, attempt + 1, max_retries + 1, exc, wait,
                    )
                    await asyncio.sleep(wait)
            raise last_exc

        return wrapper

    return decorator
