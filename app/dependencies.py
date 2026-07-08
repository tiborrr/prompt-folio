from functools import cache
from typing import Annotated
from fastapi import Depends, Form, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.config import settings, Settings
from app.constants import RATE_LIMIT_GLOBAL
from app.database import get_engine
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.models import AdminSession
from app.services import (
    MistralService,
    RecaptchaService,
    ContextStore,
    SessionStore,
    default_session_store,
    NotificationService,
)

limiter = Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_GLOBAL])


@cache
def get_settings() -> Settings:
    return settings


def get_db_session_factory(
    config: Annotated[Settings, Depends(get_settings)]
) -> async_sessionmaker[AsyncSession]:
    engine = get_engine(config.sqlite_url)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session(
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_db_session_factory)]
) -> AsyncGenerator[AsyncSession, None]:
    async with factory() as session:
        yield session


def get_admin_session_cookie(
    request: Request,
    config: Annotated[Settings, Depends(get_settings)],
) -> str | None:
    prefix = config.cookie_prefix
    return request.cookies.get(f"{prefix}admin_session")


async def is_admin_session_active(db: AsyncSession, token: str | None) -> bool:
    if not token:
        return False
    result = await db.execute(select(AdminSession).where(AdminSession.token == token))
    return result.scalar_one_or_none() is not None


async def create_admin_session(db: AsyncSession, token: str) -> None:
    existing = await db.execute(select(AdminSession).where(AdminSession.token == token))
    if existing.scalar_one_or_none() is None:
        db.add(AdminSession(token=token))
        await db.commit()


async def delete_admin_session(db: AsyncSession, token: str | None) -> None:
    if not token:
        return
    result = await db.execute(select(AdminSession).where(AdminSession.token == token))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        await db.delete(session_obj)
        await db.commit()

async def get_mistral_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    config: Annotated[Settings, Depends(get_settings)],
) -> MistralService:
    integrations = await context_store.get_active_integrations(db, config)
    return MistralService(api_key=integrations["mistral_api_key"])


async def get_recaptcha_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    config: Annotated[Settings, Depends(get_settings)],
) -> RecaptchaService:
    is_dev = config.environment in ["DEV", "TEST"]
    integrations = await context_store.get_active_integrations(db, config)
    return RecaptchaService(server_key=integrations["recaptcha_server_side_key"], is_dev=is_dev)


async def get_notification_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    config: Annotated[Settings, Depends(get_settings)],
) -> NotificationService:
    integrations = await context_store.get_active_integrations(db, config)
    return NotificationService(topic=integrations["ntfy_topic"])


@cache
def get_context_store() -> ContextStore:
    return ContextStore()


def get_session_store() -> SessionStore:
    return default_session_store


async def require_admin(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    config: Annotated[Settings, Depends(get_settings)],
) -> str:
    admin_session = get_admin_session_cookie(request, config)
    if not admin_session or not await is_admin_session_active(db, admin_session):
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
