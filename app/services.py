# pyright: reportArgumentType=false
from __future__ import annotations

import asyncio
import base64
import collections.abc
import json
import re
import typing
from typing import TYPE_CHECKING

import httpx
from mistralai.client import Mistral
from mistralai.client.models import DocumentURLChunk
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.constants import (
    CHAT_REASONING_EFFORT,
    MODEL_CHAT,
    MODEL_OCR,
    PROFILE_REASONING_EFFORT,
    ROLE_ASSISTANT,
    ROLE_TOOL,
)
from app.schemas import (
    ChatMessageData,
    FunctionCallData,
    RecaptchaVerifyResult,
    ThemeColors,
    ToolCallData,
    UploadedDocument,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import SiteSettings


def message_text(content: object) -> str:
    """Return only the answer text of a Mistral message content.

    Reasoning models such as Mistral Large 4 return a list of chunks, with
    "thinking" chunks before the "text" chunks. The thinking must never be
    shown to visitors or stored as the answer, so only text chunks are kept.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for chunk in content:
            if isinstance(chunk, str):
                parts.append(chunk)
                continue
            chunk_type = getattr(chunk, "type", None)
            if chunk_type is None and isinstance(chunk, dict):
                chunk_type = chunk.get("type")
            if chunk_type != "text":
                continue
            text = getattr(chunk, "text", None)
            if text is None and isinstance(chunk, dict):
                text = chunk.get("text")
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return str(content)


TOOL_TEXT_PATTERN = re.compile(r"update_user_profile[^\{]*\{.*?\}", re.DOTALL)
# A tool call written out as text that is still being streamed (no closing brace yet)
PARTIAL_TOOL_TEXT_PATTERN = re.compile(r"update_user_profile.*$", re.DOTALL)
SORRY_NO_CONNECTION = "I'm sorry, I'm having trouble connecting to my brain right now."
SORRY_LOOP = "I'm sorry, I encountered a loop while trying to respond."
EMPTY_REPLY_FALLBACK = "Got it! How else can I help you today?"


def visible_reply_text(text: str) -> str:
    """The part of a (partial) answer that may be shown: leaked tool calls are hidden."""
    text = TOOL_TEXT_PATTERN.sub("", text)
    return PARTIAL_TOOL_TEXT_PATTERN.sub("", text)


class MistralService:
    client: Mistral

    def __init__(self, api_key: str):
        self.client = Mistral(api_key=api_key)

    async def extract_pdf_ocr(self, file_name: str, file_bytes: bytes) -> str:
        try:
            base64_pdf = base64.b64encode(file_bytes).decode("utf-8")
            base64_pdf_url = f"data:application/pdf;base64,{base64_pdf}"

            ocr_response = await self.client.ocr.process_async(
                model=MODEL_OCR, document=DocumentURLChunk(document_url=base64_pdf_url)
            )
            text = ""
            for page in ocr_response.pages:
                text += page.markdown + "\n\n"
            return text
        except Exception as e:  # noqa: BLE001 - OCR failure must not break the upload
            print(f"Error during OCR for {file_name}: {e}")
            return ""

    async def generate_profile_from_docs(
        self,
        uploaded_files: list[UploadedDocument],
        owner_name: str,
        existing_profile: str,
    ) -> str:
        combined_text = ""
        for doc in uploaded_files:
            if doc.filename and doc.filename.lower().endswith(".md"):
                ocr_text = doc.content.decode("utf-8", errors="replace")
            else:
                ocr_text = await self.extract_pdf_ocr(doc.filename, doc.content)
            combined_text += f"\n--- {doc.filename} ---\n{ocr_text}\n"

        system_prompt = (
            "You are an expert profile writer. Below is the user's current professional profile. "
            "Your task is to update and enrich it using the information from the newly uploaded documents. "
            "Preserve the existing tone, formatting, and key information, but smoothly integrate the new details. "
            "Return only the updated markdown."
        )

        try:
            messages = [
                ChatMessageData(role="system", content=system_prompt),
                ChatMessageData(
                    role="user",
                    content=f"CURRENT PROFILE:\n{existing_profile}\n\nNEW UPLOADED DOCUMENTS:\n{combined_text}",
                ),
            ]
            dict_messages = [m.model_dump(exclude_none=True) for m in messages]
            response = await self.client.chat.complete_async(
                model=MODEL_CHAT,
                messages=dict_messages,
                reasoning_effort=PROFILE_REASONING_EFFORT,
            )
            message = response.choices[0].message
            assert message is not None
            return message_text(message.content)
        except Exception as e:  # noqa: BLE001 - fall back to the raw text
            print(f"Mistral chat error: {e}")
            return combined_text

    async def stream_mistral(
        self,
        messages_history: list[ChatMessageData],
        tools: list[dict[str, object]] | None = None,
        tool_callback: typing.Callable[..., collections.abc.Awaitable[None]]
        | None = None,
        max_depth: int = 3,
    ) -> collections.abc.AsyncIterator[str]:
        """Yield the answer text while the model writes it.

        Thinking chunks are skipped. When the model calls a tool, the tool runs
        and the model is asked again; its new text is yielded as well.
        """
        if max_depth <= 0:
            yield SORRY_LOOP
            return

        yielded_text = False
        calls: dict[str, ToolCallData] = {}
        text_parts: list[str] = []
        try:
            dict_messages = [m.model_dump(exclude_none=True) for m in messages_history]
            stream = await self.client.chat.stream_async(
                model=MODEL_CHAT,
                messages=dict_messages,
                tools=tools,
                tool_choice="auto" if tools else "none",
                reasoning_effort=CHAT_REASONING_EFFORT,
            )
            async for event in stream:
                if not event.data.choices:
                    continue
                delta = event.data.choices[0].delta
                content = delta.content
                text = message_text(content) if isinstance(content, (str, list)) else ""
                if text:
                    text_parts.append(text)
                    yielded_text = True
                    yield text
                tool_calls = delta.tool_calls
                if not isinstance(tool_calls, list):
                    continue
                for tc in tool_calls:
                    key = tc.id if isinstance(tc.id, str) and tc.id != "null" else ""
                    key = key or f"index-{tc.index}"
                    arguments = tc.function.arguments
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments)
                    existing = calls.get(key)
                    if existing is None:
                        calls[key] = ToolCallData(
                            id=key,
                            type="function",
                            function=FunctionCallData(
                                name=tc.function.name, arguments=arguments
                            ),
                        )
                    else:
                        existing.function.arguments = (
                            str(existing.function.arguments) + arguments
                        )
        except Exception as e:  # noqa: BLE001 - show a friendly message to the visitor
            print(f"Mistral API Error: {e}")
            if not yielded_text:
                yield SORRY_NO_CONNECTION
            return

        if not (calls and tool_callback):
            return

        assistant_msg = ChatMessageData(
            role=ROLE_ASSISTANT, content="".join(text_parts)
        )
        assistant_msg.tool_calls = list(calls.values())
        messages_history.append(assistant_msg)
        for call in calls.values():
            messages_history.append(
                ChatMessageData(
                    role=ROLE_TOOL,
                    name=call.function.name,
                    content=await self._run_profile_tool(call, tool_callback),
                    tool_call_id=call.id,
                )
            )
        async for text in self.stream_mistral(
            messages_history,
            tools=tools,
            tool_callback=tool_callback,
            max_depth=max_depth - 1,
        ):
            yield text

    @staticmethod
    async def _run_profile_tool(
        call: ToolCallData,
        tool_callback: typing.Callable[..., collections.abc.Awaitable[None]],
    ) -> str:
        if call.function.name != "update_user_profile":
            return f"Unknown tool: {call.function.name}"
        try:
            arguments = call.function.arguments
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
            await tool_callback(
                args.get("name"), args.get("company"), args.get("intent")
            )
            return "Profile updated successfully."
        except Exception as e:  # noqa: BLE001 - reported back to the model
            print(f"Tool error: {e}")
            return f"Failed to update profile: {e}"

    @staticmethod
    async def finish_reply(
        text: str,
        tool_callback: typing.Callable[..., collections.abc.Awaitable[None]]
        | None = None,
    ) -> str:
        """Clean up a streamed answer: run a tool call the model wrote out as
        text, remove it from the answer and never return an empty answer."""
        if tool_callback and "update_user_profile" in text:
            match = re.search(r"update_user_profile[^\{]*(\{.*?\})", text, re.DOTALL)
            if match:
                try:
                    args = json.loads(match.group(1).strip())
                    await tool_callback(
                        args.get("name"), args.get("company"), args.get("intent")
                    )
                except Exception as e:  # noqa: BLE001 - best-effort fallback
                    print(f"Text-based tool parsing error: {e}")
        cleaned = visible_reply_text(text).strip()
        return cleaned or EMPTY_REPLY_FALLBACK

    async def ask_mistral(
        self,
        messages_history: list[ChatMessageData],
        tools: list[dict[str, object]] | None = None,
        tool_callback: typing.Callable[..., collections.abc.Awaitable[None]]
        | None = None,
        max_depth: int = 3,
    ) -> str:
        if max_depth <= 0:
            return "I'm sorry, I encountered a loop while trying to respond."

        try:
            dict_messages = [m.model_dump(exclude_none=True) for m in messages_history]
            response = await self.client.chat.complete_async(
                model=MODEL_CHAT,
                messages=dict_messages,
                tools=tools,
                tool_choice="auto" if tools else "none",
                reasoning_effort=CHAT_REASONING_EFFORT,
            )
            message = response.choices[0].message
            assert message is not None

            if message.tool_calls and tool_callback:
                content_val = message_text(message.content)
                assistant_msg = ChatMessageData(
                    role=ROLE_ASSISTANT, content=content_val
                )
                assistant_msg.tool_calls = []
                for tc in message.tool_calls:
                    tool_call = ToolCallData(
                        id=tc.id,
                        type="function",
                        function=FunctionCallData(
                            name=tc.function.name,
                            arguments=tc.function.arguments,
                        ),
                    )
                    assistant_msg.tool_calls.append(tool_call)
                messages_history.append(assistant_msg)

                for tool_call in message.tool_calls:
                    if tool_call.function.name == "update_user_profile":
                        try:
                            # Mistral's function.arguments can be returned as a dict or str.
                            arguments = tool_call.function.arguments
                            if isinstance(arguments, str):
                                args = json.loads(arguments)
                            else:
                                args = arguments
                            await tool_callback(
                                args.get("name"),
                                args.get("company"),
                                args.get("intent"),
                            )
                            tool_result = "Profile updated successfully."
                        except Exception as e:  # noqa: BLE001 - reported back to the model
                            print(f"Tool error: {e}")
                            tool_result = f"Failed to update profile: {e}"

                        messages_history.append(
                            ChatMessageData(
                                role=ROLE_TOOL,
                                name=tool_call.function.name,
                                content=tool_result,
                                tool_call_id=tool_call.id,
                            )
                        )

                return await self.ask_mistral(
                    messages_history,
                    tools=tools,
                    tool_callback=tool_callback,
                    max_depth=max_depth - 1,
                )

            content_str = message_text(message.content)

            # Text-based tool invocation fallback
            if tool_callback and "update_user_profile" in content_str:
                json_match = re.search(
                    r"update_user_profile[^\{]*(\{.*?\})", content_str, re.DOTALL
                )
                if json_match:
                    try:
                        json_block = json_match.group(1).strip()
                        args = json.loads(json_block)

                        # Execute fallback callback silently
                        await tool_callback(
                            args.get("name"), args.get("company"), args.get("intent")
                        )
                    except Exception as e:  # noqa: BLE001 - best-effort fallback
                        print(f"Text-based tool parsing error: {e}")

            # Final sanitization: Strip the leaked tool call and clean up whitespace
            content_str = re.sub(
                r"update_user_profile[^\{]*\{.*?\}", "", content_str, flags=re.DOTALL
            ).strip()

            # Prevent saving empty strings to the DB which crashes future Mistral API calls
            if not content_str:
                return "Got it! How else can I help you today?"

            return content_str
        except Exception as e:  # noqa: BLE001 - show a friendly message to the visitor
            print(f"Mistral API Error: {e}")
            return "I'm sorry, I'm having trouble connecting to my brain right now."


class RecaptchaService:
    server_key: str
    is_dev: bool

    def __init__(self, server_key: str, is_dev: bool):
        self.server_key = server_key
        self.is_dev = is_dev

    async def verify(self, token: str) -> bool:
        if self.is_dev:
            return True
        verify_url = "https://www.google.com/recaptcha/api/siteverify"
        data = {"secret": self.server_key, "response": token}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(verify_url, data=data)
                result = RecaptchaVerifyResult(**response.json())
                return result.success
        except Exception as e:  # noqa: BLE001 - fail closed
            print(f"Recaptcha verification error: {e}")
            return False


class ContextStore:
    """Database-backed site settings store (singleton row id=1)."""

    MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB

    def __init__(self, storage_path: str | None = None):
        self.storage_path = storage_path

    async def _get_settings(self, db: AsyncSession) -> SiteSettings:
        from app.models import SiteSettings

        result = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
        settings = result.scalar_one_or_none()
        if not settings:
            settings = SiteSettings(id=1)
            db.add(settings)
            await db.commit()
            await db.refresh(settings)
        return settings

    async def get_owner_name(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        return s.owner_name

    async def save_owner_name(self, db: AsyncSession, name: str) -> None:
        s = await self._get_settings(db)
        s.owner_name = name.strip()
        db.add(s)
        await db.commit()

    async def get_owner_pronouns(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        return s.owner_pronouns

    async def save_owner_pronouns(self, db: AsyncSession, pronouns: str) -> None:
        s = await self._get_settings(db)
        s.owner_pronouns = pronouns.strip()
        db.add(s)
        await db.commit()

    async def has_avatar(self, db: AsyncSession) -> bool:
        s = await self._get_settings(db)
        return s.avatar is not None

    async def get_avatar_bytes(self, db: AsyncSession) -> tuple[bytes, str] | None:
        """Returns (avatar_bytes, content_type) or None."""
        s = await self._get_settings(db)
        if s.avatar is not None and s.avatar_content_type is not None:
            return s.avatar, s.avatar_content_type
        return None

    async def get_active_integrations(
        self, db: AsyncSession, config: Settings
    ) -> dict[str, str]:
        s = await self._get_settings(db)
        return {
            "mistral_api_key": s.mistral_api_key or config.mistral_api_key,
            "recaptcha_client_side_key": s.recaptcha_client_side_key
            or config.recaptcha_client_side_key,
            "recaptcha_server_side_key": s.recaptcha_server_side_key
            or config.recaptcha_server_side_key,
            "ntfy_topic": s.ntfy_topic or config.ntfy_topic,
        }

    async def save_integrations(
        self,
        db: AsyncSession,
        mistral_api_key: str | None = None,
        recaptcha_client_side_key: str | None = None,
        recaptcha_server_side_key: str | None = None,
        ntfy_topic: str | None = None,
    ) -> None:
        s = await self._get_settings(db)
        if mistral_api_key is not None:
            s.mistral_api_key = mistral_api_key.strip()
        if recaptcha_client_side_key is not None:
            s.recaptcha_client_side_key = recaptcha_client_side_key.strip()
        if recaptcha_server_side_key is not None:
            s.recaptcha_server_side_key = recaptcha_server_side_key.strip()
        if ntfy_topic is not None:
            s.ntfy_topic = ntfy_topic.strip()
        db.add(s)
        await db.commit()

    async def save_avatar(
        self, db: AsyncSession, content: bytes, content_type: str
    ) -> None:
        if len(content) > self.MAX_AVATAR_SIZE:
            msg = f"Avatar too large ({len(content)} bytes). Max is {self.MAX_AVATAR_SIZE} bytes."
            raise ValueError(msg)
        s = await self._get_settings(db)
        s.avatar = content
        s.avatar_content_type = content_type
        db.add(s)
        await db.commit()

    async def delete_avatar(self, db: AsyncSession) -> None:
        s = await self._get_settings(db)
        s.avatar = None
        s.avatar_content_type = None
        db.add(s)
        await db.commit()

    async def get_context(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        if s.context:
            return s.context
        return f"You are an assistant representing {s.owner_name}."

    async def get_context_markdown(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        if not s.context:
            return f"You are an assistant representing {s.owner_name}."
        from app.editorjs_parser import editorjs_to_markdown

        return editorjs_to_markdown(s.context)

    async def save_context(self, db: AsyncSession, text: str) -> None:
        s = await self._get_settings(db)
        s.context = text
        db.add(s)
        await db.commit()

    async def get_colors(self, db: AsyncSession) -> ThemeColors:
        s = await self._get_settings(db)
        return ThemeColors(
            shadow_grey=s.color_shadow_grey,
            sweet_salmon=s.color_sweet_salmon,
            khaki_beige=s.color_khaki_beige,
            muted_teal=s.color_muted_teal,
            seaweed=s.color_seaweed,
        )

    async def save_colors(self, db: AsyncSession, colors: ThemeColors) -> None:
        s = await self._get_settings(db)
        s.color_shadow_grey = colors.shadow_grey
        s.color_sweet_salmon = colors.sweet_salmon
        s.color_khaki_beige = colors.khaki_beige
        s.color_muted_teal = colors.muted_teal
        s.color_seaweed = colors.seaweed
        db.add(s)
        await db.commit()

    async def get_meeting_url(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        return s.meeting_url

    async def save_meeting_url(self, db: AsyncSession, url: str) -> None:
        s = await self._get_settings(db)
        s.meeting_url = url.strip()
        db.add(s)
        await db.commit()


class NotificationService:
    def __init__(self, topic: str):
        self.topic = topic

    async def send(self, message: str, url: str | None = None):
        if not self.topic:
            return
        headers = {}
        if url:
            headers["Click"] = url
        try:
            async with httpx.AsyncClient() as client:
                _ = await client.post(
                    f"https://ntfy.sh/{self.topic}",
                    content=message.encode("utf-8"),
                    headers=headers,
                )
        except Exception as e:  # noqa: BLE001 - notifications are best-effort
            print(f"Failed to send ntfy.sh notification: {e}")


class SessionStore:
    def __init__(self):
        self.queues: dict[str, list[asyncio.Queue[str]]] = {}

    async def broadcast(self, session_id: str, message_html: str):
        if session_id in self.queues:
            for q in self.queues[session_id]:
                await q.put(message_html)

    def subscribe(self, session_id: str) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue()
        if session_id not in self.queues:
            self.queues[session_id] = []
        self.queues[session_id].append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[str]):
        if session_id in self.queues and q in self.queues[session_id]:
            self.queues[session_id].remove(q)
            if not self.queues[session_id]:
                del self.queues[session_id]


# Singleton instance for default usage
default_session_store = SessionStore()
