import asyncio
from datetime import datetime
from app.database import async_session_factory
from app.models.domain import Domain

async def insert():
    async with async_session_factory() as session:
        # 检查是否已存在
        existing = await session.get(Domain, "health_regimen")
        if existing:
            print("Domain 'health_regimen' already exists. Skipping.")
            return

        d = Domain(
            id="health_regimen",
            label="养生科普",
            description="专注于中医养生、慢性病调理、科学膳食与日常健康防病科普。",
            folo_keywords=["养生", "健康科普", "中医调理", "养胃", "防癌", "饮食误区"],
            search_keywords=["科学养生", "养生误区", "日常饮食禁忌", "高血压调理", "失眠调理"],
            rss_feed_urls=["https://www.guokr.com/rss/"],  # 绑定果壳网的顶级健康与食品科普源，免登录直连
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(d)
        await session.commit()
        print("Successfully inserted the '养生科普' domain into the database!")

if __name__ == "__main__":
    asyncio.run(insert())
