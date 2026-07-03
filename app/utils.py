from app.schemas import TakeoverControlsContext
import time
from functools import cache, lru_cache
from pydantic import BaseModel
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from sqlalchemy.ext.asyncio import AsyncSession
from app.services import ContextStore
from app.config import settings
import os

base_dir = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(base_dir, "templates"))

md = MarkdownIt("commonmark", {"breaks": True, "html": True, "linkify": True}).enable(
    "linkify"
)


@lru_cache(maxsize=128)
def markdown_filter(text: str) -> str:
    return str(md.render(text))


templates.env.filters["markdown"] = markdown_filter

# Generate a unique cache-busting string per application restart
app_version = str(int(time.time()))


@cache
def get_contrast_color(hex_color: str) -> str:
    """Returns #ffffff or #1e1e24 based on relative luminance."""
    if not hex_color or not hex_color.startswith("#") or len(hex_color) not in (4, 7):
        return "#ffffff"
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c + c for c in h)
    try:
        r, g, b = tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    if luminance > 0.5:
        return "#1e1e24"
    else:
        return "#ffffff"


async def render_template(
    request: Request,
    name: str,
    context_store: ContextStore,
    db: AsyncSession,
    context: BaseModel | None = None,
):
    template_context = {}
    if context is not None:
        template_context = context.model_dump()
    template_context["request"] = request
    colors = await context_store.get_colors(db)
    template_context["colors"] = colors.model_dump()
    template_context["contrast_colors"] = {
        f"{k}_contrast": get_contrast_color(str(v)) for k, v in colors.model_dump().items()
    }
    template_context["has_avatar"] = await context_store.has_avatar(db)
    template_context["app_version"] = app_version
    template_context["owner_name"] = await context_store.get_owner_name(db)
    template_context["owner_pronouns"] = await context_store.get_owner_pronouns(db)
    template_context["recaptcha_client_side_key"] = settings.recaptcha_client_side_key
    return templates.TemplateResponse(
        request=request, name=name, context=template_context
    )


async def render_template_to_string(
    name: str,
    context_store: ContextStore,
    db: AsyncSession,
    context: BaseModel | None = None,
) -> str:
    """Renders a jinja template to a string without needing a Request object."""
    template_context = {}
    if context is not None:
        template_context = context.model_dump()
    colors = await context_store.get_colors(db)
    template_context["colors"] = colors.model_dump()
    template_context["contrast_colors"] = {
        f"{k}_contrast": get_contrast_color(str(v)) for k, v in colors.model_dump().items()
    }
    template_context["has_avatar"] = await context_store.has_avatar(db)
    template_context["owner_name"] = await context_store.get_owner_name(db)
    template_context["owner_pronouns"] = await context_store.get_owner_pronouns(db)
    return templates.get_template(name).render(template_context)


async def get_takeover_oob_html(
    session_id: str,
    is_taken_over: bool,
    owner_name: str,
    context_store: ContextStore,
    db: AsyncSession,
) -> str:
    return await render_template_to_string(
        "fragments/takeover_controls.html",
        context_store,
        db,
        TakeoverControlsContext(
            session_id=session_id,
            is_taken_over=is_taken_over,
            owner_name=owner_name,
        ),
    )
