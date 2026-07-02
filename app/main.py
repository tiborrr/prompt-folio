import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi.errors import RateLimitExceeded
import typing
from typing import Annotated, Any, override
from starlette.responses import Response

from app.routers import chat, manage
from app.dependencies import get_context_store, limiter
from app.utils import render_template
from app.services import ContextStore
from app.database import get_engine
from sqlmodel import SQLModel
from app.dependencies import get_settings
from app.constants import SECURITY_HEADERS


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize DB
    settings = get_settings()
    engine = get_engine(settings.sqlite_url)
    if settings.environment == "TEST":
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.drop_all)
            await conn.run_sync(SQLModel.metadata.create_all)

    yield


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    @override
    async def dispatch(self, request: Request, call_next: typing.Callable[[Request], typing.Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


app.add_middleware(SecurityHeadersMiddleware)

base_dir = os.path.dirname(os.path.abspath(__file__))
app.mount(
    "/static", StaticFiles(directory=os.path.join(base_dir, "static")), name="static"
)


@app.get("/avatar")
async def get_avatar(context_store: Annotated[ContextStore, Depends(get_context_store)]):
    if context_store.has_avatar():
        return FileResponse(context_store.get_avatar_path())
    raise StarletteHTTPException(status_code=404, detail="Avatar not found")


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, _: RateLimitExceeded):
    is_htmx = request.headers.get("hx-request") == "true"
    message = "Whoa there! You're going a bit too fast. Please wait a moment before trying again."

    if is_htmx:
        response = render_template(
            request, "error_message.html", get_context_store(), {"message": message}
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
        response = render_template(
            request, "error_message.html", get_context_store(), {"message": exc.detail}
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
        response = render_template(
            request,
            "error_message.html",
            get_context_store(),
            {"message": "Internal Server Error. The admin has been notified."},
        )
        response.status_code = 500
        return response

    with open(os.path.join(base_dir, "templates", "500.html"), "r") as f:
        html = f.read()
    return HTMLResponse(content=html, status_code=500)


app.include_router(chat.router)
app.include_router(manage.router)
