import json
import re

def parse_html_inline(html: str) -> str:
    if not html:
        return ""
    md = html
    # Match <b> and <strong>
    md = re.sub(r'<b\b[^>]*>(.*?)</b>', r'**\1**', md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(r'<strong\b[^>]*>(.*?)</strong>', r'**\1**', md, flags=re.IGNORECASE | re.DOTALL)
    # Match <i> and <em>
    md = re.sub(r'<i\b[^>]*>(.*?)</i>', r'*\1*', md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(r'<em\b[^>]*>(.*?)</em>', r'*\1*', md, flags=re.IGNORECASE | re.DOTALL)
    # Match <a>
    md = re.sub(r'<a[^>]*href="(.*?)"[^>]*>(.*?)</a>', r'[\2](\1)', md, flags=re.IGNORECASE | re.DOTALL)
    md = re.sub(r'&nbsp;', ' ', md, flags=re.IGNORECASE)
    # Convert <br> to newline
    md = re.sub(r'<br\s*/?>', '\n', md, flags=re.IGNORECASE)
    return md

def editorjs_to_markdown(json_str: str) -> str:
    if not json_str:
        return ""
        
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # If it's already markdown or invalid JSON, return as is
        return json_str

    if not isinstance(data, dict) or "blocks" not in data:
        return json_str
        
    md = ""
    for block in data.get("blocks", []):
        block_type = block.get("type")
        block_data = block.get("data", {})
        
        if block_type == "header":
            level = block_data.get("level", 1)
            text = parse_html_inline(block_data.get("text", ""))
            md += f"{'#' * level} {text}\n\n"
            
        elif block_type == "paragraph":
            text = parse_html_inline(block_data.get("text", ""))
            md += f"{text}\n\n"
            
        elif block_type == "list":
            items = block_data.get("items", [])
            for item in items:
                md += f"- {parse_html_inline(item)}\n"
            md += "\n"
            
        elif block_type == "code":
            code = block_data.get("code", "")
            lang = block_data.get("lang", "")
            md += f"```{lang}\n{code}\n```\n\n"
            
        elif block_type == "delimiter":
            md += "---\n\n"

    return md.strip()
