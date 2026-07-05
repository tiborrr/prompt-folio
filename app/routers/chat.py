import uuid
import asyncio
from typing import Annotated
from fastapi import APIRouter, Request, Form, Response, Cookie, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col

from app.config import Settings
from app.services import MistralService, ContextStore, SessionStore, NotificationService
from app.dependencies import (
    get_settings,
    get_mistral_service,
    get_context_store,
    get_session_store,
    require_recaptcha,
    limiter,
    get_notification_service,
)
from app.database import get_db_session
from app.models import ChatSession, ChatMessage
from app.utils import render_template, get_takeover_oob_html, render_template_to_string
from app.constants import (
    ROLE_SYSTEM,
    ROLE_USER,
    ROLE_ASSISTANT,
    ADMIN_NOTIFICATION_TRUNCATE_LEN,
    NEW_SESSION_NOTIFICATION_MSG_COUNT,
    UPDATE_USER_PROFILE_TOOL,
)
from app.schemas import (
    ChatMessageData,
    StatusContext,
    ChatSessionContext,
    MessageContext,
    SSEEvent,
)
from app.config import settings

COOKIE_PREFIX = "" if settings.environment == "DEV" else "__Secure-"
SECURE_COOKIE = settings.environment != "DEV"

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def index(
    request: Request,
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_id: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}session_id")
    ] = None,
):
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        if result.scalar_one_or_none():
            msg_result = await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(col(ChatMessage.created_at))
            )
            history_msgs = msg_result.scalars().all()
            history = [
                ChatMessageData(role=m.role, content=m.content)
                for m in history_msgs
                if m.role != ROLE_SYSTEM
            ]
            return await render_template(
                request,
                "chat.html",
                context_store,
                db,
                ChatSessionContext(session_id=session_id, history=history),
            )

    # Create new session
    new_session_id = str(uuid.uuid4())
    system_context = await context_store.get_context(db)

    new_session = ChatSession(id=new_session_id)
    db.add(new_session)

    owner_name = await context_store.get_owner_name(db)
    owner_pronouns = await context_store.get_owner_pronouns(db)
    msg1 = ChatMessage(
        session_id=new_session_id, role=ROLE_SYSTEM, content=system_context
    )
    msg2 = ChatMessage(
        session_id=new_session_id,
        role=ROLE_SYSTEM,
        content=f"You are {owner_name}'s AI assistant. The user has just opened the chat. Your previous message was a friendly welcome. Gently and naturally learn their name and what they are looking for during the conversation. IMPORTANT: Ask only ONE question at a time. Do not overwhelm the user with multiple questions in a single response. When you learn their name or intent, use the update_user_profile tool to save it.",
    )

    welcome_text = f"Hi! I am {owner_name}'s AI assistant. I have read {owner_pronouns} resume and repositories. How can I help you today?"
    msg3 = ChatMessage(
        session_id=new_session_id, role=ROLE_ASSISTANT, content=welcome_text
    )

    db.add_all([msg1, msg2, msg3])
    await db.commit()

    history = [ChatMessageData(role=ROLE_ASSISTANT, content=welcome_text)]

    res = await render_template(
        request,
        "chat.html",
        context_store,
        db,
        ChatSessionContext(session_id=new_session_id, history=history),
    )
    res.set_cookie(
        key=f"{COOKIE_PREFIX}session_id",
        value=new_session_id,
        httponly=True,
        secure=SECURE_COOKIE,
        samesite="lax",
        path="/",
        domain=settings.app_domain if settings.environment != "DEV" else None,
    )
    return res


