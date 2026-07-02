from typing import List, Annotated, Any
import asyncio
import random
import secrets
import uuid
import os
from fastapi import (
    APIRouter,
    Request,
    Form,
    Response,
    Cookie,
    UploadFile,
    File,
    Depends,
    HTTPException,
)
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse

from app.config import Settings
from app.services import MistralService, ContextStore, SessionStore
from app.dependencies import (
    get_settings,
    get_mistral_service,
    get_context_store,
    get_session_store,
    require_admin,
    limiter,
    COOKIE_PREFIX,
    ACTIVE_ADMIN_SESSIONS,
)
from app.utils import render_template, get_takeover_oob_html, render_template_to_string
from app.constants import ADMIN_SESSION_COOKIE_NAME, COOKIE_MAX_AGE_SECONDS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col
from app.database import get_db_session
from app.models import ChatSession, ChatMessage
from app.schemas import (
    ThemeColors,
    ChatMessageData,
    LoginContext,
    ManageContext,
    StatusContext,
    MessageContext,
    SessionListItemContext,
)
from app.schemas import SessionDetail, UploadedDocument
from app.config import settings

SECURE_COOKIE = settings.environment != "DEV"

router = APIRouter()


@router.get("/manage", response_class=HTMLResponse)
async def manage_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}")
    ] = None,
):
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        return render_template(
            request, "admin_login.html", context_store, LoginContext(next_url="/manage")
        )

    result = await db.execute(
        select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(20)
    )
    recent_sessions = result.scalars().all()

    raw_context = context_store.get_context()
    return render_template(
        request,
        "manage_conversations.html",
        context_store,
        ManageContext(
            active_tab="conversations",
            recent_sessions=list(recent_sessions),
            raw_context=raw_context,
        ),
    )


@router.get("/manage/context", response_class=HTMLResponse)
async def manage_context_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}")
    ] = None,
):
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        return render_template(
            request, "admin_login.html", context_store, LoginContext(next_url="/manage/context")
        )

    raw_context = context_store.get_context()
    return render_template(
        request,
        "manage_context.html",
        context_store,
        ManageContext(
            active_tab="context",
            raw_context=raw_context,
        ),
    )


@router.get("/manage/appearance", response_class=HTMLResponse)
async def manage_appearance_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}")
    ] = None,
):
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        return render_template(
            request,
            "admin_login.html",
            context_store,
            LoginContext(next_url="/manage/appearance"),
        )

    return render_template(
        request,
        "manage_appearance.html",
        context_store,
        ManageContext(
            active_tab="appearance",
            schedule_meeting_url=context_store.get_meeting_url(),
        ),
    )


@router.post("/manage/login")
@limiter.limit("5/minute")
async def manage_login(
    request: Request,
    password: Annotated[str, Form()],
    settings: Annotated[Settings, Depends(get_settings)],
    next_url: str | None = Form(None),
):
    # Add a random artificial delay to simulate "verification" and slightly mitigate timing attacks
    await asyncio.sleep(random.uniform(0.6, 1.5))

    if secrets.compare_digest(password, settings.admin_password):
        session_token = uuid.uuid4().hex
        ACTIVE_ADMIN_SESSIONS.add(session_token)

        response = Response(status_code=204)
        response.headers["HX-Redirect"] = next_url if next_url else "/manage"
        response.set_cookie(
            key=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}",
            value=session_token,
            httponly=True,
            secure=SECURE_COOKIE,
            samesite="strict",
            path="/",
            domain=settings.app_domain,
            max_age=COOKIE_MAX_AGE_SECONDS,
        )
        return response
    raise HTTPException(status_code=401, detail="Invalid password.")


@router.post("/manage/logout")
async def manage_logout(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
):
    res = RedirectResponse(url="/", status_code=303)
    res.delete_cookie(
        f"{COOKIE_PREFIX}admin_session",
        path="/",
        secure=SECURE_COOKIE,
        httponly=True,
        samesite="lax",
        domain=settings.app_domain,
    )
    res.headers["Clear-Site-Data"] = '"cookies", "storage", "cache"'
    return res


