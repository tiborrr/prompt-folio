from typing import Annotated
import asyncio
import random
import secrets
import uuid
import os
from datetime import datetime, timezone
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

from app.services import MistralService, ContextStore, SessionStore
from app.dependencies import (
    get_mistral_service,
    get_context_store,
    get_session_store,
    require_admin,
    limiter,
    get_admin_session_cookie,
    get_cookie_prefix,
    get_settings,
    create_admin_session,
    delete_admin_session,
    is_admin_session_active,
)
from app.utils import render_template, get_takeover_oob_html, render_template_to_string
from app.constants import ADMIN_SESSION_COOKIE_NAME, COOKIE_MAX_AGE_SECONDS
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col
from app.dependencies import get_db_session
from app.models import ChatSession, ChatMessage, SourceDocument
from app.schemas import (
    ThemeColors,
    ChatMessageData,
    LoginContext,
    ManageContext,
    StatusContext,
    ManageChatContext,
    MessageContext,
    SessionListItemContext,
)
from app.schemas import SessionDetail, UploadedDocument
from app.config import Settings

router = APIRouter()


@router.get("/manage", response_class=HTMLResponse)
async def manage_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    admin_session = get_admin_session_cookie(request, settings)
    if not admin_session or not await is_admin_session_active(db, admin_session):
        return await render_template(
            request, "admin_login.html", context_store, db, LoginContext(next_url="/manage")
        )

    result = await db.execute(
        select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(20)
    )
    recent_sessions = result.scalars().all()

    from sqlalchemy import func
    total_chats = (await db.execute(select(func.count()).select_from(ChatSession))).scalar_one() or 0
    takeover_requests = (await db.execute(select(func.count()).select_from(ChatSession).where(ChatSession.human_takeover == True))).scalar_one() or 0

    raw_context = await context_store.get_context(db)
    return await render_template(
        request,
        "manage_conversations.html",
        context_store,
        db,
        ManageContext(
            active_tab="conversations",
            recent_sessions=[
                SessionListItemContext(
                    id=s.id,
                    name=s.name,
                    intent=s.intent,
                    company=s.company,
                    created_at=s.created_at,
                )
                for s in recent_sessions
            ],
            raw_context=raw_context,
            total_chats=total_chats,
            takeover_requests=takeover_requests,
        ),
    )


@router.get("/manage/context", response_class=HTMLResponse)
async def manage_context_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    admin_session = get_admin_session_cookie(request, settings)
    if not admin_session or not await is_admin_session_active(db, admin_session):
        return await render_template(
            request,
            "admin_login.html",
            context_store,
            db,
            LoginContext(next_url="/manage/context"),
        )

    raw_context = await context_store.get_context(db)
    result = await db.execute(select(SourceDocument).order_by(col(SourceDocument.created_at).desc()))
    source_docs = result.scalars().all()

    return await render_template(
        request,
        "manage_context.html",
        context_store,
        db,
        ManageContext(
            active_tab="context",
            raw_context=raw_context,
            source_documents=list(source_docs),
        ),
    )


