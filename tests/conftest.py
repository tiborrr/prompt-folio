import os
import pytest
from httpx import AsyncClient, ASGITransport

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
from app.main import app

from sqlalchemy import create_engine
from sqlmodel import SQLModel


@pytest.fixture(autouse=True)
def setup_db():
    # In-memory databases with shared cache are shared across the process.
    # We can connect using the sync engine to setup and teardown.
    sync_engine = create_engine(
        "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"
    )
    SQLModel.metadata.drop_all(sync_engine)
    SQLModel.metadata.create_all(sync_engine)
    yield
    SQLModel.metadata.drop_all(sync_engine)


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
