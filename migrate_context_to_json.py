import asyncio
import json
import re
import sys
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.database import get_engine
from app.config import Settings
from app.models import SiteSettings

def parse_markdown_inline(text):
    html = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
    html = re.sub(r'\*(.*?)\*', r'<i>\1</i>', html)
    html = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', html)
    return html

def markdown_to_editorjs(md: str) -> dict:
    blocks = []
    code_blocks = []
    
    def code_replacer(match):
        placeholder = f"___CODE_BLOCK_{len(code_blocks)}___"
        code_blocks.append({"code": match.group(2).rstrip(), "lang": match.group(1).strip()})
        return f"\n\n{placeholder}\n\n"

    md = re.sub(r'```([^\n]*)\n([\s\S]*?)```', code_replacer, md)

    paragraphs = re.split(r'\n\n+', md)
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        
        code_match = re.match(r'^___CODE_BLOCK_(\d+)___$', p)
        if code_match:
            block_data = code_blocks[int(code_match.group(1))]
            blocks.append({"type": "code", "data": {"code": block_data["code"], "lang": block_data["lang"]}})
            continue
            
        if p == '---':
            blocks.append({"type": "delimiter", "data": {}})
            continue
            
        header_match = re.match(r'^(#{1,6})\s+(.*)', p, re.DOTALL)
        if header_match:
            level = len(header_match.group(1))
            text = parse_markdown_inline(header_match.group(2))
            blocks.append({"type": "header", "data": {"text": text, "level": level}})
        elif p.startswith('- '):
            items = [parse_markdown_inline(item.replace('- ', '', 1)) for item in p.split('\n') if item.startswith('- ')]
            if items:
                blocks.append({"type": "list", "data": {"style": "unordered", "items": items}})
        else:
            html_text = parse_markdown_inline(p.replace('\n', '<br>'))
            blocks.append({"type": "paragraph", "data": {"text": html_text}})
            
    return {"time": 1713000000, "blocks": blocks, "version": "2.29.0"}


async def run():
    settings = Settings()
    engine = get_engine(settings.sqlite_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as db:
        result = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
        site = result.scalar_one_or_none()
        if site and site.context:
            if not site.context.strip().startswith('{'):
                print("Converting context to JSON...")
                editor_data = markdown_to_editorjs(site.context)
                site.context = json.dumps(editor_data)
                db.add(site)
                await db.commit()
                print("Done!")
            else:
                print("Already JSON.")
        else:
            print("No context to convert.")
            
if __name__ == "__main__":
    asyncio.run(run())
