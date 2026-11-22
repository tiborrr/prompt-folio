import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, Relationship, SQLModel


def utcnow():
    return datetime.now(UTC)


class AdminSession(SQLModel, table=True):
    token: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)


class ChatMessage(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    session_id: str = Field(foreign_key="chatsession.id", index=True)
    role: str = Field(index=True)  # "system", "user", "assistant"
    content: str
    created_at: datetime = Field(default_factory=utcnow)

    session: ChatSession = Relationship(back_populates="messages")  # pyright: ignore[reportAny]


class ChatSession(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str | None = Field(default=None)
    company: str | None = Field(default=None)
    intent: str | None = Field(default=None)
    human_takeover: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)

    messages: list[ChatMessage] = Relationship(  # pyright: ignore[reportAny]
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

    # Public profile: what search engines and AI agents see. Empty values fall
    # back to what the profile text says (its "# Name" heading, its tagline).
    full_name: str = Field(default="")
    headline: str = Field(default="")
    profile_links: str = Field(default="")  # one URL per line (LinkedIn, GitHub, ...)
    seo_description: str = Field(default="")
    # Leave email addresses and phone numbers out of the public pages
    hide_public_contact: bool = Field(default=True)

    # Integrations
    mistral_api_key: str | None = Field(default=None)
    recaptcha_client_side_key: str | None = Field(default=None)
    recaptcha_server_side_key: str | None = Field(default=None)
    ntfy_topic: str | None = Field(default=None)


class SourceDocument(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    filename: str
    content: bytes = Field(sa_column=Column(LargeBinary))
    created_at: datetime = Field(default_factory=utcnow)


class OAuthClient(SQLModel, table=True):
    """An MCP client registered through OAuth dynamic client registration."""

    client_id: str = Field(primary_key=True)
    # OAuthClientInformationFull as JSON
    data: str
    created_at: datetime = Field(default_factory=utcnow)


class OAuthToken(SQLModel, table=True):
    """Pending authorization requests, authorization codes, access and refresh tokens.

    Only the SHA-256 hash of a token is stored. All tokens issued from one
    approval share ``grant_id``, so revoking one revokes the whole grant.
    """

    token_hash: str = Field(primary_key=True)
    kind: str = Field(index=True)  # "request", "code", "access", "refresh"
    client_id: str = Field(index=True)
    grant_id: str = Field(index=True)
    expires_at: int = Field(index=True)  # unix timestamp
    # Kind-specific fields (scopes, redirect URI, PKCE challenge, ...) as JSON
    data: str = Field(default="{}")
    created_at: datetime = Field(default_factory=utcnow)


class ProfileRevision(SQLModel, table=True):
    """Previous versions of the profile context, saved before Claude changes it."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    context: str
    note: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow, index=True)
