"""Celery 异步任务定义"""

import asyncio

from celery import shared_task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery_app
from app.collectors import RSSCollector, SearchEngineCollector, FoloCollector
from app.config import settings
from app.models.content_item import ContentItem
from app.models.article import Article, ArticleStatus, article_status_db_label
from app.publishers.wechat import WeChatPublisher

# ---------- Celery 专用同步数据库连接 ----------
_sync_db_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_db_url, pool_size=5, max_overflow=10)
_sync_session_factory = sessionmaker(bind=_sync_engine)


def _save_content_items(items) -> int:
    """将采集到的内容批量写入数据库（去重）"""
    saved = 0
    with _sync_session_factory() as session:
        for item in items:
            if item.fingerprint:
                existing = session.execute(
                    text("SELECT id FROM content_items WHERE fingerprint = :fp"),
                    {"fp": item.fingerprint},
                ).first()
                if existing:
                    continue

            ci = ContentItem(
                title=item.title,
                body=item.body,
                summary=item.summary,
                url=item.url,
                source=item.source,
                source_name=item.source_name,
                author=item.author,
                tags=item.tags or [],
                published_at=item.published_at,
                read_count=item.read_count,
                like_count=item.like_count,
                comment_count=item.comment_count,
                favorite_count=item.favorite_count,
                fingerprint=item.fingerprint,
                domain=item.domain,
            )
            session.add(ci)
            saved += 1

        session.commit()
    return saved


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task
def collect_rss(feed_urls: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """采集 RSS 数据源并存入数据库"""
    urls = feed_urls or settings.domains.get(domain, {}).get("rss_feed_urls", [])
    collector = RSSCollector()
    results = _run_async(collector.collect(feed_urls=urls, domain=domain, max_items=limit))
    saved = _save_content_items(results)
    print(f"[Task] collect_rss({domain}): collected={len(results)}, saved(new)={saved}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_search(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """搜索引擎采集并存入数据库（关键字均衡分布）"""
    kw = keywords or settings.domains.get(domain, {}).get("search_keywords", [])
    per_keyword = max(limit // max(len(kw), 1), 3) if limit else None
    collector = SearchEngineCollector()
    results = _run_async(collector.collect(keywords=kw, domain=domain, max_per_keyword=per_keyword))
    if limit and len(results) > limit:
        results = results[:limit]
    saved = _save_content_items(results)
    print(f"[Task] collect_search({domain}): collected={len(results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_folo(search_keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """Folo 智能数据源采集并存入数据库（关键字均衡分布）"""
    kw = search_keywords or settings.domains.get(domain, {}).get("folo_keywords", [])
    per_keyword = max(limit // max(len(kw), 1), 3) if limit else None
    collector = FoloCollector()
    results = _run_async(collector.collect(search_keywords=kw, domain=domain, max_per_keyword=per_keyword))
    if limit and len(results) > limit:
        results = results[:limit]
    saved = _save_content_items(results)
    print(f"[Task] collect_folo({domain}): collected={len(results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def auto_generate():
    """定时任务：自动生成文章（扩展点）"""
    print("[Task] auto_generate: triggered")
    return "ok"


@celery_app.task
def sync_wechat_stats(days: int = 7):
    """从微信公众号拉取最近 N 天的文章阅读数据并更新数据库"""
    from datetime import date, timedelta

    end = date.today()
    start = end - timedelta(days=days - 1)

    publisher = WeChatPublisher()
    stats_list = _run_async(publisher.fetch_article_stats(start.isoformat(), end.isoformat()))
    if not stats_list:
        print(f"[Task] sync_wechat_stats: 未获取到统计数据 (range={start}~{end})")
        return {"synced": 0, "range": f"{start}~{end}"}

    # 按标题匹配已发布的文章并更新数据
    updated = 0
    with _sync_session_factory() as session:
        for stat in stats_list:
            title = stat.get("title", "")
            if not title:
                continue
            article = session.execute(
                text("SELECT id FROM articles WHERE title = :title AND status = :published_status"),
                {"title": title, "published_status": article_status_db_label(ArticleStatus.PUBLISHED)},
            ).first()
            if not article:
                continue

            # 更新统计数据
            read_user = stat.get("int_page_read_user", 0) or 0
            read_count = stat.get("int_page_read_count", 0) or 0
            share_user = stat.get("share_user", 0) or 0
            share_count = stat.get("share_count", 0) or 0
            fav_user = stat.get("add_to_fav_user", 0) or 0

            session.execute(
                text("""
                    UPDATE articles SET
                        read_count = :read_count,
                        share_count = :share_count,
                        favorite_count = :fav_count
                    WHERE id = :id
                """),
                {
                    "read_count": read_count,
                    "share_count": share_count,
                    "fav_count": fav_user,
                    "id": article[0],
                },
            )
            updated += 1

        session.commit()

    print(f"[Task] sync_wechat_stats: synced={updated}, stats_total={len(stats_list)}, range={start}~{end}")
    return {"synced": updated, "range": f"{start}~{end}"}
