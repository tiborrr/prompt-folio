"""The public face of the profile, for search engines and AI agents.

Everything here is derived from the stored profile and the site settings: the
owner's full name, headline and description, the links that identify them
(LinkedIn, GitHub, ...), the profile as Markdown with contact details left out,
and the structured data (schema.org JSON-LD), llms.txt and sitemap built from it.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.config import Settings
from app.editorjs_parser import editorjs_to_markdown
from app.models import ProfileRevision, SiteSettings

DESCRIPTION_MAX_CHARS = 160

_OUTER_FENCE = re.compile(r"^```(?:markdown|md)?[ \t]*\n(.*)\n```[ \t]*$", re.DOTALL)


def profile_markdown(context: str) -> str:
    """The stored profile as Markdown. A profile generated from uploads can be
    wrapped in one ```markdown fence as a whole; unwrap it so its headings count
    as sections."""
    markdown = editorjs_to_markdown(context).strip()
    match = _OUTER_FENCE.match(markdown)
    if match and "\n```" not in match.group(1):
        return match.group(1).strip()
    return markdown


# --- Contact details -------------------------------------------------------

_CONTACT_LINK = re.compile(r"\[[^\]]*\]\(\s*(?:mailto|tel):[^)]*\)", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A phone number: an optional +, then at least 9 digits with spaces, dots,
# dashes or brackets between them. Year ranges ("2010 – 2015") use an en dash
# and have too few digits, so they do not match.
_PHONE = re.compile(r"\+?\(?\d(?:[\s().-]{0,2}\d){8,}")
_HAS_WORD = re.compile(r"[^\W_]")


def _remove_contact(text: str) -> str:
    text = _CONTACT_LINK.sub("", text)
    text = _EMAIL.sub("", text)
    return _PHONE.sub("", text)


def redact_contact(markdown: str) -> str:
    """Leave email addresses and phone numbers out of the profile.

    Lines like "Deventer | +31 6 ... | me@example.com | [LinkedIn](...)" keep
    their other parts; a part or line that held only contact details (with an
    icon or bold markers around it) is dropped as a whole.
    """
    lines: list[str] = []
    for line in markdown.splitlines():
        cleaned = _remove_contact(line)
        if cleaned == line:
            lines.append(line)
            continue
        parts = [p.strip() for p in line.split("|")]
        kept = [p for p in parts if _HAS_WORD.search(_remove_contact(p))]
        kept = [p for p in kept if _remove_contact(p) == p]
        if kept:
            lines.append(" | ".join(kept))
    return "\n".join(lines)


# --- Reading the profile ---------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]*)\)")
_BARE_WWW_LINK = re.compile(r"\]\((www\.[^)\s]+)\)")
_URL = re.compile(r"https?://[^\s)\]>\"']+|www\.[^\s)\]>\"']+")
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️‍]", re.UNICODE)


def fix_links(markdown: str) -> str:
    """Links written as "www.example.com" would point to a page on this site;
    give them https://."""
    return _BARE_WWW_LINK.sub(r"](https://\1)", markdown)


def plain_text(markdown: str) -> str:
    """Markdown without its markup: link texts, no bold/italic markers, no icons."""
    text = _MD_LINK.sub(r"\1", markdown)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_`]+", "", text)
    text = _EMOJI.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_heading(markdown: str, level: int) -> str:
    pattern = re.compile(rf"^{'#' * level}\s+(.+?)\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    return plain_text(match.group(1)) if match else ""


def name_from_profile(markdown: str) -> str:
    """The profile's "# Name" heading, if it starts with one."""
    return _first_heading(markdown, 1)


def headline_from_profile(markdown: str) -> str:
    """The first line under the "# Name" heading when it is a short tagline,
    such as "**IT Architect & Full Stack Developer**"."""
    match = re.search(r"^#\s+.+?$\n+(.+?)$", markdown, re.MULTILINE)
    if not match:
        return ""
    line = match.group(1).strip()
    if line.startswith(("#", "-", "---")) or "|" in line:
        return ""
    text = plain_text(line)
    return text if 0 < len(text) <= 100 else ""


def strip_title(markdown: str) -> str:
    """Leave out a leading "# Name" heading and the tagline right under it."""
    if not markdown.startswith("# "):
        return markdown
    rest = markdown.split("\n", 1)[1] if "\n" in markdown else ""
    if headline_from_profile(markdown):
        rest = rest.lstrip("\n")
        rest = rest.split("\n", 1)[1] if "\n" in rest else ""
    return rest.strip()


def _paragraphs(markdown: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", markdown)
    paragraphs: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block or block.startswith(("#", "-", "*  ", "---", "```", "|", ">")):
            continue
        text = plain_text(block)
        # Skip taglines and contact lines; a summary is a sentence or more
        if len(text) >= 60 and "." in text:
            paragraphs.append(text)
    return paragraphs


