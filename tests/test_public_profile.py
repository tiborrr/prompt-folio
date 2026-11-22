"""Public profile for search engines and AI agents: the pages, the files
(robots.txt, sitemap.xml, llms.txt, profile.md), the structured data and the
public MCP server."""

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response

from app.editorjs_parser import editorjs_to_markdown
from app.markdown_editorjs import markdown_to_editorjs
from app.models import SiteSettings
from app.public_profile import (
    build_public_profile,
    headline_from_profile,
    identity_links,
    name_from_profile,
    redact_contact,
    summary_from_profile,
)
from app.schemas import ChatMessageData
from tests.test_mcp import BASE, mcp_client

PROFILE = """# **Alex Jansen**

**IT Architect & Full Stack Developer**
Deventer, Netherlands | +31 6 12 34 56 78 | alex@example.com | [LinkedIn](www.linkedin.com/in/alexjansen)

---

## **Professional Summary**

Innovative **IT Architect** who builds cloud-native platforms, CI/CD pipelines and AI agent automation for growing companies.

## **Experience**

- **Acme** | *Amsterdam* – Platform lead (2019 – 2023), cut processing from 2 minutes to seconds
- Contributed to [uv](https://github.com/astral-sh/uv-docker-example)

## **Let’s Connect!**

📧 **alex@example.com** | 📞 **+31 6 12 34 56 78** | 🔗 [LinkedIn](www.linkedin.com/in/alexjansen)
Mail [me](mailto:alex@example.com)
"""


def json_body(response: Response) -> dict[str, object]:
    return cast(dict[str, object], response.json())


async def login(client: AsyncClient) -> None:
    response = await client.post(
        "/manage/login", data={"password": "test_secure_password"}
    )
    assert response.status_code == 204


PHONE = re.compile(r"\+31 6 12 34 56 78|12 34 56")


def test_redact_contact_keeps_the_rest_of_the_line():
    redacted = redact_contact(PROFILE)
    assert "alex@example.com" not in redacted
    assert not PHONE.search(redacted)
    assert "mailto:" not in redacted
    assert "Deventer, Netherlands | [LinkedIn](www.linkedin.com/in/alexjansen)" in (
        redacted
    )
    # Year ranges and numbers in the text are not phone numbers
    assert "(2019 – 2023)" in redacted
    assert "2 minutes" in redacted
    # The contact line keeps only its LinkedIn part
    assert "🔗 [LinkedIn](www.linkedin.com/in/alexjansen)" in redacted
    assert "📧" not in redacted


def test_name_headline_summary_and_links_come_from_the_profile():
    assert name_from_profile(PROFILE) == "Alex Jansen"
    assert headline_from_profile(PROFILE) == "IT Architect & Full Stack Developer"
    assert summary_from_profile(PROFILE).startswith("Innovative IT Architect who")
    # Only profiles that identify the person, not projects they worked on
    assert identity_links(PROFILE) == ["https://www.linkedin.com/in/alexjansen"]


def _site(**fields: object) -> SiteSettings:
    site = SiteSettings(id=1, owner_name="Alex", context=markdown_to_editorjs(PROFILE))
    for key, value in fields.items():
        setattr(site, key, value)
    return site


def test_settings_override_the_profile_and_contact_can_be_shown():
    profile = build_public_profile(
        _site(
            headline="Solution Architect",
            profile_links="https://github.com/alexj\nwww.linkedin.com/in/alexjansen",
            hide_public_contact=False,
        ),
        BASE,
    )
    assert profile.name == "Alex Jansen"
    assert profile.title == "Alex Jansen – Solution Architect"
    assert profile.links == [
        "https://github.com/alexj",
        "https://www.linkedin.com/in/alexjansen",
    ]
    assert "alex@example.com" in profile.markdown
    # Links without a scheme get https:// instead of pointing at this site
    assert "](https://www.linkedin.com/in/alexjansen)" in profile.markdown
    # The page header shows the name and headline; the body does not repeat them
    assert not profile.body_markdown.startswith("#")
    assert "Full Stack Developer**" not in profile.body_markdown.splitlines()[0]


async def _seed(client: AsyncClient, **fields: str) -> None:
    """Store the test profile through /manage, as the owner would."""
    await login(client)
    response = await client.post(
        "/manage/update_raw",
        data={"raw_context": markdown_to_editorjs(PROFILE)},
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        "/manage/public_profile",
        data={
            "full_name": "",
            "headline": "Solution Architect",
            "profile_links": "https://github.com/alexj",
            "seo_description": fields.get("seo_description", ""),
            "hide_public_contact": "true",
        },
    )
    assert response.status_code == 200, response.text
    _ = await client.post("/manage/logout")


@pytest.mark.asyncio
async def test_homepage_has_title_description_and_structured_data():
    async with mcp_client() as client:
        await _seed(client)
        page = (await client.get("/")).text

    assert "<title>Alex Jansen – Solution Architect</title>" in page
    assert '<meta name="description" content="Innovative IT Architect who' in page
    assert f'<link rel="canonical" href="{BASE}/">' in page
    assert '<meta property="og:type" content="profile">' in page
    assert "<h1>Alex Jansen</h1>" in page
    assert 'href="/profile"' in page

    match = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', page, re.DOTALL
    )
    assert match
    data = cast(list[dict[str, object]], json.loads(match.group(1)))
    person = cast(dict[str, object], data[0]["mainEntity"])
    assert data[0]["@type"] == "ProfilePage"
    assert person["name"] == "Alex Jansen"
    assert person["alternateName"] == "Tibor"  # the default display name
    assert person["jobTitle"] == "Solution Architect"
    assert person["sameAs"] == [
        "https://github.com/alexj",
        "https://www.linkedin.com/in/alexjansen",
    ]
    assert not PHONE.search(page)
    assert "alex@example.com" not in page


