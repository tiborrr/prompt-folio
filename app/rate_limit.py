"""Per-client rate limiting for FastAPI routes, built on the ``limits`` library.

Usage mirrors slowapi, which this replaces::

    @router.post("/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...): ...

The decorated endpoint must take a ``request: Request`` parameter. The client
key is the connection's host, which uvicorn already rewrites from
X-Forwarded-For for trusted proxies (FORWARDED_ALLOW_IPS).
"""

import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar, cast

from fastapi import Request
from limits import RateLimitItem, parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter

P = ParamSpec("P")
R = TypeVar("R")


class RateLimitExceeded(Exception):
    """Raised when a client goes over a route's limit; handled as HTTP 429."""

    def __init__(self, limit: RateLimitItem) -> None:
        super().__init__(f"Rate limit exceeded: {limit}")
        self.limit: RateLimitItem = limit


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class Limiter:
    def __init__(self, key_func: Callable[[Request], str] = client_address) -> None:
        self._key_func: Callable[[Request], str] = key_func
        self._strategy: MovingWindowRateLimiter = MovingWindowRateLimiter(
            MemoryStorage()
        )

    def limit(
        self, limit_value: str
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        item = parse(limit_value)

        def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            # One bucket per route, so limits on different routes do not add up
            scope = f"{func.__module__}.{func.__qualname__}"

            @functools.wraps(func)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if not isinstance(kwargs.get("request"), Request):
                    raise TypeError(
                        f"{scope} needs a 'request: Request' parameter to be rate limited"
                    )
                key = self._key_func(cast(Request, kwargs["request"]))
                if not await self._strategy.hit(item, scope, key):
                    raise RateLimitExceeded(item)
                return await func(*args, **kwargs)

            return wrapper

        return decorator

    def reset(self) -> None:
        """Forget all hits (used by the tests)."""
        self._strategy = MovingWindowRateLimiter(MemoryStorage())
