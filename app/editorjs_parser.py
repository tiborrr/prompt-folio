import json
import re
from html import unescape
from typing import cast


def _as_dict(value: object) -> dict[str, object]:
    """Return a JSON object as a dict, or an empty dict for anything else."""
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    """Return a JSON array as a list, or an empty list for anything else."""
    return cast(list[object], value) if isinstance(value, list) else []


def parse_html_inline(html: str) -> str:
    if not html:
        return ""
    md = html
    # Match <b> and <strong>
    md = re.sub(r"<b\b[^>]*>(.*?)</b>", r"**\1**", md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(
        r"<strong\b[^>]*>(.*?)</strong>", r"**\1**", md, flags=re.IGNORECASE | re.DOTALL
    )
    # Match <i> and <em>
    md = re.sub(r"<i\b[^>]*>(.*?)</i>", r"*\1*", md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(r"<em\b[^>]*>(.*?)</em>", r"*\1*", md, flags=re.IGNORECASE | re.DOTALL)
    # Match <a>
    md = re.sub(
        r'<a[^>]*href="(.*?)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        md,
        flags=re.IGNORECASE | re.DOTALL,
    )
    md = re.sub(r"&nbsp;", " ", md, flags=re.IGNORECASE)
    # Convert <br> to newline
    md = re.sub(r"<br\s*/?>", "\n", md, flags=re.IGNORECASE)
    # Editor.js stores text as HTML, so "&" arrives as "&amp;"
    return unescape(md)


def _list_to_markdown(items: list[object], ordered: bool, depth: int = 0) -> str:
    """Render list items: plain strings (List 1.x) or nested objects (List 2.x)."""
    md = ""
    indent = "  " * depth
    for index, item in enumerate(items, start=1):
        marker = f"{index}." if ordered else "-"
        entry = _as_dict(item)
        if entry or item == {}:
            content = str(entry.get("content", ""))
            meta = _as_dict(entry.get("meta"))
            if "checked" in meta:
                marker = f"- [{'x' if meta['checked'] else ' '}]"
            md += f"{indent}{marker} {parse_html_inline(content)}\n"
            children = _as_list(entry.get("items"))
            if children:
                md += _list_to_markdown(children, ordered, depth + 1)
        else:
            md += f"{indent}{marker} {parse_html_inline(str(item))}\n"
    return md


def editorjs_to_markdown(json_str: str) -> str:
    if not json_str:
        return ""

    try:
        data = cast(object, json.loads(json_str))
    except json.JSONDecodeError:
        # If it's already markdown or invalid JSON, return as is
        return json_str

    document = _as_dict(data)
    if "blocks" not in document:
        return json_str

    md = ""
    for raw_block in _as_list(document.get("blocks")):
        block = _as_dict(raw_block)
        block_type = block.get("type")
        block_data = _as_dict(block.get("data"))

        if block_type == "header":
            level = block_data.get("level", 1)
            level = level if isinstance(level, int) else 1
            text = parse_html_inline(str(block_data.get("text", "")))
            md += f"{'#' * level} {text}\n\n"

        elif block_type == "paragraph":
            text = parse_html_inline(str(block_data.get("text", "")))
            md += f"{text}\n\n"

        elif block_type == "list":
            items = _as_list(block_data.get("items"))
            ordered = block_data.get("style") == "ordered"
            md += _list_to_markdown(items, ordered) + "\n"

        elif block_type == "code":
            code = block_data.get("code", "")
            lang = block_data.get("lang", "")
            md += f"```{lang}\n{code}\n```\n\n"

        elif block_type == "delimiter":
            md += "---\n\n"

    return md.strip()
