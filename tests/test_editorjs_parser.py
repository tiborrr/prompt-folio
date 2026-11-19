import json

from app.editorjs_parser import editorjs_to_markdown


def _doc(*blocks: dict[str, object]) -> str:
    return json.dumps({"blocks": list(blocks)})


def test_legacy_list_items_are_strings():
    doc = _doc(
        {"type": "list", "data": {"style": "unordered", "items": ["a", "<b>b</b>"]}}
    )
    assert editorjs_to_markdown(doc) == "- a\n- **b**"


def test_list_v2_nested_items():
    doc = _doc(
        {
            "type": "list",
            "data": {
                "style": "ordered",
                "meta": {},
                "items": [
                    {
                        "content": "first",
                        "meta": {},
                        "items": [{"content": "child", "meta": {}, "items": []}],
                    },
                    {"content": "second", "meta": {}, "items": []},
                ],
            },
        }
    )
    assert editorjs_to_markdown(doc) == "1. first\n  1. child\n2. second"


def test_list_v2_checklist():
    doc = _doc(
        {
            "type": "list",
            "data": {
                "style": "checklist",
                "meta": {},
                "items": [
                    {"content": "done", "meta": {"checked": True}, "items": []},
                    {"content": "todo", "meta": {"checked": False}, "items": []},
                ],
            },
        }
    )
    assert editorjs_to_markdown(doc) == "- [x] done\n- [ ] todo"


def test_plain_text_is_returned_unchanged():
    assert editorjs_to_markdown("just text") == "just text"
