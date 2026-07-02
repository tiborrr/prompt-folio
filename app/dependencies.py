import os
from functools import cache
from typing import Annotated
from fastapi import Depends, Cookie, Form, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings, Settings
from app.constants import RATE_LIMIT_GLOBAL
from app.services import (
    MistralService,
    RecaptchaService,
    ContextStore,
    SessionStore,
    default_session_store,
    NotificationService,
)

COOKIE_PREFIX = "" if settings.environment == "DEV" else "__Secure-"

ACTIVE_ADMIN_SESSIONS: set[str] = set()

limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_GLOBAL])


@cache
def get_settings() -> Settings:
    return settings


def get_mistral_service(
    config: Annotated[Settings, Depends(get_settings)],
) -> MistralService:
    return MistralService(api_key=config.mistral_api_key)


def get_recaptcha_service(
    config: Annotated[Settings, Depends(get_settings)],
) -> RecaptchaService:
    is_dev = config.environment in ["DEV", "TEST"]
    return RecaptchaService(server_key=config.recaptcha_server_side_key, is_dev=is_dev)


def get_notification_service(
    config: Annotated[Settings, Depends(get_settings)],
) -> NotificationService:
    return NotificationService(topic=config.ntfy_topic)


@cache
def get_context_store() -> ContextStore:
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    private_dir = os.path.join(root_dir, "private")
    os.makedirs(private_dir, exist_ok=True)
    return ContextStore(base_dir=private_dir)


def get_session_store() -> SessionStore:
    return default_session_store


async def require_admin(
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}admin_session")
    ] = None,
) -> str:
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Invalid or expired admin session.")
    return admin_session


async def require_recaptcha(
    recaptcha_service: Annotated[RecaptchaService, Depends(get_recaptcha_service)],
    g_recaptcha_response: Annotated[str, Form(alias="g-recaptcha-response")] = "",
) -> None:
    if not await recaptcha_service.verify(g_recaptcha_response):
        raise HTTPException(
            status_code=400, detail="reCAPTCHA verification failed. Please try again."
        )