@router.get("/manage/appearance", response_class=HTMLResponse)
async def manage_appearance_get(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    admin_session = get_admin_session_cookie(request, settings)
    if not admin_session or not await is_admin_session_active(db, admin_session):
        return await render_template(
            request,
            "admin_login.html",
            context_store,
            db,
            LoginContext(next_url="/manage/appearance"),
        )

    return await render_template(
        request,
        "manage_appearance.html",
        context_store,
        db,
        ManageContext(
            active_tab="appearance",
            schedule_meeting_url=await context_store.get_meeting_url(db),
        ),
    )


@router.post("/manage/login")
@limiter.limit("5/minute")
async def manage_login(
    request: Request,
    password: Annotated[str, Form()],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    next_url: Annotated[str | None, Form()] = None,
):
    _ = request
    # Add a random artificial delay to simulate "verification" and slightly mitigate timing attacks
    await asyncio.sleep(random.uniform(0.6, 1.5))

    if secrets.compare_digest(password, settings.admin_password):
        session_token = password
        await create_admin_session(db, session_token)

        cookie_domain = (
            settings.app_domain
            if settings.environment not in {"DEV", "TEST"} and settings.app_domain not in {None, "localhost"}
            else None
        )

        response = Response(status_code=204)
        response.headers["HX-Redirect"] = next_url if next_url else "/manage"
        response.set_cookie(
            key=f"{get_cookie_prefix(settings)}{ADMIN_SESSION_COOKIE_NAME}",
            value=session_token,
            httponly=True,
            secure=settings.environment not in {"DEV", "TEST"},
            samesite="strict",
            path="/",
            domain=cookie_domain,
            max_age=COOKIE_MAX_AGE_SECONDS,
        )
        return response
    raise HTTPException(status_code=401, detail="Invalid password.")


@router.post("/manage/logout")
async def manage_logout(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    admin_session = get_admin_session_cookie(request, settings)
    await delete_admin_session(db, admin_session)

    res = RedirectResponse(url="/", status_code=303)
    cookie_domain = (
        settings.app_domain
        if settings.environment not in {"DEV", "TEST"} and settings.app_domain not in {None, "localhost"}
        else None
    )
    res.delete_cookie(
        f"{get_cookie_prefix(settings)}admin_session",
        path="/",
        secure=settings.environment not in {"DEV", "TEST"},
        httponly=True,
        samesite="lax",
        domain=cookie_domain,
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
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    colors = ThemeColors(
        shadow_grey=shadow_grey,
        sweet_salmon=sweet_salmon,
        khaki_beige=khaki_beige,
        muted_teal=muted_teal,
        seaweed=seaweed,
    )

    await context_store.save_colors(db, colors)
    return await render_template(
        request,
        "status.html",
        context_store,
        db,
        StatusContext(
            message="Colors updated successfully! Please hard refresh (Ctrl+F5) to see changes across all pages."
        ),
    )


@router.post("/manage/update_raw", response_class=HTMLResponse)
async def manage_update_raw(
    request: Request,
    raw_context: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    await context_store.save_context(db, raw_context)
    return await render_template(
        request,
        "status.html",
        context_store,
        db,
        StatusContext(message="Context updated successfully!"),
    )


@router.post("/manage/meeting_url", response_class=HTMLResponse)
async def manage_meeting_url(
    request: Request,
    meeting_url: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    await context_store.save_meeting_url(db, meeting_url)
    return await render_template(
        request,
        "status.html",
        context_store,
        db,
        StatusContext(message="Meeting link updated successfully!"),
    )


@router.post("/manage/owner_name", response_class=HTMLResponse)
async def manage_owner_name(
    request: Request,
    owner_name: Annotated[str, Form()],
    owner_pronouns: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    await context_store.save_owner_name(db, owner_name)
    await context_store.save_owner_pronouns(db, owner_pronouns)
    return await render_template(
        request,
        "status.html",
        context_store,
        db,
        StatusContext(message="Owner identity updated successfully!"),
    )


@router.post("/manage/avatar", response_class=HTMLResponse)
async def manage_avatar(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File(...)],
    _: Annotated[None, Depends(require_admin)],
):
    content = await file.read()
    if not content:
        return PlainTextResponse("No file uploaded.", status_code=400)

    content_type = file.content_type or "image/png"
    try:
        await context_store.save_avatar(db, content, content_type)
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)

    return await render_template(
        request,
        "status.html",
        context_store,
        db,
        StatusContext(
            message="Avatar updated successfully! Please hard refresh (Ctrl+F5) to see changes across all pages."
        ),
    )


@router.post("/manage/upload")
async def manage_upload(
    files: Annotated[list[UploadFile], File()],
    mistral_service: Annotated[MistralService, Depends(get_mistral_service)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    pdf_files: list[UploadedDocument] = []
    for file in files:
        if file.filename and file.filename.endswith(".pdf"):
            content = await file.read()
            doc = SourceDocument(filename=file.filename, content=content)
            db.add(doc)
    await db.commit()

    # Fetch all source documents to rebuild context
    result = await db.execute(select(SourceDocument).order_by(col(SourceDocument.created_at).desc()))
    all_docs = result.scalars().all()

    if not all_docs:
        return PlainTextResponse("No PDFs available to generate profile.", status_code=400)

    pdf_files = [UploadedDocument(filename=d.filename, content=d.content) for d in all_docs]
    owner = await context_store.get_owner_name(db)
    new_profile = await mistral_service.generate_profile_from_pdfs(pdf_files, owner)

    old_context = await context_store.get_context(db)
    repos_split = old_context.split("=== Repositories ===")
    if len(repos_split) > 1:
        repos_section = "=== Repositories ===" + repos_split[1]
    else:
        repos_section = ""

    final_context = f"The following is the rich context profile for {owner}:\n\n"
    final_context += new_profile + "\n\n" + repos_section

    await context_store.save_context(db, final_context)
    return PlainTextResponse(final_context)


@router.post("/manage/rebuild_context")
async def manage_rebuild_context(
    mistral_service: Annotated[MistralService, Depends(get_mistral_service)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(SourceDocument).order_by(col(SourceDocument.created_at).desc()))
    all_docs = result.scalars().all()
    if not all_docs:
        return PlainTextResponse("No PDFs uploaded yet. Upload a PDF first.", status_code=400)

    pdf_files = [UploadedDocument(filename=d.filename, content=d.content) for d in all_docs]
    owner = await context_store.get_owner_name(db)
    new_profile = await mistral_service.generate_profile_from_pdfs(pdf_files, owner)

    old_context = await context_store.get_context(db)
    repos_split = old_context.split("=== Repositories ===")
    if len(repos_split) > 1:
        repos_section = "=== Repositories ===" + repos_split[1]
    else:
        repos_section = ""

    final_context = f"The following is the rich context profile for {owner}:\n\n"
    final_context += new_profile + "\n\n" + repos_section

    await context_store.save_context(db, final_context)
    return PlainTextResponse(final_context)


@router.get("/manage/document/{document_id}")
async def manage_document_get(
    document_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(SourceDocument).where(SourceDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return Response(
        content=doc.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=\"{doc.filename}\""}
    )


@router.delete("/manage/document/{document_id}", response_class=Response)
async def manage_document_delete(
    document_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(SourceDocument).where(SourceDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    await db.delete(doc)
    await db.commit()
    return Response(status_code=204)


@router.delete("/manage/chat/{session_id}", response_class=Response)
async def delete_chat_session(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    admin_session = get_admin_session_cookie(request, settings)
    if not admin_session or not await is_admin_session_active(db, admin_session):
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
        from app.utils import render_template_to_string

        result = await db.execute(select(ChatSession).order_by(col(ChatSession.created_at).desc()).limit(20))
        recent_sessions = result.scalars().all()
        from sqlalchemy import func
        total_chats = (await db.execute(select(func.count()).select_from(ChatSession))).scalar_one() or 0
        takeover_requests = (await db.execute(select(func.count()).select_from(ChatSession).where(ChatSession.human_takeover == True))).scalar_one() or 0

        stats_html = await render_template_to_string(
            "fragments/conversation_stats.html",
            context_store,
            db,
            ManageContext(
                active_tab="conversations",
                recent_sessions=[
                    SessionListItemContext(
                        id=s.id,
                        name=s.name,
                        intent=s.intent,
                        company=s.company,
                        created_at=s.created_at,
                    )
                    for s in recent_sessions
                ],
                total_chats=total_chats,
                takeover_requests=takeover_requests,
            ),
        )
        response = HTMLResponse(content=stats_html)
        response.headers["HX-Reswap"] = "none"
        return response
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
):
    admin_session = get_admin_session_cookie(request, settings)
    if not admin_session or not await is_admin_session_active(db, admin_session):
        return await render_template(
            request,
            "admin_login.html",
            context_store,
            db,
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
    history = [ChatMessageData(role=m.role, content=m.content) for m in history_msgs]

    session_data = SessionDetail(
        name=session_obj.name,
        company=session_obj.company,
        intent=session_obj.intent,
        human_takeover=session_obj.human_takeover,
        history=history,
    )

    return await render_template(
        request,
        "manage_chat.html",
        context_store,
        db,
        ManageChatContext(
            session_id=session_id,
            session_data=session_data,
            schedule_meeting_url=await context_store.get_meeting_url(db),
        ),
    )


@router.post("/manage/chat/{session_id}/toggle_takeover")
async def manage_chat_toggle_takeover(
    request: Request,
    session_id: str,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.human_takeover = not session_obj.human_takeover
        db.add(session_obj)
        await db.commit()

        is_taken_over = session_obj.human_takeover
        owner_name = await context_store.get_owner_name(db)
        oob_html = await get_takeover_oob_html(
            session_id, is_taken_over, owner_name, context_store, db
        )
        await session_store.broadcast(session_id, oob_html)

        msg = (
            f"{owner_name} has joined the chat."
            if is_taken_over
            else "You are now chatting with the AI again."
        )
        msg_html = await render_template_to_string(
            "fragments/system_message.html", context_store, db, StatusContext(message=msg)
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
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if not session_obj:
        return HTMLResponse("Session not found.")

    session_obj.human_takeover = True
    db.add(session_obj)

    assistant_msg = ChatMessage(
        session_id=session_id, role="admin", content=message
    )
    db.add(assistant_msg)
    await db.commit()

    assistant_html = bytes(
        (await render_template(
            request,
            "message.html",
            context_store,
            db,
            MessageContext(message=message, is_user=False, is_admin=True),
        )).body
    ).decode("utf-8")

    await session_store.broadcast(session_id, assistant_html)
    return Response(status_code=204)


@router.get("/manage/chat/{session_id}/edit_name", response_class=HTMLResponse)
async def manage_chat_edit_name(
    session_id: str,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    name = session_obj.name if session_obj else None
    html = await render_template_to_string(
        "fragments/session_name_edit.html",
        context_store,
        db,
        SessionListItemContext(id=session_id, name=name, created_at=datetime.now(timezone.utc)),
    )
    return HTMLResponse(content=html)


@router.post("/manage/chat/{session_id}/update_name")
async def manage_chat_update_name(
    session_id: str,
    name: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.name = name
        db.add(session_obj)
        await db.commit()

    html = await render_template_to_string(
        "fragments/session_name.html",
        context_store,
        db,
        SessionListItemContext(id=session_id, name=name, created_at=datetime.now(timezone.utc)),
    )
    return HTMLResponse(content=html)


@router.get("/manage/chat/{session_id}/edit_intent", response_class=HTMLResponse)
async def manage_chat_edit_intent(
    session_id: str,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    intent = session_obj.intent if session_obj else None
    html = await render_template_to_string(
        "fragments/session_intent_edit.html",
        context_store,
        db,
        SessionListItemContext(id=session_id, intent=intent, created_at=datetime.now(timezone.utc)),
    )
    return HTMLResponse(content=html)


@router.post("/manage/chat/{session_id}/update_intent")
async def manage_chat_update_intent(
    session_id: str,
    intent: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()
    if session_obj:
        session_obj.intent = intent
        db.add(session_obj)
        await db.commit()

    html = await render_template_to_string(
        "fragments/session_intent.html",
        context_store,
        db,
        SessionListItemContext(id=session_id, intent=intent, created_at=datetime.now(timezone.utc)),
    )
    return HTMLResponse(content=html)