def summary_from_profile(markdown: str) -> str:
    """The first paragraph of a "Summary" / "About" section, else the first
    real paragraph of the profile."""
    match = re.search(
        r"^#{2,3}\s+[^\n]*(?:summary|about|profile|introduction|samenvatting|over mij)[^\n]*$"
        + r"(.*?)(?=^#{1,3}\s|\Z)",
        markdown,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if match:
        paragraphs = _paragraphs(match.group(1))
        if paragraphs:
            return paragraphs[0]
    paragraphs = _paragraphs(markdown)
    return paragraphs[0] if paragraphs else ""


def shorten(text: str, limit: int = DESCRIPTION_MAX_CHARS) -> str:
    """Cut text at a word boundary so it fits in ``limit`` characters."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:–-")
    return cut + "…"


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,;")
    if url.startswith("www."):
        url = "https://" + url
    return url


# Profiles that say who someone is (schema.org sameAs); other links in the
# profile, such as projects someone contributed to, are not about the person.
_IDENTITY_HOSTS = re.compile(
    r"^https?://(?:[\w-]+\.)*(?:linkedin\.com/in/|github\.com/[^/]+/?$|gitlab\.com/[^/]+/?$"
    + r"|x\.com/|twitter\.com/|bsky\.app/profile/|mastodon\.[\w.]+/@|medium\.com/@"
    + r"|dev\.to/|stackoverflow\.com/users/|youtube\.com/@|instagram\.com/"
    + r"|orcid\.org/|scholar\.google\.)",
    re.IGNORECASE,
)


def identity_links(markdown: str) -> list[str]:
    """Links in the profile to the owner's own profiles elsewhere."""
    links: list[str] = []
    for match in _URL.finditer(markdown):
        url = _normalize_url(match.group(0))
        if _IDENTITY_HOSTS.match(url) and url not in links:
            links.append(url)
    return links


# --- The public profile ----------------------------------------------------


@dataclass(frozen=True)
class PublicProfile:
    name: str
    short_name: str
    headline: str
    description: str
    markdown: str
    links: list[str] = field(default_factory=list)
    meeting_url: str = ""
    base_url: str = ""
    updated_at: datetime | None = None
    has_avatar: bool = False

    @property
    def title(self) -> str:
        return f"{self.name} – {self.headline}" if self.headline else self.name

    @property
    def body_markdown(self) -> str:
        """The profile without its "# Name" heading and tagline, which the
        page header already shows."""
        return strip_title(self.markdown)

    @property
    def image_url(self) -> str:
        return f"{self.base_url}/avatar" if self.has_avatar else ""


def build_public_profile(
    site: SiteSettings, base_url: str, updated_at: datetime | None = None
) -> PublicProfile:
    markdown = fix_links(profile_markdown(site.context)) if site.context else ""
    if site.hide_public_contact:
        markdown = redact_contact(markdown)

    name = site.full_name.strip() or name_from_profile(markdown) or site.owner_name
    headline = site.headline.strip() or headline_from_profile(markdown)
    description = site.seo_description.strip() or summary_from_profile(markdown)
    if not description:
        description = f"{name}{', ' + headline if headline else ''}. Ask my AI assistant about my experience and projects."

    links: list[str] = []
    configured = [u for u in re.split(r"[\s,]+", site.profile_links) if u.strip()]
    for url in [_normalize_url(u) for u in configured] + identity_links(markdown):
        if url.startswith("https://") and url not in links:
            links.append(url)

    return PublicProfile(
        name=name,
        short_name=site.owner_name,
        headline=headline,
        description=description,
        markdown=markdown,
        links=links,
        meeting_url=site.meeting_url,
        base_url=base_url,
        updated_at=updated_at,
        has_avatar=site.avatar is not None,
    )


async def load_public_profile(db: AsyncSession, config: Settings) -> PublicProfile:
    site = await db.get(SiteSettings, 1)
    if site is None:
        site = SiteSettings(id=1)
    result = await db.execute(
        select(ProfileRevision.created_at)
        .order_by(col(ProfileRevision.created_at).desc())
        .limit(1)
    )
    updated_at = result.scalar_one_or_none()
    return build_public_profile(site, config.base_url, updated_at)


# --- Machine-readable forms ------------------------------------------------


def json_ld(profile: PublicProfile, page_url: str) -> str:
    """schema.org ProfilePage + Person, for Google's profile results and
    knowledge panels. Safe to put in a <script> element."""
    person: dict[str, object] = {
        "@type": "Person",
        "@id": f"{profile.base_url}/#person",
        "name": profile.name,
        "url": f"{profile.base_url}/",
        "description": profile.description,
    }
    if profile.short_name and profile.short_name != profile.name:
        person["alternateName"] = profile.short_name
    if profile.headline:
        person["jobTitle"] = profile.headline
    if profile.image_url:
        person["image"] = profile.image_url
    if profile.links:
        person["sameAs"] = profile.links
    page: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "ProfilePage",
        "@id": page_url,
        "url": page_url,
        "name": profile.title,
        "mainEntity": person,
    }
    if profile.updated_at:
        page["dateModified"] = profile.updated_at.isoformat()
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": f"{profile.base_url}/#website",
        "url": f"{profile.base_url}/",
        "name": profile.name,
    }
    data = json.dumps([page, website], ensure_ascii=False, indent=2)
    # "</script>" inside a string would end the element early
    return data.replace("</", "<\\/")


