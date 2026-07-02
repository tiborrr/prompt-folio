import os
import time
from typing import Any
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


def markdown_filter(text):
    return md.render(text)


templates.env.filters["markdown"] = markdown_filter

# Generate a unique cache-busting string per application restart
app_version = str(int(time.time()))


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
    context: dict[str, Any] | BaseModel | None = None,
):
    if context is None:
        context = {}
    elif isinstance(context, BaseModel):
        context = context.model_dump()
    context["request"] = request
    colors = context_store.get_colors()
    context["colors"] = colors.model_dump()
    context["contrast_colors"] = {
        f"{k}_contrast": get_contrast_color(v) for k, v in colors.model_dump().items()
    }
    context["has_avatar"] = context_store.has_avatar()
    context["app_version"] = app_version
    context["owner_name"] = context_store.get_owner_name()
    context["owner_pronouns"] = context_store.get_owner_pronouns()
    context["recaptcha_client_side_key"] = settings.recaptcha_client_side_key
    return templates.TemplateResponse(request=request, name=name, context=context)


def render_template_to_string(
    name: str,
    context: dict[str, Any] | BaseModel | None = None,
) -> str:
    """Renders a jinja template to a string without needing a Request object."""
    if context is None:
        context = {}
    elif isinstance(context, BaseModel):
        context = context.model_dump()
    return templates.get_template(name).render(context)


def get_takeover_oob_html(session_id: str, is_taken_over: bool, owner_name: str) -> str:
    return render_template_to_string(
        "fragments/takeover_controls.html",
        {
            "session_id": session_id,
            "is_taken_over": is_taken_over,
            "owner_name": owner_name,
        },
    )
