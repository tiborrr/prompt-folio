"""Consent page for the MCP server's OAuth flow (see app.mcp_oauth).

/authorize sends the browser here. The owner logs in with the /manage password
(if not logged in yet) and approves or denies the client.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.dependencies import (
    get_admin_session_cookie,
    get_context_store,
    get_db_session,
    get_settings,
    is_admin_session_active,
    require_admin,
)
from app.mcp_oauth import DatabaseOAuthProvider
from app.schemas import ConsentContext, LoginContext
from app.services import ContextStore
from app.utils import render_template

router = APIRouter()


def get_oauth_provider(
    config: Annotated[Settings, Depends(get_settings)],
) -> DatabaseOAuthProvider:
    return DatabaseOAuthProvider(config)


@router.get("/oauth/consent", response_class=HTMLResponse)
async def oauth_consent_get(
    request: Request,
    request_id: str,
    provider: Annotated[DatabaseOAuthProvider, Depends(get_oauth_provider)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    config: Annotated[Settings, Depends(get_settings)],
):
    pending = await provider.load_pending(request_id)
    if pending is None:
        raise HTTPException(
            status_code=400,
            detail="This authorization request has expired. Start connecting again from Claude.",
        )

    admin_session = get_admin_session_cookie(request, config)
    if not await is_admin_session_active(db, admin_session):
        return await render_template(
            request,
            "admin_login.html",
            context_store,
            db,
            LoginContext(next_url=f"/oauth/consent?request_id={request_id}"),
        )

    return await render_template(
        request,
        "oauth_consent.html",
        context_store,
        db,
        ConsentContext(
            request_id=request_id,
            client_name=pending.client_name,
            redirect_host=pending.redirect_host,
        ),
    )


@router.post("/oauth/consent")
async def oauth_consent_post(
    request_id: Annotated[str, Form()],
    action: Annotated[str, Form()],
    provider: Annotated[DatabaseOAuthProvider, Depends(get_oauth_provider)],
    _: Annotated[None, Depends(require_admin)],
):
    redirect_url = await provider.complete_pending(
        request_id, approved=action == "approve"
    )
    if redirect_url is None:
        raise HTTPException(
            status_code=400,
            detail="This authorization request has expired. Start connecting again from Claude.",
        )
    return RedirectResponse(redirect_url, status_code=303)
