"""Remote MCP server, so Claude (claude.ai custom connector, Claude Code, ...) can
read and update the owner's profile.

Served by the main app at /mcp (streamable HTTP) and protected with OAuth: see
``app.mcp_oauth``. The profile is stored as Editor.js JSON; tools read it as
Markdown and convert Markdown back, so the /manage editor keeps working.
"""

import collections.abc
import contextlib
import io
from typing import cast

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import col, select
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings
from app.database import get_engine
from app.markdown_editorjs import list_sections, markdown_to_editorjs, replace_section
from app.mcp_oauth import MCP_SCOPE, DatabaseOAuthProvider
from app.models import ProfileRevision, SiteSettings, SourceDocument
from app.public_mcp import PUBLIC_MCP_PATH, create_public_mcp_server
from app.public_profile import profile_markdown

MAX_REVISIONS = 50
MAX_DOCUMENT_CHARS = 100_000

INSTRUCTIONS = """\
This server holds the professional profile (CV) of the owner of this Prompt \
Folio site. The site's AI assistant answers recruiters and visitors from this \
profile, so keep it accurate, factual and in the owner's voice.

- Call get_profile first. The profile is Markdown with sections (## headings).
- Prefer update_profile_section for focused changes; use update_profile only \
to rewrite the whole profile.
- Every change saves the previous version; list_profile_revisions and \
restore_profile_revision undo a change.
- Source documents (uploaded CVs, notes) can be read with list_source_documents \
and read_source_document.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def _session_factory(config: Settings) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        get_engine(config.sqlite_url), class_=AsyncSession, expire_on_commit=False
    )


async def _site(db: AsyncSession) -> SiteSettings:
    site = await db.get(SiteSettings, 1)
    if site is None:
        site = SiteSettings(id=1)
        db.add(site)
        await db.flush()
    return site


async def _save_context(db: AsyncSession, site: SiteSettings, context: str, note: str):
    """Keep the current version as a revision, then store the new one."""
    db.add(ProfileRevision(context=site.context, note=note))
    site.context = context
    db.add(site)
    await db.flush()
    # Only keep the newest revisions
    old = await db.execute(
        select(ProfileRevision)
        .order_by(col(ProfileRevision.created_at).desc())
        .offset(MAX_REVISIONS)
    )
    for revision in old.scalars().all():
        await db.delete(revision)
    await db.commit()


def _document_text(doc: SourceDocument) -> str:
    if doc.filename.lower().endswith(".md"):
        return doc.content.decode("utf-8", errors="replace")
    try:
        reader = PdfReader(io.BytesIO(doc.content))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as e:  # noqa: BLE001 - reported to the client
        return f"(Could not read text from this PDF: {e})"


def create_mcp_server(config: Settings) -> MCPServer:
    sessions = _session_factory(config)
    base_url = config.base_url

    server = MCPServer(
        name="prompt-folio",
        title="Prompt Folio profile",
        instructions=INSTRUCTIONS,
        website_url=base_url,
        auth_server_provider=DatabaseOAuthProvider(config),
        auth=AuthSettings(
            issuer_url=base_url,  # pyright: ignore[reportArgumentType]
            resource_server_url=f"{base_url}/mcp",  # pyright: ignore[reportArgumentType]
            validate_token_resource=True,
            required_scopes=[MCP_SCOPE],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[MCP_SCOPE], default_scopes=[MCP_SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    )

    @server.tool(annotations=READ_ONLY)
    async def get_profile() -> dict[str, object]:
        """Read the owner's profile: name, pronouns, meeting link and the full
        profile/CV text as Markdown, with the list of its section headings."""
        async with sessions() as db:
            site = await _site(db)
            profile = profile_markdown(site.context)
            return {
                "owner_name": site.owner_name,
                "owner_pronouns": site.owner_pronouns,
                "meeting_url": site.meeting_url,
                "full_name": site.full_name,
                "headline": site.headline,
                "profile_links": site.profile_links.split(),
                "seo_description": site.seo_description,
                "sections": list_sections(profile),
                "profile_markdown": profile,
            }

    @server.tool(annotations=WRITES)
    async def update_profile(profile_markdown: str, change_note: str = "") -> str:
        """Replace the whole profile with new Markdown. Use ## headings for
        sections, - for bullet lists, **bold**, *italic* and [links](url).
        change_note briefly says what changed (stored with the revision)."""
        if not profile_markdown.strip():
            return "Refused: the new profile is empty. Nothing was changed."
        async with sessions() as db:
            site = await _site(db)
            await _save_context(
                db, site, markdown_to_editorjs(profile_markdown), change_note
            )
        return "Profile updated. The previous version was saved as a revision."

    @server.tool(annotations=WRITES)
    async def update_profile_section(
        heading: str, content_markdown: str, change_note: str = ""
    ) -> str:
        """Replace the content under one heading of the profile (e.g.
        "Experience"), up to the next heading of the same or a higher level.
        The heading itself stays. A heading that does not exist yet is added
        at the end as a new ## section."""
        async with sessions() as db:
            site = await _site(db)
            current = profile_markdown(site.context)
            updated, existed = replace_section(current, heading, content_markdown)
            await _save_context(
                db, site, markdown_to_editorjs(updated), change_note or heading
            )
        action = "updated" if existed else "added as a new section"
        return f"Section '{heading}' {action}. The previous version was saved as a revision."

    @server.tool(annotations=WRITES)
    async def update_owner_details(
        owner_name: str | None = None,
        owner_pronouns: str | None = None,
        meeting_url: str | None = None,
        full_name: str | None = None,
        headline: str | None = None,
        profile_links: list[str] | None = None,
        seo_description: str | None = None,
    ) -> str:
        """Change the owner's details. Fields left out stay as they are.

        - owner_name: short display name the assistant uses ("Alex")
        - owner_pronouns: e.g. "his", "her", "their"
        - meeting_url: meeting/booking link
        - full_name: full name for search engines ("Alex Jansen"); empty uses
          the profile's "# Name" heading
        - headline: job title shown in search results and the page header
        - profile_links: the owner's profiles elsewhere (LinkedIn, GitHub, ...),
          so search engines know they are the same person
        - seo_description: one or two sentences for search results; empty
          uses the first paragraph of the profile's summary"""
        async with sessions() as db:
            site = await _site(db)
            changed: list[str] = []
            if owner_name is not None and owner_name.strip():
                site.owner_name = owner_name.strip()
                changed.append("name")
            if owner_pronouns is not None and owner_pronouns.strip():
                site.owner_pronouns = owner_pronouns.strip()
                changed.append("pronouns")
            if meeting_url is not None:
                site.meeting_url = meeting_url.strip()
                changed.append("meeting link")
            if full_name is not None:
                site.full_name = full_name.strip()
                changed.append("full name")
            if headline is not None:
                site.headline = headline.strip()
                changed.append("headline")
            if profile_links is not None:
                site.profile_links = "\n".join(
                    u.strip() for u in profile_links if u.strip()
                )
                changed.append("profile links")
            if seo_description is not None:
                site.seo_description = seo_description.strip()
                changed.append("description")
            db.add(site)
            await db.commit()
        return f"Updated: {', '.join(changed)}." if changed else "Nothing to update."

    @server.tool(annotations=READ_ONLY)
    async def list_source_documents() -> list[dict[str, str]]:
        """List the uploaded source documents (CV PDFs, Markdown notes)."""
        async with sessions() as db:
            result = await db.execute(
                select(SourceDocument).order_by(col(SourceDocument.created_at).desc())
            )
            return [
                {
                    "id": d.id,
                    "filename": d.filename,
                    "uploaded_at": d.created_at.isoformat(),
                }
                for d in result.scalars().all()
            ]

    @server.tool(annotations=READ_ONLY)
    async def read_source_document(document_id: str) -> str:
        """Read the text of one uploaded source document."""
        async with sessions() as db:
            doc = await db.get(SourceDocument, document_id)
        if doc is None:
            return "No document with that id. Call list_source_documents first."
        text = _document_text(doc)
        if len(text) > MAX_DOCUMENT_CHARS:
            text = text[:MAX_DOCUMENT_CHARS] + "\n\n(truncated)"
        return f"# {doc.filename}\n\n{text}"

    @server.tool(annotations=READ_ONLY)
    async def list_profile_revisions(limit: int = 10) -> list[dict[str, str]]:
        """List earlier versions of the profile, newest first."""
        async with sessions() as db:
            result = await db.execute(
                select(ProfileRevision)
                .order_by(col(ProfileRevision.created_at).desc())
                .limit(max(1, min(limit, MAX_REVISIONS)))
            )
            return [
                {
                    "id": r.id,
                    "saved_at": r.created_at.isoformat(),
                    "change_note": r.note,
                    "preview": profile_markdown(r.context)[:300],
                }
                for r in result.scalars().all()
            ]

    @server.tool(annotations=WRITES)
    async def restore_profile_revision(revision_id: str) -> str:
        """Put an earlier version of the profile back. The current version is
        saved as a revision first, so this can be undone too."""
        async with sessions() as db:
            revision = await db.get(ProfileRevision, revision_id)
            if revision is None:
                return "No revision with that id. Call list_profile_revisions first."
            site = await _site(db)
            await _save_context(
                db, site, revision.context, f"Before restoring {revision_id}"
            )
        return "Revision restored."

    return server


