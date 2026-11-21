import os
from functools import cache

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool


@cache
def get_engine(db_url: str) -> AsyncEngine:
    if db_url.startswith("sqlite+aiosqlite:///"):
        # Ensure the directory exists
        path = db_url.replace("sqlite+aiosqlite:///", "")
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    if "mode=memory" in db_url:
        # A shared in-memory database (used by the tests) lives as long as one
        # connection does, so keep a single connection open.
        return create_async_engine(db_url, poolclass=StaticPool)
    return create_async_engine(db_url)