def profile_document(profile: PublicProfile) -> str:
    """The profile as one Markdown document, for /profile.md and llms-full.txt."""
    lines = [f"# {profile.name}", ""]
    if profile.headline:
        lines += [f"**{profile.headline}**", ""]
    lines += [
        f"Website: {profile.base_url}/",
        f"Chat with {profile.short_name}'s AI assistant: {profile.base_url}/",
    ]
    if profile.meeting_url:
        lines.append(f"Book a meeting: {profile.meeting_url}")
    for url in profile.links:
        lines.append(f"Profile: {url}")
    # The profile usually starts with the same name and tagline; do not repeat them
    return "\n".join(lines) + "\n\n---\n\n" + profile.body_markdown + "\n"


def llms_txt(profile: PublicProfile) -> str:
    """/llms.txt (https://llmstxt.org): where an AI agent finds what about the owner."""
    base = profile.base_url
    lines = [
        f"# {profile.name}",
        "",
        f"> {profile.description}",
        "",
    ]
    if profile.headline:
        lines += [
            f"{profile.name} is {_article(profile.headline)} {profile.headline}.",
            "",
        ]
    lines += [
        f"This is {profile.name}'s official website. Visitors can chat with an AI "
        + f"assistant that answers questions about {profile.short_name}'s experience, "
        + "skills and projects, based on the profile linked below.",
        "",
        "## Profile",
        "",
        f"- [Full profile (Markdown)]({base}/profile.md): CV, experience, skills, projects and education",
        f"- [Full profile (HTML)]({base}/profile): the same profile as a web page",
        "",
        "## For AI agents",
        "",
        f"- [MCP server]({base}/mcp/public): public, read-only Model Context Protocol "
        + "endpoint (streamable HTTP, no login). Tools: `get_profile` returns the "
        + "profile as Markdown; `ask_assistant` asks the AI assistant a question "
        + "(rate limited).",
        f"- [Chat]({base}/): talk to the AI assistant in a browser",
    ]
    contact: list[str] = []
    if profile.meeting_url:
        contact.append(f"- [Book a meeting]({profile.meeting_url})")
    contact += [f"- [{_link_label(url)}]({url})" for url in profile.links]
    if contact:
        lines += ["", "## Contact and other profiles", "", *contact]
    lines += [
        "",
        "## Optional",
        "",
        f"- [Full profile as one file]({base}/llms-full.txt)",
    ]
    return "\n".join(lines) + "\n"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _link_label(url: str) -> str:
    host = re.sub(r"^https?://(?:www\.)?", "", url).split("/")[0]
    labels = {
        "linkedin.com": "LinkedIn",
        "github.com": "GitHub",
        "gitlab.com": "GitLab",
        "x.com": "X",
        "twitter.com": "X",
        "bsky.app": "Bluesky",
    }
    return labels.get(host, host)


def sitemap_xml(profile: PublicProfile) -> str:
    lastmod = (
        f"<lastmod>{profile.updated_at.date().isoformat()}</lastmod>"
        if profile.updated_at
        else ""
    )
    urls = "".join(
        f"<url><loc>{xml_escape(profile.base_url + path)}</loc>{lastmod}</url>"
        for path in ("/", "/profile")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + urls
        + "</urlset>\n"
    )


def robots_txt(base_url: str) -> str:
    """Everyone, AI crawlers included, may read the public pages; the admin,
    OAuth and chat plumbing stay out of search results."""
    private = ["/manage", "/oauth/", "/authorize", "/token", "/register", "/revoke"]
    private += ["/stream/", "/chat", "/clear", "/takeover_request", "/revert_takeover"]
    lines = ["User-agent: *", "Allow: /", *[f"Disallow: {p}" for p in private]]
    lines += ["", f"Sitemap: {base_url}/sitemap.xml", ""]
    return "\n".join(lines)
