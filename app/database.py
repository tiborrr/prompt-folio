from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import os

from functools import cache


@cache
def get_engine(db_url: str):
    if db_url.startswith("sqlite+aiosqlite:///"):
        # Ensure the directory exists
        path = db_url.replace("sqlite+aiosqlite:///", "")
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    engine = create_async_engine(db_url, echo=False, future=True)
    return engine


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    from app.dependencies import get_settings

    settings = get_settings()
    engine = get_engine(settings.sqlite_url)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session