# Paths answered by the MCP app instead of FastAPI
MCP_PATHS = {"/mcp", "/authorize", "/token", "/register", "/revoke"}
WELL_KNOWN_PREFIX = "/.well-known/oauth-"


class MCPRuntime:
    """Builds the MCP apps and runs their session managers for the app's lifetime:
    the owner's OAuth-protected server at /mcp and the public one at /mcp/public."""

    def __init__(self, config: Settings):
        self.config: Settings = config
        self.app: ASGIApp | None = None
        self.server: MCPServer | None = None
        self.public_app: ASGIApp | None = None

    @contextlib.asynccontextmanager
    async def run(self) -> collections.abc.AsyncGenerator[None]:
        # A session manager runs only once, so every lifespan gets fresh servers
        async with contextlib.AsyncExitStack() as stack:
            if self.config.mcp_enabled:
                server = create_mcp_server(self.config)
                app = server.streamable_http_app(
                    streamable_http_path="/mcp",
                    stateless_http=True,
                    json_response=True,
                    # Requests come through the reverse proxy; bearer auth guards /mcp
                    host="0.0.0.0",
                )
                await stack.enter_async_context(server.session_manager.run())
                self.server, self.app = server, app
            if self.config.public_mcp_enabled:
                public = create_public_mcp_server(self.config)
                public_app = public.streamable_http_app(
                    streamable_http_path=PUBLIC_MCP_PATH,
                    stateless_http=True,
                    json_response=True,
                    host="0.0.0.0",
                )
                await stack.enter_async_context(public.session_manager.run())
                self.public_app = public_app
            try:
                yield
            finally:
                self.server, self.app, self.public_app = None, None, None


class MCPDispatchMiddleware:
    """Sends MCP and OAuth paths to the MCP apps; everything else to FastAPI."""

    def __init__(self, app: ASGIApp, runtime: MCPRuntime):
        self.inner: ASGIApp = app
        self.runtime: MCPRuntime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = cast(str, scope["path"])
            if path == PUBLIC_MCP_PATH:
                await self._forward(self.runtime.public_app, scope, receive, send)
                return
            if path in MCP_PATHS or path.startswith(WELL_KNOWN_PREFIX):
                await self._forward(self.runtime.app, scope, receive, send)
                return
        await self.inner(scope, receive, send)

    @staticmethod
    async def _forward(
        app: ASGIApp | None, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if app is None:
            response = PlainTextResponse("MCP server is disabled.", 404)
            await response(scope, receive, send)
            return
        await app(scope, receive, send)
