from fastapi.testclient import TestClient
from app.main import app
from app.dependencies import (
    get_settings,
    get_mistral_service,
    get_recaptcha_service,
    get_context_store,
    get_session_store,
)
from app.config import Settings
from app.services import SessionStore, MistralService, RecaptchaService, ContextStore
from app.schemas import ChatMessageData, ThemeColors, UploadedDocument

from typing import Any, override


# Fake Services
class FakeMistralService(MistralService):
    def __init__(self):
        super().__init__("fake")

    @override
    async def ask_mistral(self, messages_history: list[ChatMessageData], tools: list[dict[str, Any]] | None = None, tool_callback: Any | None = None, max_depth: int = 3) -> str:
        return "Fake AI Response"

    @override
    async def generate_profile_from_pdfs(
        self, pdf_files: list[UploadedDocument], owner_name: str
    ) -> str:
        return "Fake Profile"


class FakeRecaptchaService(RecaptchaService):
    def __init__(self):
        super().__init__("fake", True)

    @override
    async def verify(self, token: str) -> bool:
        return True  # Always pass in tests


class FakeContextStore(ContextStore):
    def __init__(self):
        super().__init__("/fake")

    @override
    def get_context(self) -> str:
        return "Fake Context"

    @override
    def save_context(self, text: str):
        pass

    @override
    def get_colors(self) -> ThemeColors:
        return ThemeColors(
            shadow_grey="#4a4a4a",
            sweet_salmon="#fb9f89",
            khaki_beige="#e8d8c3",
            muted_teal="#678d85",
            seaweed="#2c4c3b",
        )

    @override
    def save_colors(self, colors: ThemeColors):
        pass


def get_fake_session_store():
    return SessionStore()  # isolated per test run since it's instantiated fresh


def get_fake_settings():
    return Settings(
        environment="TEST",
        admin_password="test_secure_password",
        mistral_api_key="fake",
        recaptcha_client_side_key="fake",
        recaptcha_server_side_key="fake",
    )


app.dependency_overrides[get_mistral_service] = FakeMistralService
app.dependency_overrides[get_recaptcha_service] = FakeRecaptchaService
app.dependency_overrides[get_context_store] = FakeContextStore
app.dependency_overrides[get_session_store] = get_fake_session_store
app.dependency_overrides[get_settings] = get_fake_settings

client = TestClient(app)


def test_read_main():
    response = client.get("/")
    assert response.status_code == 200


def test_manage_unauthenticated():
    response = client.get("/manage")
    assert response.status_code == 200
    assert "Admin Login" in response.text


def test_manage_login_success():
    response = client.post("/manage/login", data={"password": "test_secure_password"})
    assert response.status_code == 204
    assert "admin_session" in response.cookies
    assert response.cookies.get("admin_session") == "test_secure_password"
    assert response.headers.get("hx-redirect") == "/manage"


def test_manage_login_failure():
    response = client.post(
        "/manage/login",
        data={"password": "wrong_password"},
        headers={"hx-request": "true"},
    )
    assert response.status_code == 401
    assert "Invalid password" in response.text
    assert "admin_session" not in response.cookies


def test_manage_authenticated_get():
    response = client.get("/manage", cookies={"admin_session": "test_secure_password"})
    assert response.status_code == 200
    assert "1. AI Context Generation" in response.text
    assert "Admin Login" not in response.text


def test_manage_logout():
    response = client.post(
        "/manage/logout",
        cookies={"admin_session": "test_secure_password"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers.get("location") == "/"
    assert "admin_session" not in response.cookies
