import asyncio
from sqlalchemy import update
from app.database import async_session_factory
from app.models.domain import Domain

async def update_regimen_feed():
    async with async_session_factory() as session:
        # 将养生科普的 RSS 源更新为存活良好的少数派源，确保拉取顺畅
        await session.execute(
            update(Domain)
            .where(Domain.id == "health_regimen")
            .values(rss_feed_urls=["https://sspai.com/feed"])
        )
        await session.commit()
        print("Successfully updated 'health_regimen' RSS feed to Sspai feed!")

if __name__ == "__main__":
    asyncio.run(update_regimen_feed())