@router.post("/manage/colors", response_class=HTMLResponse)
async def manage_colors(
    request: Request,
    shadow_grey: Annotated[str, Form()],
    sweet_salmon: Annotated[str, Form()],
    khaki_beige: Annotated[str, Form()],
    muted_teal: Annotated[str, Form()],
    seaweed: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    colors = ThemeColors(
        shadow_grey=shadow_grey,
        sweet_salmon=sweet_salmon,
        khaki_beige=khaki_beige,
        muted_teal=muted_teal,
        seaweed=seaweed,
    )

    context_store.save_colors(colors)
    return render_template(
        request,
        "status.html",
        context_store,
        StatusContext(
            message="Colors updated successfully! Please hard refresh (Ctrl+F5) to see changes across all pages."
        ),
    )


@router.post("/manage/update_raw", response_class=HTMLResponse)
async def manage_update_raw(
    request: Request,
    raw_context: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    context_store.save_context(raw_context)
    return render_template(
        request,
        "status.html",
        context_store,
        StatusContext(message="Context updated successfully!"),
    )


@router.post("/manage/meeting_url", response_class=HTMLResponse)
async def manage_meeting_url(
    request: Request,
    meeting_url: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    context_store.save_meeting_url(meeting_url)
    return render_template(
        request,
        "status.html",
        context_store,
        StatusContext(message="Meeting link updated successfully!"),
    )


@router.post("/manage/owner_name", response_class=HTMLResponse)
async def manage_owner_name(
    request: Request,
    owner_name: Annotated[str, Form()],
    owner_pronouns: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    context_store.save_owner_name(owner_name)
    context_store.save_owner_pronouns(owner_pronouns)
    return render_template(
        request,
        "status.html",
        context_store,
        StatusContext(message="Owner identity updated successfully!"),
    )


@router.post("/manage/avatar", response_class=HTMLResponse)
async def manage_avatar(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    file: Annotated[UploadFile, File(...)],
    _: Annotated[Any, Depends(require_admin)],
):
    content = await file.read()
    if not content:
        return PlainTextResponse("No file uploaded.", status_code=400)

    with open(context_store.get_avatar_path(), "wb") as f:
        f.write(content)

    return render_template(
        request,
        "status.html",
        context_store,
        StatusContext(
            message="Avatar updated successfully! Please hard refresh (Ctrl+F5) to see changes across all pages."
        ),
    )


@router.post("/manage/upload")
async def manage_upload(
    files: Annotated[List[UploadFile], File()],
    mistral_service: Annotated[MistralService, Depends(get_mistral_service)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    pdf_files: list[UploadedDocument] = []
    for file in files:
        if file.filename and file.filename.endswith(".pdf"):
            content = await file.read()
            pdf_files.append(UploadedDocument(filename=file.filename, content=content))

    if not pdf_files:
        return PlainTextResponse("No valid PDFs uploaded.", status_code=400)

    owner = context_store.get_owner_name()
    new_profile = await mistral_service.generate_profile_from_pdfs(pdf_files, owner)

    old_context = context_store.get_context()
    repos_split = old_context.split("=== Repositories ===")
    if len(repos_split) > 1:
        repos_section = "=== Repositories ===" + repos_split[1]
    else:
        repos_section = ""

    final_context = f"The following is the rich context profile for {owner}:\n\n"
    final_context += new_profile + "\n\n" + repos_section


@router.delete("/manage/chat/{session_id}", response_class=Response)
async def delete_chat_session(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}")
    ] = None,
):
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()

    if session_obj:
        # Broadcast notification to the active user (if any) that the session is deleted
        try:
            with open(
                os.path.join(
                    os.path.dirname(__file__),
                    "../templates/fragments/session_deleted.html",
                ),
                "r",
            ) as f:
                deleted_html = f.read()
            await session_store.broadcast(session_id, deleted_html)
        except Exception as e:
            print(f"Failed to broadcast deletion to {session_id}: {e}")

        await db.delete(session_obj)
        await db.commit()

    # Determine response based on where the delete was triggered from
    if request.headers.get("HX-Target") == "closest .conversation-card":
        # Delete from list view: return empty 200 to remove the card from the DOM
        return Response(status_code=200)
    else:
        # Delete from detailed view: redirect back to list view
        response = Response(status_code=204)
        response.headers["HX-Redirect"] = "/manage"
        return response


@router.get("/manage/chat/{session_id}", response_class=HTMLResponse)
async def manage_chat_get(
    request: Request,
    session_id: str,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin_session: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}{ADMIN_SESSION_COOKIE_NAME}")
    ] = None,
):
    if not admin_session or admin_session not in ACTIVE_ADMIN_SESSIONS:
        return render_template(
            request,
            "admin_login.html",
            context_store,
            LoginContext(next_url=f"/manage/chat/{session_id}"),
        )

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        return HTMLResponse(
            "Session not found or expired. They might have closed the tab."
        )

    # Get history for context
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(col(ChatMessage.created_at))
    )
    history_msgs = msg_result.scalars().all()
    history = [
        ChatMessageData(role=m.role, content=m.content)
        for m in history_msgs
    ]

    session_data = SessionDetail(
        name=session_obj.name,
        company=session_obj.company,
        intent=session_obj.intent,
        human_takeover=session_obj.human_takeover,
        history=history,
    )

    return render_template(
        request,
        "manage_chat.html",
        context_store,
        {
            "session_id": session_id,
            "session_data": session_data.model_dump(),
            "schedule_meeting_url": context_store.get_meeting_url(),
        },
    )


@router.post("/manage/chat/{session_id}/toggle_takeover")
async def manage_chat_toggle_takeover(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[Any, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.human_takeover = not session_obj.human_takeover
        db.add(session_obj)
        await db.commit()

        is_taken_over = session_obj.human_takeover
        oob_html = get_takeover_oob_html(
            session_id, is_taken_over, context_store.get_owner_name()
        )
        await session_store.broadcast(session_id, oob_html)

        msg = (
            f"{context_store.get_owner_name()} has joined the chat."
            if is_taken_over
            else "You are now chatting with the AI again."
        )
        msg_html = render_template_to_string(
            "fragments/system_message.html", StatusContext(message=msg)
        )
        await session_store.broadcast(session_id, msg_html)

    return Response(status_code=204)


@router.post("/manage/chat/{session_id}/send")
async def manage_chat_send(
    request: Request,
    session_id: str,
    message: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[Any, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        return HTMLResponse("Session not found.")

    session_obj.human_takeover = True
    db.add(session_obj)

    assistant_msg = ChatMessage(
        session_id=session_id, role="assistant", content=message
    )
    db.add(assistant_msg)
    await db.commit()

    assistant_html = bytes(
        render_template(
            request,
            "message.html",
            context_store,
            MessageContext(message=message, is_user=False, is_admin=True),
        ).body
    ).decode("utf-8")

    await session_store.broadcast(session_id, assistant_html)
    return Response(status_code=204)


@router.post("/manage/chat/{session_id}/update_name")
async def manage_chat_update_name(
    session_id: str,
    name: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[Any, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.name = name
        db.add(session_obj)
        await db.commit()

    html = render_template_to_string(
        "fragments/session_name.html", SessionListItemContext(session_id=session_id, name=name)
    )
    return HTMLResponse(content=html)


@router.post("/manage/chat/{session_id}/update_intent")
async def manage_chat_update_intent(
    session_id: str,
    intent: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[Any, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.intent = intent
        db.add(session_obj)
        await db.commit()

    html = render_template_to_string(
        "fragments/session_intent.html", SessionListItemContext(session_id=session_id, intent=intent)
    )
    return HTMLResponse(content=html)
