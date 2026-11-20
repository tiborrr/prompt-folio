import os

import pytest
from httpx import ASGITransport, AsyncClient

# Set environment variables for testing before importing the app
os.environ["ENVIRONMENT"] = "TEST"
os.environ["ADMIN_PASSWORD"] = "test_secure_password"
os.environ["MISTRAL_API_KEY"] = "fake_test_key"
os.environ["RECAPTCHA_SERVER_SIDE_KEY"] = "test_recaptcha"
os.environ["RECAPTCHA_CLIENT_SIDE_KEY"] = "test_recaptcha"
os.environ["SQLITE_URL"] = (
    "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared&uri=true"
)

# Now import the app
from sqlalchemy import create_engine
from sqlalchemy.pool import SingletonThreadPool
from sqlmodel import SQLModel

from app.dependencies import limiter
from app.main import app


@pytest.fixture(autouse=True)
def setup_db():
    # In-memory databases with shared cache are shared across the process.
    # We can connect using the sync engine to setup and teardown.
    sync_engine = create_engine(
        "sqlite:///file:testdb?mode=memory&cache=shared&uri=true",
        poolclass=SingletonThreadPool,
    )
    SQLModel.metadata.drop_all(sync_engine)
    SQLModel.metadata.create_all(sync_engine)
    # Rate limits are per process; reset them so tests do not depend on order
    limiter.reset()
    yield
    SQLModel.metadata.drop_all(sync_engine)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
