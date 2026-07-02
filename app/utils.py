from app.schemas import TakeoverControlsContext
import os
import time
from functools import cache, lru_cache
from pydantic import BaseModel
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from app.services import ContextStore
from app.config import settings

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


def render_template(
    request: Request,
    name: str,
    context_store: ContextStore,
    context: BaseModel | None = None,
):
    template_context = {}
    if context is not None:
        template_context = context.model_dump()
        template_context = context.model_dump()
    template_context["request"] = request
    colors = context_store.get_colors()
    template_context["colors"] = colors.model_dump()
    template_context["contrast_colors"] = {
        f"{k}_contrast": get_contrast_color(str(v)) for k, v in colors.model_dump().items()
    }
    template_context["has_avatar"] = context_store.has_avatar()
    template_context["app_version"] = app_version
    template_context["owner_name"] = context_store.get_owner_name()
    template_context["owner_pronouns"] = context_store.get_owner_pronouns()
    template_context["recaptcha_client_side_key"] = settings.recaptcha_client_side_key
    return templates.TemplateResponse(
        request=request, name=name, context=template_context
    )


def render_template_to_string(
    name: str,
    context: BaseModel | None = None,
) -> str:
    """Renders a jinja template to a string without needing a Request object."""
    template_context = {}
    if context is not None:
        template_context = context.model_dump()
        template_context = context.model_dump()
    return templates.get_template(name).render(template_context)


def get_takeover_oob_html(session_id: str, is_taken_over: bool, owner_name: str) -> str:
    return render_template_to_string(
        "fragments/takeover_controls.html",
        TakeoverControlsContext(
            session_id=session_id,
            is_taken_over=is_taken_over,
            owner_name=owner_name,
        ),
    )
