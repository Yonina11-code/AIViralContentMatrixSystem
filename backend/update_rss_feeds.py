import asyncio
from sqlalchemy import update
from app.database import async_session_factory
from app.models.domain import Domain

async def update_feeds():
    async with async_session_factory() as session:
        # 1. 家居收纳与清洁 & 家电妙用与数码避坑 -> 少数派（包含海量生活/收纳/小家电优质好文，免密直连）
        await session.execute(
            update(Domain)
            .where(Domain.id.in_(["home_hacks", "smart_living"]))
            .values(rss_feed_urls=["https://sspai.com/feed"])
        )
        
        # 2. 菜场智慧与食品安全 & 防骗与家庭急救 -> 果壳网科学人（包含海量食品科普、谣言粉碎与防骗自救，免密直连）
        await session.execute(
            update(Domain)
            .where(Domain.id.in_(["food_safety", "safety_first"]))
            .values(rss_feed_urls=["https://www.guokr.com/rss/"])
        )
        
        await session.commit()
        print("Successfully injected free, unauthenticated RSS feeds into your 4 new domains!")

if __name__ == "__main__":
    asyncio.run(update_feeds())