@router.get("/stream/{session_id}")
async def chat_stream(
    request: Request,
    session_id: str,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    if not result.scalar_one_or_none():
        return Response(status_code=404)

    async def event_publisher():
        q = session_store.subscribe(session_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message_html = await q.get()
                yield SSEEvent(event="chat_message", data=message_html).model_dump()
        except asyncio.CancelledError:
            pass
        finally:
            session_store.unsubscribe(session_id, q)

    return EventSourceResponse(event_publisher())


@router.post("/takeover_request")
@limiter.limit("5/minute")
async def takeover_request(
    request: Request,
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(require_recaptcha)],
    session_id: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}session_id")
    ] = None,
):
    if not session_id:
        return HTMLResponse("Session expired.", status_code=400)

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()

    if not session_obj:
        return HTMLResponse("Session expired.", status_code=400)

    session_obj.human_takeover = True
    db.add(session_obj)
    await db.commit()

    admin_url = str(request.base_url).rstrip("/") + f"/manage/chat/{session_id}"
    await notification_service.send(
        f"URGENT: {session_obj.name} requested to chat with you directly!",
        url=admin_url,
    )

    owner_name = await context_store.get_owner_name(db)
    oob_html = await get_takeover_oob_html(session_id, True, owner_name, context_store, db)
    await session_store.broadcast(session_id, oob_html)

    msg = f"{owner_name} has been notified and can chat with you directly now."
    msg_html = await render_template_to_string(
        "fragments/system_message.html", context_store, db, StatusContext(message=msg)
    )
    await session_store.broadcast(session_id, msg_html)

    return Response(status_code=204)


@router.post("/revert_takeover")
async def revert_takeover(
    request: Request,
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_id: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}session_id")
    ] = None,
):
    if not session_id:
        return HTMLResponse("Session expired.", status_code=400)

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()

    if session_obj:
        session_obj.human_takeover = False
        db.add(session_obj)
        await db.commit()

        owner_name = await context_store.get_owner_name(db)
        oob_html = await get_takeover_oob_html(
            session_id, False, owner_name, context_store, db
        )
        await session_store.broadcast(session_id, oob_html)

        msg_html = await render_template_to_string(
            "fragments/system_message.html",
            context_store,
            db,
            StatusContext(message="You are now chatting with the AI again."),
        )
        await session_store.broadcast(session_id, msg_html)

    return Response(status_code=204)


