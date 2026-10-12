"""Token-bucket rate limiter. EIA suspends keys that exceed its throttles, so we stay well under."""

import threading
import time
from collections.abc import Callable


class TokenBucket:
    def __init__(
        self,
        rate_per_second: float,
        capacity: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        self._rate = rate_per_second
        self._capacity = capacity
        self._tokens = capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until one token is available, then take it."""
        with self._lock:
            while True:
                now = self._clock()
                self._tokens = min(
                    self._capacity, self._tokens + (now - self._updated) * self._rate
                )
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                self._sleep((1 - self._tokens) / self._rate)
