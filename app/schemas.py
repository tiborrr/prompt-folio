from pydantic import BaseModel, Field, field_validator
from typing import Any
from datetime import datetime


class ThemeColors(BaseModel):
    shadow_grey: str
    sweet_salmon: str
    khaki_beige: str
    muted_teal: str
    seaweed: str

    @field_validator("*", mode="before")
    @classmethod
    def ensure_hash_prefix(cls, v: str | object) -> str | object:
        if isinstance(v, str):
            v = v.strip()
            if not v.startswith("#"):
                v = f"#{v}"
            while v.startswith("##"):
                v = v[1:]
        return v


class UploadedDocument(BaseModel):
    filename: str
    content: bytes


class ChatMessageData(BaseModel):
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, object]] | None = None


class SessionDetail(BaseModel):
    name: str | None
    company: str | None
    intent: str | None
    human_takeover: bool
    history: list[ChatMessageData]


class RecaptchaVerifyResult(BaseModel):
    success: bool
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] | None = Field(default=None, alias="error-codes")


# ------------------------------------------------------------------------------
# Template Context Models
# ------------------------------------------------------------------------------


class StatusContext(BaseModel):
    message: str


class LoginContext(BaseModel):
    next_url: str


class ManageContext(BaseModel):
    active_tab: str
    raw_context: str | None = None
    recent_sessions: list["SessionListItemContext"] | None = None
    schedule_meeting_url: str | None = None


class ChatSessionContext(BaseModel):
    session_id: str
    history: list["ChatMessageData"] | str


class MessageContext(BaseModel):
    message: str | ChatMessageData
    is_user: bool = False
    is_admin: bool = False


class SessionListItemContext(BaseModel):
    session_id: str
    name: str | None = None
    intent: str | None = None
    created_at: datetime


class SSEEvent(BaseModel):
    event: str
    data: str


class ManageChatContext(BaseModel):
    session_id: str
    session_data: SessionDetail
    schedule_meeting_url: str | None = None


class ErrorContext(BaseModel):
    error: str


class TakeoverControlsContext(BaseModel):
    session_id: str
    is_taken_over: bool
    owner_name: str
