from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from app.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug, pool_size=10, max_overflow=20)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """建表 + 初始数据播种 + 枚举迁移"""
    from app.models.domain import Domain

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 迁移：为 contentsource 枚举添加 FOLO（独立事务，不影响上面的建表）
    # ContentItem.source 现为 String(50)，新库无此枚举类型，需先检查再迁移
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contentsource')")
            )
            if result.scalar():
                await conn.execute(text("ALTER TYPE contentsource ADD VALUE IF NOT EXISTS 'FOLO'"))
    except Exception:
        pass

    # 迁移：为 content_items 表添加 used_at 列（如不存在）
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='content_items' AND column_name='used_at'")
            )
            if not result.scalar():
                await conn.execute(text("ALTER TABLE content_items ADD COLUMN used_at TIMESTAMP NULL DEFAULT NULL"))
    except Exception:
        pass

    # 迁移：为 articles 表添加 scheduled_publish_at 列（如不存在）
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='articles' AND column_name='scheduled_publish_at'")
            )
            if not result.scalar():
                await conn.execute(text("ALTER TABLE articles ADD COLUMN scheduled_publish_at TIMESTAMP NULL DEFAULT NULL"))
    except Exception:
        pass

    # 如果 domains 表为空，从 config.py 播种默认领域
    async with async_session_factory() as sess:
        existing = await sess.execute(text("SELECT count(*) FROM domains"))
        if existing.scalar() == 0:
            for key, cfg in settings.domains.items():
                sess.add(Domain(
                    id=key,
                    label=cfg.get("label", key),
                    folo_keywords=cfg.get("folo_keywords", []),
                    search_keywords=cfg.get("search_keywords", []),
                    rss_feed_urls=cfg.get("rss_feed_urls", []),
                ))
            await sess.commit()
