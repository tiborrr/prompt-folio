from datetime import datetime, timedelta, timezone
from typing import override

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func
from sqlmodel import Session, select

from app.config import Settings
from app.dependencies import get_recaptcha_service, hash_session_token
from app.main import app
from app.models import AdminSession, ChatMessage, ChatSession
from app.routers.manage import safe_next_url
from app.services import ContextStore
from app.utils import markdown_filter

TEST_DB = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"
ADMIN_PASSWORD = "test_secure_password"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _login(client: AsyncClient) -> str:
    response = await client.post("/manage/login", data={"password": ADMIN_PASSWORD})
    assert response.status_code == 204
    token = response.cookies.get("admin_session")
    assert token
    return token


# --- XSS -------------------------------------------------------------------


def test_markdown_escapes_raw_html():
    html = markdown_filter("hi <img src=x onerror=alert(1)> **bold**")
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<strong>bold</strong>" in html


def test_markdown_drops_javascript_links():
    assert 'href="javascript:' not in markdown_filter("[x](javascript:alert(1))")


@pytest.mark.asyncio
async def test_admin_chat_view_escapes_visitor_html():
    with Session(create_engine(TEST_DB)) as db:
        db.add(ChatSession(id="11111111-1111-4111-8111-111111111111"))
        db.add(
            ChatMessage(
                session_id="11111111-1111-4111-8111-111111111111",
                role="user",
                content="<script>steal()</script>",
            )
        )
        db.commit()

    async with _client() as client:
        _ = await _login(client)
        response = await client.get("/manage/chat/11111111-1111-4111-8111-111111111111")
    assert response.status_code == 200
    assert "<script>steal()</script>" not in response.text
    assert "&lt;script&gt;steal()&lt;/script&gt;" in response.text


# --- Admin sessions --------------------------------------------------------


@pytest.mark.asyncio
async def test_login_stores_only_a_hash_of_a_random_token():
    async with _client() as client:
        token = await _login(client)

    with Session(create_engine(TEST_DB)) as db:
        stored = db.exec(select(AdminSession.token)).all()
    assert stored == [hash_session_token(token)]
    assert ADMIN_PASSWORD not in stored
    assert token != ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_password_is_not_a_valid_session_cookie():
    async with _client() as client:
        _ = await _login(client)
        client.cookies.clear()
        client.cookies.set("admin_session", ADMIN_PASSWORD)
        response = await client.get("/manage")
    assert "Admin Login" in response.text


@pytest.mark.asyncio
async def test_expired_admin_session_is_rejected():
    token = "expired-token"
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
    with Session(create_engine(TEST_DB)) as db:
        db.add(AdminSession(token=hash_session_token(token), created_at=old))
        db.commit()

    async with _client() as client:
        client.cookies.set("admin_session", token)
        response = await client.get("/manage")
    assert "Admin Login" in response.text


@pytest.mark.asyncio
async def test_logout_invalidates_the_session():
    async with _client() as client:
        token = await _login(client)
        _ = await client.post("/manage/logout")
        client.cookies.set("admin_session", token)
        response = await client.get("/manage")
    assert "Admin Login" in response.text


@pytest.mark.parametrize(
    ("next_url", "expected"),
    [
        (None, "/manage"),
        ("/manage/chat/abc", "/manage/chat/abc"),
        ("https://evil.example", "/manage"),
        ("//evil.example", "/manage"),
        ("/\\evil.example", "/manage"),
    ],
)
def test_safe_next_url(next_url: str | None, expected: str):
    assert safe_next_url(next_url) == expected


# --- Configuration ---------------------------------------------------------


@pytest.mark.parametrize("password", ["", "secret", "change_this_to_a_secure_password"])
def test_production_refuses_default_admin_password(password: str):
    with pytest.raises(ValidationError):
        _ = Settings(environment="PROD", admin_password=password)


def test_production_accepts_a_real_admin_password():
    assert Settings(environment="PROD", admin_password="a-real-password").admin_password


class _KeysStore(ContextStore):
    def __init__(self, server_key: str):
        super().__init__()
        self.server_key = server_key

    @override
    async def get_active_integrations(self, db, config) -> dict[str, str]:  # pyright: ignore[reportMissingParameterType, reportUnknownParameterType]
        return {
            "mistral_api_key": "",
            "recaptcha_client_side_key": "",
            "recaptcha_server_side_key": self.server_key,
            "ntfy_topic": "",
        }


@pytest.mark.asyncio
async def test_recaptcha_is_disabled_without_server_key():
    config = Settings(environment="PROD", admin_password="a-real-password")
    service = await get_recaptcha_service(None, _KeysStore(""), config)  # pyright: ignore[reportArgumentType]
    assert await service.verify("")


@pytest.mark.asyncio
async def test_recaptcha_is_enforced_with_server_key():
    config = Settings(environment="PROD", admin_password="a-real-password")
    service = await get_recaptcha_service(None, _KeysStore("key"), config)  # pyright: ignore[reportArgumentType]
    assert not service.is_dev


# --- Input limits ----------------------------------------------------------


def _session_count() -> int:
    with Session(create_engine(TEST_DB)) as db:
        return db.exec(select(func.count()).select_from(ChatSession)).one()


@pytest.mark.asyncio
async def test_opening_the_page_does_not_store_a_session():
    async with _client() as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.cookies.get("session_id")
    assert _session_count() == 0


@pytest.mark.asyncio
async def test_too_long_chat_message_is_rejected():
    async with _client() as client:
        _ = await client.get("/")
        response = await client.post("/chat", data={"message": "x" * 4001})
    assert response.status_code == 400
    assert _session_count() == 0


@pytest.mark.asyncio
async def test_svg_avatar_is_rejected():
    async with _client() as client:
        _ = await _login(client)
        response = await client.post(
            "/manage/avatar",
            files={"file": ("a.svg", b"<svg onload=alert(1)>", "image/svg+xml")},
        )
    assert response.status_code == 400