@pytest.mark.asyncio
async def test_profile_page_and_files_leave_out_contact_details():
    async with mcp_client() as client:
        await _seed(client, seo_description="Architect in </script> Deventer.")
        html = await client.get("/profile")
        markdown = await client.get("/profile.md")
        llms = await client.get("/llms.txt")
        llms_full = await client.get("/llms-full.txt")

    assert html.status_code == 200
    assert "Professional Summary" in html.text
    assert 'rel="me noopener"' in html.text
    # A description cannot end the JSON-LD script early
    assert "Architect in <\\/script> Deventer." in html.text

    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("# Alex Jansen\n\n**Solution Architect**")
    assert "## **Experience**" in markdown.text
    assert llms_full.text == markdown.text

    assert llms.text.startswith("# Alex Jansen\n\n> Architect in </script> Deventer.")
    assert f"{BASE}/mcp/public" in llms.text
    assert f"[Full profile (Markdown)]({BASE}/profile.md)" in llms.text

    for response in (html, markdown, llms):
        assert "alex@example.com" not in response.text
        assert not PHONE.search(response.text)


@pytest.mark.asyncio
async def test_robots_and_sitemap():
    async with mcp_client() as client:
        robots = await client.get("/robots.txt")
        sitemap = await client.get("/sitemap.xml")
    assert robots.status_code == 200
    assert "User-agent: *\nAllow: /" in robots.text
    assert "Disallow: /manage" in robots.text
    assert "Sitemap: http://localhost:3005/sitemap.xml" in robots.text

    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "<loc>http://localhost:3005/</loc>" in sitemap.text
    assert "<loc>http://localhost:3005/profile</loc>" in sitemap.text


@pytest.mark.asyncio
async def test_admin_pages_are_not_indexed():
    async with mcp_client() as client:
        page = await client.get("/manage")
    assert '<meta name="robots" content="noindex, nofollow">' in page.text
    assert 'rel="canonical"' not in page.text


async def _public_rpc(client: AsyncClient, method: str, params: dict[str, object]):
    return await client.post(
        "/mcp/public",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


async def _public_tool(client: AsyncClient, name: str, **arguments: object) -> object:
    response = await _public_rpc(
        client, "tools/call", {"name": name, "arguments": arguments}
    )
    assert response.status_code == 200, response.text
    result = cast(dict[str, object], json_body(response)["result"])
    assert not result.get("isError"), result
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        fields = cast(dict[str, object], structured)
        return fields.get("result", fields)
    return cast(list[dict[str, object]], result["content"])[0]["text"]


@pytest.mark.asyncio
async def test_public_mcp_needs_no_login_and_cannot_write():
    async with mcp_client() as client:
        await _seed(client)
        listed = await _public_rpc(client, "tools/list", {})
        assert listed.status_code == 200, listed.text
        tools = cast(dict[str, list[dict[str, str]]], json_body(listed)["result"])
        assert {t["name"] for t in tools["tools"]} == {"get_profile", "ask_assistant"}

        profile = cast(dict[str, object], await _public_tool(client, "get_profile"))
        assert profile["name"] == "Alex Jansen"
        assert profile["headline"] == "Solution Architect"
        assert profile["website"] == f"{BASE}/"
        text = cast(str, profile["profile_markdown"])
        assert "## **Experience**" in text
        assert "alex@example.com" not in text
        assert not PHONE.search(text)

        # The owner's server still needs a token
        owner = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert owner.status_code == 401


@pytest.mark.asyncio
async def test_ask_assistant_answers_from_the_public_profile_and_is_rate_limited():
    ask = AsyncMock(return_value="Yes, Alex has run Kubernetes in production.")
    with patch("app.public_mcp.MistralService.ask_mistral", ask):
        async with mcp_client() as client:
            await _seed(client)
            answer = await _public_tool(
                client, "ask_assistant", question="Does Alex know Kubernetes?"
            )
            assert answer == "Yes, Alex has run Kubernetes in production."

            assert ask.await_args is not None
            messages = cast(list[ChatMessageData], ask.await_args.args[0])
            system = messages[0].content or ""
            assert "Alex Jansen" in system
            assert "## **Experience**" in system
            assert "alex@example.com" not in system
            assert not PHONE.search(system)

            # The owner sees the question among the conversations
            await login(client)
            conversations = await client.get("/manage")
            assert "AI agent (MCP)" in conversations.text

            for _ in range(9):
                _ = await _public_tool(client, "ask_assistant", question="Hi?")
            limited = await _public_tool(client, "ask_assistant", question="Hi?")
            assert "Too many questions" in cast(str, limited)
            assert ask.await_count == 10


def test_migration_adds_public_columns_to_an_existing_database(tmp_path: Path):
    db_path = tmp_path / "existing.db"
    env = os.environ.copy()
    env["SQLITE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    def alembic(*args: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr

    alembic("upgrade", "7b2e4d9f1a6c")
    with sqlite3.connect(db_path) as db:
        _ = db.execute(
            "CREATE TABLE sitesettings (id INTEGER PRIMARY KEY, owner_name VARCHAR)"
        )
        _ = db.execute("INSERT INTO sitesettings VALUES (1, 'Alex')")
    alembic("upgrade", "head")

    with sqlite3.connect(db_path) as db:
        row = cast(
            tuple[str, str, int],
            db.execute(
                "SELECT owner_name, full_name, hide_public_contact FROM sitesettings"
            ).fetchone(),
        )
    assert row == ("Alex", "", 1)


def test_profile_markdown_round_trips_through_editorjs():
    # The stored profile is Editor.js; the public pages read it back as Markdown
    assert "## **Experience**" in editorjs_to_markdown(markdown_to_editorjs(PROFILE))