@router.post("/chat")
@limiter.limit("20/minute")
async def chat(
    request: Request,
    message: Annotated[str, Form()],
    context_store: Annotated[ContextStore, Depends(get_context_store)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    mistral_service: Annotated[MistralService, Depends(get_mistral_service)],
    notification_service: Annotated[
        NotificationService, Depends(get_notification_service)
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    background_tasks: BackgroundTasks,
    _: Annotated[None, Depends(require_recaptcha)],
    session_id: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}session_id")
    ] = None,
):
    if not session_id:
        error_html = await render_template_to_string(
            "fragments/system_message.html",
            context_store,
            db,
            StatusContext(message="No active session found. Please refresh the page."),
        )
        return HTMLResponse(error_html, status_code=400)

    result = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session_obj = result.scalar_one_or_none()

    if not session_obj:
        error_html = await render_template_to_string(
            "fragments/system_message.html",
            context_store,
            db,
            StatusContext(message="Session expired. Please refresh the page."),
        )
        return HTMLResponse(error_html, status_code=400)

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role=ROLE_USER, content=message)
    db.add(user_msg)
    await db.commit()

    user_html = bytes(
        (await render_template(
            request,
            "message.html",
            context_store,
            db,
            MessageContext(message=message, is_user=True),
        )).body
    ).decode("utf-8")
    await session_store.broadcast(session_id, user_html)

    if session_obj.human_takeover:
        return Response(status_code=204)

    async def generate_ai_response():
        from app.database import get_engine
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as BgAsyncSession

        engine = get_engine(settings.sqlite_url)
        bg_session_factory = async_sessionmaker(
            engine, class_=BgAsyncSession, expire_on_commit=False
        )

        try:
            async with bg_session_factory() as bg_db:
                # Step 1: Inject the typing indicator normally
                typing_indicator_html = await render_template_to_string(
                    "fragments/typing_indicator.html",
                    context_store,
                    bg_db,
                )
                await session_store.broadcast(session_id, typing_indicator_html)
                
                # Step 2: Process the request (call LLM)
                # Get session
                result = await bg_db.execute(
                    select(ChatSession).where(ChatSession.id == session_id)
                )
                bg_session_obj = result.scalar_one_or_none()
                if not bg_session_obj:
                    return

                # Get history for AI
                msg_result = await bg_db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(col(ChatMessage.created_at))
                )
                history_msgs = msg_result.scalars().all()
                history = [
                    ChatMessageData(role=ROLE_ASSISTANT if m.role == "admin" else m.role, content=m.content) 
                    for m in history_msgs if m.content and m.content.strip() != ""
                ]

                # Inject current profile so Mistral remembers it across messages
                if bg_session_obj.name or bg_session_obj.intent:
                    profile_text = f"Current known user profile - Name: {bg_session_obj.name or 'Unknown'}, Intent: {bg_session_obj.intent or 'Unknown'}"
                    history.append(ChatMessageData(role=ROLE_SYSTEM, content=profile_text))

                # Notify admin on first user message
                if len(history_msgs) == NEW_SESSION_NOTIFICATION_MSG_COUNT:
                    admin_url = (
                        str(request.base_url).rstrip("/") + f"/manage/chat/{session_id}"
                    )
                    await notification_service.send(
                        f'New chat started! User says: "{message[:ADMIN_NOTIFICATION_TRUNCATE_LEN]}..."',
                        url=admin_url,
                    )

                tools = [UPDATE_USER_PROFILE_TOOL]

                async def update_profile_callback(name: str | None, company: str | None, intent: str | None):
                    updated = False
                    if name and not bg_session_obj.name:
                        bg_session_obj.name = name
                        updated = True
                    if company and not bg_session_obj.company:
                        bg_session_obj.company = company
                        updated = True
                    if intent and not bg_session_obj.intent:
                        bg_session_obj.intent = intent
                        updated = True

                    if updated:
                        bg_db.add(bg_session_obj)
                        await bg_db.commit()

                assistant_response = await mistral_service.ask_mistral(
                    history, tools=tools, tool_callback=update_profile_callback
                )

                # Save AI message
                assistant_msg = ChatMessage(
                    session_id=session_id, role=ROLE_ASSISTANT, content=assistant_response
                )
                bg_db.add(assistant_msg)
                await bg_db.commit()

                # Step 3 & 4: Bundle the deletion with the first chunk of AI response
                assistant_html = bytes(
                    (await render_template(
                        request,
                        "message.html",
                        context_store,
                        bg_db,
                        MessageContext(message=assistant_response, is_user=False),
                    )).body
                ).decode("utf-8")
                
                # Prepend the OOB delete to the AI response so they're in the same payload
                response_with_delete = '<div id="typing-indicator" hx-swap-oob="delete"></div>' + assistant_html
                await session_store.broadcast(session_id, response_with_delete)
        except Exception as e:
            # If there's an error, still remove the typing indicator
            await session_store.broadcast(session_id, '<div id="typing-indicator" hx-swap-oob="delete"></div>')
            raise e
        finally:
            pass

    background_tasks.add_task(generate_ai_response)

    return Response(status_code=204)


@router.post("/clear")
async def clear_session(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_id: Annotated[
        str | None, Cookie(alias=f"{COOKIE_PREFIX}session_id")
    ] = None,
):
    if session_id:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session_obj = result.scalar_one_or_none()
        if session_obj:
            await db.delete(
                session_obj
            )  # cascades to messages due to relationship config
            await db.commit()

    res = RedirectResponse(url="/", status_code=303)
    res.delete_cookie(
        f"{COOKIE_PREFIX}session_id",
        path="/",
        secure=SECURE_COOKIE,
        httponly=True,
        samesite="lax",
        domain=settings.app_domain,
    )
    return res
