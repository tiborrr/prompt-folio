# pyright: reportArgumentType=false
from __future__ import annotations
import typing
from typing import TYPE_CHECKING
import base64
import json
import re
import httpx
import asyncio
import collections.abc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from mistralai.client import Mistral
from mistralai.client.models import DocumentURLChunk
from app.constants import MODEL_CHAT, MODEL_OCR, ROLE_ASSISTANT, ROLE_TOOL
from app.schemas import (
    ThemeColors,
    UploadedDocument,
    ChatMessageData,
    RecaptchaVerifyResult,
    ToolCallData,
    FunctionCallData,
)

if TYPE_CHECKING:
    from app.models import SiteSettings


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
        except Exception as e:
            print(f"Error during OCR for {file_name}: {e}")
            return ""

    async def generate_profile_from_pdfs(
        self, pdf_files: list[UploadedDocument], owner_name: str
    ) -> str:
        combined_text = ""
        for doc in pdf_files:
            ocr_text = await self.extract_pdf_ocr(doc.filename, doc.content)
            combined_text += f"\n--- {doc.filename} ---\n{ocr_text}\n"

        system_prompt = f"You are an expert summarizer. Take the following extracted documents and synthesize them into a rich, cohesive professional profile for {owner_name}. Do not include any meta-commentary, just the profile text."

        try:
            messages = [
                ChatMessageData(role="system", content=system_prompt),
                ChatMessageData(role="user", content=combined_text),
            ]
            dict_messages = [m.model_dump(exclude_none=True) for m in messages]
            response = await self.client.chat.complete_async(
                model=MODEL_CHAT,
                messages=dict_messages,
            )
            message = response.choices[0].message
            assert message is not None
            content = str(message.content) if message.content else None
            return content if content else ""
        except Exception as e:
            print(f"Mistral chat error: {e}")
            return combined_text

    async def ask_mistral(
        self,
        messages_history: list[ChatMessageData],
        tools: list[dict[str, object]] | None = None,
        tool_callback: typing.Callable[..., collections.abc.Awaitable[None]] | None = None,
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
            )
            message = response.choices[0].message
            assert message is not None

            if message.tool_calls and tool_callback:
                content_val = message.content if message.content else None
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
                            await tool_callback(args.get("name"), args.get("company"), args.get("intent"))
                            tool_result = "Profile updated successfully."
                        except Exception as e:
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

            content_str = str(message.content)
            
            # Text-based tool invocation fallback
            if tool_callback and "update_user_profile" in content_str:
                json_match = re.search(r'update_user_profile[^\{]*(\{.*?\})', content_str, re.DOTALL)
                if json_match:
                    try:
                        json_block = json_match.group(1).strip()
                        args = json.loads(json_block)
                        
                        # Execute fallback callback silently
                        await tool_callback(args.get("name"), args.get("company"), args.get("intent"))
                    except (json.JSONDecodeError, Exception) as e:
                        print(f"Text-based tool parsing error: {e}")
            
            # Final sanitization: Strip the leaked tool call and clean up whitespace
            content_str = re.sub(r'update_user_profile[^\{]*\{.*?\}', '', content_str, flags=re.DOTALL).strip()
            
            # Prevent saving empty strings to the DB which crashes future Mistral API calls
            if not content_str:
                return "Got it! How else can I help you today?"
            
            return content_str
        except Exception as e:
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
        except Exception as e:
            print(f"Recaptcha verification error: {e}")
            return False


class ContextStore:
    """Database-backed site settings store (singleton row id=1)."""

    MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB

    async def _get_settings(self, db: AsyncSession) -> "SiteSettings":
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

    async def save_avatar(self, db: AsyncSession, content: bytes, content_type: str) -> None:
        if len(content) > self.MAX_AVATAR_SIZE:
            msg = f"Avatar too large ({len(content)} bytes). Max is {self.MAX_AVATAR_SIZE} bytes."
            raise ValueError(msg)
        s = await self._get_settings(db)
        s.avatar = content
        s.avatar_content_type = content_type
        db.add(s)
        await db.commit()

    async def get_context(self, db: AsyncSession) -> str:
        s = await self._get_settings(db)
        if s.context:
            return s.context
        return f"You are an assistant representing {s.owner_name}."

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
        except Exception as e:
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
