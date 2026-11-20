from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ------------------------------------------------------------------------------
# Tool Call Schemas
# ------------------------------------------------------------------------------


class FunctionCallData(BaseModel):
    name: str
    arguments: str


class ToolCallData(BaseModel):
    id: str
    type: str = "function"
    function: FunctionCallData


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

    def as_dict(self) -> dict[str, str]:
        return {
            "shadow_grey": self.shadow_grey,
            "sweet_salmon": self.sweet_salmon,
            "khaki_beige": self.khaki_beige,
            "muted_teal": self.muted_teal,
            "seaweed": self.seaweed,
        }


class UploadedDocument(BaseModel):
    filename: str
    content: bytes


class ChatMessageData(BaseModel):
    role: str
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCallData] | None = None


class SessionDetail(BaseModel):
    name: str | None
    company: str | None
    intent: str | None
    human_takeover: bool
    history: list[ChatMessageData]


class ProfileUpdateArgs(BaseModel):
    """Arguments of the update_user_profile tool call."""

    name: str | None = None
    company: str | None = None
    intent: str | None = None


class RecaptchaVerifyResult(BaseModel):
    success: bool
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] | None = Field(default=None, alias="error-codes")


class SourceDocumentItem(BaseModel):
    """A source document as listed in the manage page (without its content)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str
    filename: str
    created_at: datetime


# ------------------------------------------------------------------------------
# Template Context Models
# ------------------------------------------------------------------------------


class StatusContext(BaseModel):
    message: str


class LoginContext(BaseModel):
    next_url: str


class ManageContext(BaseModel):
    is_upload: bool = False
    active_tab: str
    raw_context: str | None = None
    recent_sessions: list[SessionListItemContext] | None = None
    schedule_meeting_url: str | None = None
    total_chats: int = 0
    takeover_requests: int = 0
    source_documents: list[SourceDocumentItem] | None = None
    mistral_api_key: str | None = None
    mistral_api_key_locked: bool = False

    recaptcha_client_side_key: str | None = None
    recaptcha_client_side_key_locked: bool = False

    recaptcha_server_side_key: str | None = None
    recaptcha_server_side_key_locked: bool = False

    ntfy_topic: str | None = None
    ntfy_topic_locked: bool = False


class ChatSessionContext(BaseModel):
    session_id: str
    history: list[ChatMessageData] | str


class MessageContext(BaseModel):
    message: str | ChatMessageData
    is_user: bool = False
    is_admin: bool = False


class SessionListItemContext(BaseModel):
    id: str
    name: str | None = None
    intent: str | None = None
    company: str | None = None
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


class EditModeContext(BaseModel):
    edit_mode: bool = False
