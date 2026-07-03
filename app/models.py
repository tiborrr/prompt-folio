from datetime import datetime, timezone
import uuid
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, LargeBinary


def utcnow():
    return datetime.now(timezone.utc)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="chatsession.id", index=True)
    role: str = Field(index=True)  # "system", "user", "assistant"
    content: str
    created_at: datetime = Field(default_factory=utcnow)

    session: "ChatSession" = Relationship(back_populates="messages")  # basedpyright: ignore[reportAny]


class ChatSession(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str | None = Field(default=None)
    company: str | None = Field(default=None)
    intent: str | None = Field(default=None)
    human_takeover: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)

    messages: list[ChatMessage] = Relationship(  # basedpyright: ignore[reportAny]
        back_populates="session",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "ChatMessage.created_at",
        },
    )


class SiteSettings(SQLModel, table=True):
    """Singleton row (id=1) storing all site configuration."""

    id: int = Field(default=1, primary_key=True)
    owner_name: str = Field(default="Tibor")
    owner_pronouns: str = Field(default="their")
    context: str = Field(default="")
    meeting_url: str = Field(default="")
    color_shadow_grey: str = Field(default="#1e1e24")
    color_sweet_salmon: str = Field(default="#fb9f89")
    color_khaki_beige: str = Field(default="#c4af9a")
    color_muted_teal: str = Field(default="#81ae9d")
    color_seaweed: str = Field(default="#21a179")
    avatar: bytes | None = Field(default=None)
    avatar_content_type: str | None = Field(default=None)


class SourceDocument(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    filename: str
    content: bytes = Field(sa_column=Column(LargeBinary))
    created_at: datetime = Field(default_factory=utcnow)

