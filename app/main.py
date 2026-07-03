from app.schemas import StatusContext
import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded
import typing
from typing import Annotated, override
import collections.abc
from starlette.responses import Response as StarletteResponse

from app.routers import chat, manage
from app.dependencies import get_context_store, limiter
from app.utils import render_template
from app.services import ContextStore
from app.database import get_engine, get_db_session
from sqlmodel import SQLModel, select
from app.dependencies import get_settings
from app.constants import SECURITY_HEADERS
from app.config import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def migrate_files_to_db(db: AsyncSession) -> None:
    """One-time migration: read old file-based settings into the database."""
    from app.models import SiteSettings

    result = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
    if result.scalar_one_or_none():
        return  # Already has settings, skip migration

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    private_dir = os.path.join(root_dir, "private")

    site = SiteSettings(id=1)

    # Owner name
    owner_name_path = os.path.join(private_dir, "owner_name.txt")
    if os.path.exists(owner_name_path):
        with open(owner_name_path, "r", encoding="utf-8") as f:
            val = f.read().strip()
            if val:
                site.owner_name = val

    # Owner pronouns
    owner_pronouns_path = os.path.join(private_dir, "owner_pronouns.txt")
    if os.path.exists(owner_pronouns_path):
        with open(owner_pronouns_path, "r", encoding="utf-8") as f:
            val = f.read().strip()
            if val:
                site.owner_pronouns = val

    # Context
    context_path = os.path.join(private_dir, "context.txt")
    if os.path.exists(context_path):
        with open(context_path, "r", encoding="utf-8") as f:
            site.context = f.read()

    # Meeting URL
    meeting_url_path = os.path.join(private_dir, "meeting_url.txt")
    if os.path.exists(meeting_url_path):
        with open(meeting_url_path, "r", encoding="utf-8") as f:
            site.meeting_url = f.read().strip()

    # Colors
    colors_path = os.path.join(private_dir, "colors.json")
    if os.path.exists(colors_path):
        try:
            with open(colors_path, "r", encoding="utf-8") as f:
                colors = json.load(f)
            site.color_shadow_grey = colors.get("shadow_grey", site.color_shadow_grey)
            site.color_sweet_salmon = colors.get("sweet_salmon", site.color_sweet_salmon)
            site.color_khaki_beige = colors.get("khaki_beige", site.color_khaki_beige)
            site.color_muted_teal = colors.get("muted_teal", site.color_muted_teal)
            site.color_seaweed = colors.get("seaweed", site.color_seaweed)
        except Exception:
            pass

    # Avatar
    avatar_path = os.path.join(private_dir, "avatar")
    if os.path.exists(avatar_path):
        with open(avatar_path, "rb") as f:
            site.avatar = f.read()
            site.avatar_content_type = "image/png"

    db.add(site)
    await db.commit()
    print("[MIGRATION] File-based settings migrated to database successfully.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize DB
    app_settings = get_settings()
    engine = get_engine(app_settings.sqlite_url)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Run file-to-db migration
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        await migrate_files_to_db(db)

    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    @override
    async def dispatch(
        self,
        request: Request,
        call_next: typing.Callable[[Request], collections.abc.Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


app.add_middleware(SecurityHeadersMiddleware)

base_dir = os.path.dirname(os.path.abspath(__file__))
app.mount(
    "/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static"
)


async def _get_db() -> AsyncSession:
    """Create a standalone db session for use outside DI (e.g. exception handlers)."""
    app_settings = get_settings()
    engine = get_engine(app_settings.sqlite_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return session_factory()


@app.get("/avatar")
async def get_avatar(
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    avatar_data = await context_store.get_avatar_bytes(db)
    if avatar_data:
        content, content_type = avatar_data
        return Response(content=content, media_type=content_type)
    raise StarletteHTTPException(status_code=404, detail="Avatar not found")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, _: RateLimitExceeded):
    is_htmx = request.headers.get("hx-request") == "true"
    message = "Whoa there! You're going a bit too fast. Please wait a moment before trying again."

    if is_htmx:
        async with await _get_db() as db:
            response = await render_template(
                request,
                "error_message.html",
                get_context_store(),
                db,
                StatusContext(message=message),
            )
        response.status_code = 429
        return response

    return HTMLResponse(
        content=f"<h1>429 Too Many Requests</h1><p>{message}</p>", status_code=429
    )


@app.exception_handler(StarletteHTTPException)
async def htmx_exception_handler(request: Request, exc: StarletteHTTPException):
    is_htmx = request.headers.get("hx-request") == "true"

    # If the request comes from HTMX, we return HTML template snippet instead of JSON.
    if is_htmx:
        async with await _get_db() as db:
            response = await render_template(
                request,
                "error_message.html",
                get_context_store(),
                db,
                StatusContext(message=exc.detail),
            )
        response.status_code = exc.status_code
        return response

    # If it's a normal browser request and it hits a 401, redirect to login page.
    if exc.status_code == 401:
        return RedirectResponse(url="/manage")

    # Default behavior for non-HTMX
    return HTMLResponse(content=exc.detail, status_code=exc.status_code)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    import logging

    logging.error(f"Global exception caught: {exc}\n{traceback.format_exc()}")

    is_htmx = request.headers.get("hx-request") == "true"
    if is_htmx:
        async with await _get_db() as db:
            response = await render_template(
                request,
                "error_message.html",
                get_context_store(),
                db,
                StatusContext(
                    message="Internal Server Error. The admin has been notified."
                ),
            )
        response.status_code = 500
        return response

    with open(os.path.join(base_dir, "templates", "500.html"), "r") as f:
        html = f.read()
    return HTMLResponse(content=html, status_code=500)


app.include_router(chat.router)
app.include_router(manage.router)
