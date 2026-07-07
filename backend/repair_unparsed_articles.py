import asyncio
import re
import html
from sqlalchemy import select
from app.database import async_session_factory
from app.models.article import Article, ArticleStatus
from app.llm import parse_llm_json
from app.agents.publisher import PublisherAgent  # 导入 publisher 重新排版

def clean_html_to_json(html_text: str) -> str:
    """剥离 HTML 标签并还原 HTML 实体，恢复出原始 JSON 字符串"""
    if not html_text:
        return ""
    # 1. 替换所有的 HTML 标签
    text = re.sub(r"<[^>]+>", "", html_text)
    # 2. 还原 HTML 实体
    text = html.unescape(text)
    return text.strip()

async def repair():
    publisher_agent = PublisherAgent()
    async with async_session_factory() as session:
        # 查询所有标题为“未解析”的草稿或失败的文章
        query = select(Article).where(Article.title == "未解析")
        rows = (await session.execute(query)).scalars().all()
        
        if not rows:
            print("No unparsed articles found.")
            return

        repaired_count = 0
        for article in rows:
            print(f"Attempting to repair article: {article.id}")
            
            # 首先剥离 HTML 得到原始 JSON 文本
            cleaned_text = clean_html_to_json(article.body)
            
            try:
                # 尝试解析 JSON 源码
                data = parse_llm_json(cleaned_text)
                
                title = data.get("title", "未命名文章").strip()
                raw_body = data.get("body", "").strip()
                summary = data.get("summary", "").strip()
                
                if title and raw_body:
                    # 重新对正文进行排版（因为之前是把 json 整个排版了，现在我们需要对真正的 body 正文进行排版）
                    prepared = publisher_agent.prepare(
                        title=title,
                        body=raw_body,
                        summary=summary
                    )
                    
                    # 重新将解析并排版过的内容应用到文章
                    article.title = prepared["title"]
                    article.body = prepared["body"]
                    article.summary = prepared["summary"]
                    # 更新状态为 DRAFT 草稿状态
                    article.status = ArticleStatus.DRAFT
                    
                    repaired_count += 1
                    print(f"Successfully repaired: {title}")
                else:
                    print(f"Skipping {article.id}: parsed data is incomplete.")
            except Exception as e:
                print(f"Failed to parse body of {article.id}: {e}")
                
        if repaired_count > 0:
            await session.commit()
            print(f"Repaired {repaired_count} articles in total.")
        else:
            print("No articles were successfully repaired.")

if __name__ == "__main__":
    asyncio.run(repair())
