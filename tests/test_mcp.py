"""MCP server: OAuth flow (register, consent, token, refresh, revoke) and the profile tools."""

import base64
import collections.abc
import contextlib
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_settings
from app.editorjs_parser import editorjs_to_markdown
from app.main import app, mcp_runtime
from app.markdown_editorjs import markdown_to_editorjs, replace_section
from app.mcp_oauth import DatabaseOAuthProvider

REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
BASE = "http://localhost:3005"

pytestmark = pytest.mark.asyncio(loop_scope="function")


@contextlib.asynccontextmanager
async def mcp_client() -> collections.abc.AsyncGenerator[AsyncClient]:
    # Other test modules install dependency overrides at import time
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    try:
        async with (
            mcp_runtime.run(),
            AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client,
        ):
            yield client
    finally:
        app.dependency_overrides.update(saved)


async def _login(client: AsyncClient) -> None:
    response = await client.post(
        "/manage/login", data={"password": "test_secure_password"}
    )
    assert response.status_code == 204


async def _register(client: AsyncClient, redirect_uri: str = REDIRECT_URI):
    return await client.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


async def _authorize(client: AsyncClient, client_id: str) -> tuple[str, str]:
    """Run /authorize; returns (request_id, PKCE verifier)."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    response = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "resource": f"{BASE}/mcp",
        },
    )
    assert response.status_code == 302, response.text
    location = urlparse(response.headers["location"])
    assert location.path == "/oauth/consent"
    return parse_qs(location.query)["request_id"][0], verifier


async def _get_tokens(client: AsyncClient) -> dict[str, str]:
    client_id = (await _register(client)).json()["client_id"]
    request_id, verifier = await _authorize(client, client_id)

    await _login(client)
    consent = await client.get(f"/oauth/consent?request_id={request_id}")
    assert consent.status_code == 200
    assert "Connect Claude" in consent.text

    approved = await client.post(
        "/oauth/consent", data={"request_id": request_id, "action": "approve"}
    )
    assert approved.status_code == 303
    redirect = urlparse(approved.headers["location"])
    query = parse_qs(redirect.query)
    assert redirect.netloc == "claude.ai"
    assert query["state"] == ["xyz"]

    token = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": f"{BASE}/mcp",
        },
    )
    assert token.status_code == 200, token.text
    return {"client_id": client_id, **token.json()}


async def _rpc(
    client: AsyncClient, token: str | None, method: str, params: dict[str, object]
):
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-06-18",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


async def _call_tool(client: AsyncClient, token: str, name: str, **arguments: object):
    response = await _rpc(
        client, token, "tools/call", {"name": name, "arguments": arguments}
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    structured = result.get("structuredContent")
    if structured is not None:
        # Lists and strings come wrapped as {"result": ...}
        return structured.get("result", structured)
    return result["content"][0]["text"]


async def test_metadata_is_public():
    async with mcp_client() as mcp:
        resource = await mcp.get("/.well-known/oauth-protected-resource/mcp")
        assert resource.status_code == 200
        assert resource.json()["resource"] == f"{BASE}/mcp"

        server = await mcp.get("/.well-known/oauth-authorization-server")
        assert server.status_code == 200
        assert server.json()["registration_endpoint"] == f"{BASE}/register"


async def test_mcp_requires_a_token():
    async with mcp_client() as mcp:
        response = await _rpc(mcp, None, "tools/list", {})
        assert response.status_code == 401
        assert "resource_metadata" in response.headers["www-authenticate"]

        response = await _rpc(mcp, "not-a-token", "tools/list", {})
        assert response.status_code == 401


async def test_registration_rejects_unknown_redirect_hosts():
    async with mcp_client() as mcp:
        response = await _register(mcp, "https://evil.example/callback")
        assert response.status_code == 400

        # Loopback is fine (Claude Code, MCP Inspector)
        response = await _register(mcp, "http://localhost:6274/oauth/callback")
        assert response.status_code == 201


async def test_consent_requires_login():
    async with mcp_client() as mcp:
        client_id = (await _register(mcp)).json()["client_id"]
        request_id, _ = await _authorize(mcp, client_id)

        page = await mcp.get(f"/oauth/consent?request_id={request_id}")
        assert "Admin Login" in page.text

        approved = await mcp.post(
            "/oauth/consent", data={"request_id": request_id, "action": "approve"}
        )
        assert approved.status_code in {307, 401}
        assert "code=" not in approved.headers.get("location", "")


async def test_deny_redirects_with_error():
    async with mcp_client() as mcp:
        client_id = (await _register(mcp)).json()["client_id"]
        request_id, _ = await _authorize(mcp, client_id)
        await _login(mcp)
        denied = await mcp.post(
            "/oauth/consent", data={"request_id": request_id, "action": "deny"}
        )
        assert denied.status_code == 303
        assert "error=access_denied" in denied.headers["location"]

        # The request is used up
        again = await mcp.post(
            "/oauth/consent", data={"request_id": request_id, "action": "approve"}
        )
        assert again.status_code == 400


async def test_profile_tools_round_trip():
    async with mcp_client() as mcp:
        tokens = await _get_tokens(mcp)
        access = tokens["access_token"]

        listed = await _rpc(mcp, access, "tools/list", {})
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert {"get_profile", "update_profile", "update_profile_section"} <= names

        result = await _call_tool(
            mcp,
            access,
            "update_profile",
            profile_markdown="## Summary\n\nEngineer in **Deventer**.\n\n## Experience\n\n- Acme & Co\n- Initech",
            change_note="first version",
        )
        assert "Profile updated" in result

        result = await _call_tool(
            mcp,
            access,
            "update_profile_section",
            heading="Experience",
            content_markdown="- Globex (2024-now)\n- Acme & Co",
        )
        assert "updated" in result

        profile = await _call_tool(mcp, access, "get_profile")
        assert profile["sections"] == ["## Summary", "## Experience"]
        assert "Engineer in **Deventer**." in profile["profile_markdown"]
        assert "- Globex (2024-now)\n- Acme & Co" in profile["profile_markdown"]
        assert "Initech" not in profile["profile_markdown"]

        await _call_tool(mcp, access, "update_owner_details", owner_pronouns="his")
        profile = await _call_tool(mcp, access, "get_profile")
        assert profile["owner_pronouns"] == "his"

        revisions = await _call_tool(mcp, access, "list_profile_revisions")
        assert len(revisions) == 2
        # Newest revision holds the version before the section update
        await _call_tool(
            mcp, access, "restore_profile_revision", revision_id=revisions[0]["id"]
        )
        profile = await _call_tool(mcp, access, "get_profile")
        assert "Initech" in profile["profile_markdown"]


async def test_source_documents():
    async with mcp_client() as mcp:
        from app.dependencies import get_db_session_factory
        from app.models import SourceDocument

        async with get_db_session_factory(get_settings())() as db:
            db.add(
                SourceDocument(id="doc1", filename="notes.md", content=b"# Notes\nHi")
            )
            await db.commit()

        access = (await _get_tokens(mcp))["access_token"]
        docs = await _call_tool(mcp, access, "list_source_documents")
        assert docs[0]["filename"] == "notes.md"
        text = await _call_tool(mcp, access, "read_source_document", document_id="doc1")
        assert "# Notes\nHi" in text


async def test_refresh_rotates_and_revoke_ends_the_grant():
    async with mcp_client() as mcp:
        tokens = await _get_tokens(mcp)
        refreshed = await mcp.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": tokens["client_id"],
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        new = refreshed.json()

        # The old access token stopped working, the new one works
        assert (
            await _rpc(mcp, tokens["access_token"], "tools/list", {})
        ).status_code == 401
        assert (
            await _rpc(mcp, new["access_token"], "tools/list", {})
        ).status_code == 200

        # Revoking one token of the grant ends the whole grant
        provider = DatabaseOAuthProvider(get_settings())
        access_token = await provider.load_access_token(new["access_token"])
        assert access_token is not None
        await provider.revoke_token(access_token)
        assert (
            await _rpc(mcp, new["access_token"], "tools/list", {})
        ).status_code == 401


def test_markdown_round_trips_through_editorjs():
    md = (
        "# Tibor\n\n"
        "Developer & architect with **10 years** of *Python*. See [site](https://x.nl).\n\n"
        "## Skills\n\n"
        "- Python\n  - FastAPI\n- Go\n\n"
        "1. one\n2. two\n\n"
        "- [x] done\n- [ ] todo\n\n"
        "---\n\n"
        "```python\nprint('<hi>')\n```"
    )
    data = json.loads(markdown_to_editorjs(md))
    assert [b["type"] for b in data["blocks"]] == [
        "header",
        "paragraph",
        "header",
        "list",
        "list",
        "list",
        "delimiter",
        "code",
    ]
    assert editorjs_to_markdown(markdown_to_editorjs(md)) == md


def test_replace_section_appends_missing_heading():
    doc, existed = replace_section("## A\n\ntext\n", "Languages", "- Dutch")
    assert not existed
    assert doc == "## A\n\ntext\n\n## Languages\n\n- Dutch\n"

    doc, existed = replace_section(
        "## A\n\nold\n\n### A.1\n\nsub\n\n## B\n\nkeep", "a", "new"
    )
    assert existed
    assert doc == "## A\n\nnew\n\n## B\n\nkeep\n"


def test_redirect_host_patterns():
    from app.mcp_oauth import redirect_uri_allowed

    allowed = {"claude.ai", "*.cursor.com"}
    cursor = "https://www.cursor.com/agents/mcp/oauth/callback"
    assert redirect_uri_allowed(cursor, allowed)
    assert redirect_uri_allowed("https://cursor.com/cb", allowed)
    assert redirect_uri_allowed("https://claude.ai/api/mcp/auth_callback", allowed)
    # Exact hosts do not cover subdomains, and lookalike domains never match
    assert not redirect_uri_allowed("https://evil.claude.ai/cb", allowed)
    assert not redirect_uri_allowed("https://evilcursor.com/cb", allowed)
    assert not redirect_uri_allowed("https://cursor.com.evil.example/cb", allowed)
    # https only, except on loopback
    assert not redirect_uri_allowed("http://www.cursor.com/cb", allowed)
    assert redirect_uri_allowed("http://127.0.0.1:33418/callback", allowed)
    # "*" allows any https host
    assert redirect_uri_allowed("https://anything.example/cb", {"*"})
    assert not redirect_uri_allowed("http://anything.example/cb", {"*"})


def test_default_allowlist_covers_common_clients():
    from app.mcp_oauth import DatabaseOAuthProvider, redirect_uri_allowed

    hosts = DatabaseOAuthProvider(get_settings()).allowed_hosts
    for uri in [
        "https://claude.ai/api/mcp/auth_callback",
        "https://www.cursor.com/agents/mcp/oauth/callback",
        "https://chatgpt.com/connector_platform_oauth_redirect",
        "https://grok.com/oauth/callback",
    ]:
        assert redirect_uri_allowed(uri, hosts), uri
