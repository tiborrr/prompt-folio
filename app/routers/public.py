"""Pages and files for search engines and AI agents: the public profile as HTML
and Markdown, llms.txt, robots.txt and the sitemap."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies import get_context_store, get_db_session, get_settings, limiter
from app.public_profile import (
    llms_txt,
    load_public_profile,
    profile_document,
    robots_txt,
    sitemap_xml,
)
from app.services import ContextStore
from app.utils import render_template

router = APIRouter()

# Search engines and agents may keep these for an hour
CACHE = {"Cache-Control": "public, max-age=3600"}
MARKDOWN = "text/markdown; charset=utf-8"


@router.get("/profile", response_class=HTMLResponse)
@limiter.limit("60/minute")
async def profile_page(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    return await render_template(request, "profile.html", context_store, db)


@router.get("/profile.md")
@limiter.limit("60/minute")
async def profile_markdown_file(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _ = request  # used by the rate limiter
    profile = await load_public_profile(db, settings)
    return Response(profile_document(profile), media_type=MARKDOWN, headers=CACHE)


@router.get("/llms.txt", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def llms(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _ = request  # used by the rate limiter
    profile = await load_public_profile(db, settings)
    return PlainTextResponse(llms_txt(profile), headers=CACHE)


@router.get("/llms-full.txt", response_class=PlainTextResponse)
@limiter.limit("60/minute")
async def llms_full(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _ = request  # used by the rate limiter
    profile = await load_public_profile(db, settings)
    return PlainTextResponse(profile_document(profile), headers=CACHE)


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots(settings: Annotated[Settings, Depends(get_settings)]):
    return PlainTextResponse(robots_txt(settings.base_url), headers=CACHE)


@router.get("/sitemap.xml")
@limiter.limit("60/minute")
async def sitemap(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _ = request  # used by the rate limiter
    profile = await load_public_profile(db, settings)
    return Response(sitemap_xml(profile), media_type="application/xml", headers=CACHE)
