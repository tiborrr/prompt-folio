from datetime import datetime, timezone
import uuid
from sqlmodel import Field, SQLModel, Relationship


def utcnow():
    return datetime.now(timezone.utc)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="chatsession.id", index=True)
    role: str = Field(index=True)  # "system", "user", "assistant"
    content: str
    created_at: datetime = Field(default_factory=utcnow)

    session: "ChatSession" = Relationship(back_populates="messages")


class ChatSession(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str | None = Field(default=None)
    company: str | None = Field(default=None)
    intent: str | None = Field(default=None)
    human_takeover: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)

    messages: list[ChatMessage] = Relationship(
        back_populates="session",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "ChatMessage.created_at",
        },
    )
