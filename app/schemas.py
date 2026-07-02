from pydantic import BaseModel, Field, field_validator
from typing import Any


class ThemeColors(BaseModel):
    shadow_grey: str
    sweet_salmon: str
    khaki_beige: str
    muted_teal: str
    seaweed: str

    @field_validator("*", mode="before")
    @classmethod
    def ensure_hash_prefix(cls, v: Any) -> Any:
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
    tool_calls: list[dict[str, Any]] | None = None


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
