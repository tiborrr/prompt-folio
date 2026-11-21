"""Markdown -> Editor.js conversion, the reverse of ``app.editorjs_parser``.

The MCP server lets Claude read the profile as Markdown and write Markdown back.
The /manage context editor works with Editor.js JSON, so writes are converted
into the same block types the editor offers (header, paragraph, list, code,
delimiter), and the profile stays editable by hand afterwards.
"""

import html
import json
import re
import time

EDITORJS_VERSION = "2.31.7"

_HEADER_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_DELIMITER_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_CHECK_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*```\s*([\w+-]*)\s*$")


def markdown_inline_to_html(text: str) -> str:
    """Escape HTML, then turn **bold**, *italic* and [links](url) into Editor.js inline HTML."""
    out = html.escape(text, quote=False)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        out,
    )
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__(.+?)__", r"<b>\1</b>", out)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", out)
    out = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", out)
    return out.replace("\n", "<br>")


def _parse_list(lines: list[str], start: int) -> tuple[dict[str, object], int]:
    """Parse consecutive list lines into one Editor.js List 2.x block."""
    first = _LIST_RE.match(lines[start])
    assert first is not None
    ordered = first.group(2)[0].isdigit()
    style = "ordered" if ordered else "unordered"
    if not ordered and _CHECK_RE.match(first.group(3)):
        style = "checklist"

    root: list[dict[str, object]] = []
    # Stack of (indent, items list to append to)
    stack: list[tuple[int, list[dict[str, object]]]] = [(len(first.group(1)), root)]
    last_item: dict[str, object] | None = None
    i = start
    while i < len(lines):
        m = _LIST_RE.match(lines[i])
        if not m:
            break
        indent = len(m.group(1))
        content = m.group(3)
        meta: dict[str, object] = {}
        if style == "checklist":
            check = _CHECK_RE.match(content)
            if check:
                meta["checked"] = check.group(1).lower() == "x"
                content = check.group(2)
            else:
                meta["checked"] = False

        if indent > stack[-1][0] and last_item is not None:
            children = last_item["items"]
            assert isinstance(children, list)
            stack.append((indent, children))  # pyright: ignore[reportUnknownArgumentType]
        else:
            while len(stack) > 1 and indent < stack[-1][0]:
                _ = stack.pop()

        item: dict[str, object] = {
            "content": markdown_inline_to_html(content),
            "meta": meta,
            "items": [],
        }
        stack[-1][1].append(item)
        last_item = item
        i += 1

    return {"type": "list", "data": {"style": style, "meta": {}, "items": root}}, i


def markdown_to_editorjs(markdown: str) -> str:
    """Convert Markdown to an Editor.js JSON document string."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks: list[dict[str, object]] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = "\n".join(line.strip() for line in paragraph)
            blocks.append(
                {"type": "paragraph", "data": {"text": markdown_inline_to_html(text)}}
            )
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            flush_paragraph()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            data: dict[str, object] = {"code": "\n".join(code_lines)}
            if fence.group(1):
                data["lang"] = fence.group(1)
            blocks.append({"type": "code", "data": data})
            continue

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        header = _HEADER_RE.match(line)
        if header:
            flush_paragraph()
            blocks.append(
                {
                    "type": "header",
                    "data": {
                        "text": markdown_inline_to_html(header.group(2)),
                        "level": len(header.group(1)),
                    },
                }
            )
            i += 1
            continue

        if _DELIMITER_RE.match(line):
            flush_paragraph()
            blocks.append({"type": "delimiter", "data": {}})
            i += 1
            continue

        if _LIST_RE.match(line) and not paragraph:
            block, i = _parse_list(lines, i)
            blocks.append(block)
            continue

        paragraph.append(line)
        i += 1

    flush_paragraph()
    return json.dumps(
        {
            "time": int(time.time() * 1000),
            "blocks": blocks,
            "version": EDITORJS_VERSION,
        },
        ensure_ascii=False,
    )


def _heading_title(line: str) -> tuple[int, str] | None:
    m = _HEADER_RE.match(line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def _normalise(title: str) -> str:
    return re.sub(r"[*_`]", "", title).strip().casefold()


def list_sections(markdown: str) -> list[str]:
    """The headings in a Markdown document, as written (e.g. ``## Experience``)."""
    titles: list[str] = []
    in_code = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_code = not in_code
            continue
        if not in_code and _heading_title(line):
            titles.append(line.strip())
    return titles


def replace_section(markdown: str, heading: str, body: str) -> tuple[str, bool]:
    """Replace the body under ``heading`` (up to the next heading of the same or a
    higher level). Returns the new document and whether the heading existed; a
    missing heading is appended as a new ``##`` section."""
    wanted = _normalise(heading.lstrip("#"))
    lines = markdown.split("\n")
    in_code = False
    start: int | None = None
    level = 0
    end = len(lines)
    for idx, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        found = _heading_title(line)
        if not found:
            continue
        if start is None:
            if _normalise(found[1]) == wanted:
                start, level = idx, found[0]
        elif found[0] <= level:
            end = idx
            break

    body = body.strip("\n")
    if start is None:
        title = heading.strip()
        if not title.startswith("#"):
            title = f"## {title}"
        new = markdown.rstrip("\n") + f"\n\n{title}\n\n{body}\n"
        return new.lstrip("\n"), False

    new_lines = [*lines[: start + 1], "", body, "", *lines[end:]]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(new_lines)).strip("\n") + "\n", True
