import asyncio
import re
import html
import json
from sqlalchemy import select
from app.database import async_session_factory
from app.models.article import Article

def clean_html_to_json(html_text: str) -> str:
    if not html_text:
        return ""
    text = re.sub(r"<[^>]+>", "", html_text)
    text = html.unescape(text)
    return text.strip()

async def test():
    async with async_session_factory() as session:
        article = await session.get(Article, "092fb423-7f12-4b0f-9487-fe32f43c75a0")
        if article:
            cleaned = clean_html_to_json(article.body)
            try:
                # 尝试开启 strict=False 宽松模式
                data = json.loads(cleaned, strict=False)
                print("Perfect! json.loads(strict=False) succeeded!")
                print("Parsed Title:", data.get("title"))
            except Exception as e:
                print("Loads Error details:", str(e))
        else:
            print("Article not found!")

if __name__ == "__main__":
    asyncio.run(test())
