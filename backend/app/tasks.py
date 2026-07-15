"""Celery 异步任务定义"""

import asyncio

from celery import shared_task
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import sessionmaker

from app.celery_app import celery_app
from app.collectors import RSSCollector, SearchEngineCollector, FoloCollector, WeChatArticleCollector, ZhihuCollector
from app.config import settings
from app.models.content_item import ContentItem
from app.models.article import Article, ArticleStatus, article_status_db_label
from app.publishers.wechat import WeChatPublisher

# ---------- Celery 专用同步数据库连接 ----------
_sync_db_url = settings.database_url.replace("+asyncpg", "+psycopg2")
_sync_engine = create_engine(_sync_db_url, pool_size=5, max_overflow=10)
_sync_session_factory = sessionmaker(bind=_sync_engine)


HEALTH_WECHAT_KEYWORDS = [
    "控糖饮食误区 科普",
    "高血压饮食误区 科普",
    "睡眠调理 科普 医生",
    "肠道健康 调理 科普",
    "中医养生 误区 科普",
    "节气养生 科普 医生",
    "更年期调理 科普",
    "尿酸高 饮食误区 科普",
]


def _default_wechat_keywords(domain: str, configured_keywords: list[str] | None) -> list[str]:
    """微信采集使用更精确的健康科普关键词，避免宽泛养生词带来低质内容。"""
    if domain == "health_regimen":
        return HEALTH_WECHAT_KEYWORDS
    return configured_keywords or []


def _candidate_fetch_limit(limit: int | None) -> int | None:
    """采集时多拉候选，后续再过滤已入库内容，降低连续采集重复率。"""
    if not limit:
        return limit
    return max(limit * 3, limit + 10)


def _per_keyword_limit(total_limit: int | None, keywords: list[str] | None, *, minimum: int = 3) -> int | None:
    if not total_limit:
        return None
    return max(total_limit // max(len(keywords or []), 1), minimum)


def _existing_fingerprints(fingerprints: list[str]) -> set[str]:
    if not fingerprints:
        return set()
    with _sync_session_factory() as session:
        rows = (
            session.query(ContentItem.fingerprint)
            .filter(ContentItem.fingerprint.in_(fingerprints))
            .all()
        )
    return {row[0] for row in rows if row[0]}


def _normalize_identity_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _content_identity_key(item) -> tuple[str, str, str, str] | None:
    title = _normalize_identity_text(getattr(item, "title", None))
    if not title:
        return None
    return (
        getattr(item, "domain", None) or "",
        getattr(item, "source", None) or "",
        title,
        _normalize_identity_text(getattr(item, "source_name", None)),
    )


def _existing_content_identity_keys(items) -> set[tuple[str, str, str, str]]:
    keys = {key for item in items if (key := _content_identity_key(item))}
    if not keys:
        return set()

    domains = {key[0] for key in keys}
    sources = {key[1] for key in keys}
    titles = {key[2] for key in keys}

    with _sync_session_factory() as session:
        rows = (
            session.query(
                ContentItem.domain,
                ContentItem.source,
                ContentItem.title,
                ContentItem.source_name,
            )
            .filter(ContentItem.domain.in_(domains))
            .filter(ContentItem.source.in_(sources))
            .filter(func.lower(func.trim(ContentItem.title)).in_(titles))
            .all()
        )

    existing = set()
    for domain, source, title, source_name in rows:
        key = (domain or "", source or "", _normalize_identity_text(title), _normalize_identity_text(source_name))
        if key in keys:
            existing.add(key)
    return existing


def _select_new_content_items(items, limit: int | None = None):
    """从候选中挑出数据库尚未存在的内容，保留采集器原始排序。"""
    seen_batch: set[str] = set()
    seen_identity_keys: set[tuple[str, str, str, str]] = set()
    deduped = []
    for item in items:
        fingerprint = getattr(item, "fingerprint", None)
        identity_key = _content_identity_key(item)
        if not fingerprint or fingerprint in seen_batch or (identity_key and identity_key in seen_identity_keys):
            continue
        deduped.append(item)
        seen_batch.add(fingerprint)
        if identity_key:
            seen_identity_keys.add(identity_key)

    existing = _existing_fingerprints([item.fingerprint for item in deduped])
    existing_identity_keys = _existing_content_identity_keys(deduped)
    selected = [
        item
        for item in deduped
        if item.fingerprint not in existing
        and (key := _content_identity_key(item)) not in existing_identity_keys
    ]
    if limit:
        return selected[:limit]
    return selected


def _save_content_items(items) -> int:
    """将采集到的内容批量写入数据库（内存+数据库去重）"""
    saved = 0
    seen_fingerprints = set()
    seen_identity_keys = set()
    with _sync_session_factory() as session:
        for item in items:
            if not item.fingerprint:
                continue
            identity_key = _content_identity_key(item)
                
            # 内存防重（批次内去重）
            if item.fingerprint in seen_fingerprints or (identity_key and identity_key in seen_identity_keys):
                continue

            # 数据库防重
            existing = session.execute(
                text("SELECT id FROM content_items WHERE fingerprint = :fp"),
                {"fp": item.fingerprint},
            ).first()
            if existing:
                continue

            if identity_key:
                existing_same_content = session.execute(
                    text("""
                        SELECT id
                        FROM content_items
                        WHERE domain = :domain
                          AND source = :source
                          AND lower(trim(title)) = :title
                          AND lower(trim(coalesce(source_name, ''))) = :source_name
                        LIMIT 1
                    """),
                    {
                        "domain": identity_key[0],
                        "source": identity_key[1],
                        "title": identity_key[2],
                        "source_name": identity_key[3],
                    },
                ).first()
                if existing_same_content:
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
            seen_fingerprints.add(item.fingerprint)
            if identity_key:
                seen_identity_keys.add(identity_key)
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
    urls = feed_urls
    if not urls:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            urls = d.rss_feed_urls if d else []
        if not urls:
            urls = settings.domains.get(domain, {}).get("rss_feed_urls", [])

    candidate_limit = _candidate_fetch_limit(limit)
    collector = RSSCollector()
    results = _run_async(collector.collect(feed_urls=urls, domain=domain, max_items=candidate_limit))
    new_results = _select_new_content_items(results, limit)
    saved = _save_content_items(new_results)
    print(f"[Task] collect_rss({domain}): collected={len(results)}, selected_new={len(new_results)}, saved(new)={saved}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_search(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """搜索引擎采集并存入数据库（关键字均衡分布）"""
    kw = keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            kw = d.search_keywords if d else []
        if not kw:
            kw = settings.domains.get(domain, {}).get("search_keywords", [])
    candidate_limit = _candidate_fetch_limit(limit)
    per_keyword = _per_keyword_limit(candidate_limit, kw)
    collector = SearchEngineCollector()
    results = _run_async(collector.collect(keywords=kw, domain=domain, max_per_keyword=per_keyword))
    new_results = _select_new_content_items(results, limit)
    saved = _save_content_items(new_results)
    print(f"[Task] collect_search({domain}): collected={len(results)}, selected_new={len(new_results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_folo(search_keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """Folo 智能数据源采集并存入数据库（关键字均衡分布）"""
    kw = search_keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            kw = d.folo_keywords if d else []
        if not kw:
            kw = settings.domains.get(domain, {}).get("folo_keywords", [])
    candidate_limit = _candidate_fetch_limit(limit)
    per_keyword = _per_keyword_limit(candidate_limit, kw)
    collector = FoloCollector()
    results = []
    try:
        results = _run_async(collector.collect(search_keywords=kw, domain=domain, max_per_keyword=per_keyword))
    except Exception as e:
        print(f"[Task] collect_folo error: {e}")

    # 自动降级机制：如果 Folo 采集由于授权等原因抓回 0 条，则自动切换为 RSS 兜底采集
    if not results:
        print(f"[Task] collect_folo({domain}) returned 0 items. Falling back to RSS...")
        urls = []
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            urls = d.rss_feed_urls if d else []
        if not urls:
            urls = settings.domains.get(domain, {}).get("rss_feed_urls", [])
            
        if urls:
            from app.collectors import RSSCollector
            rss_collector = RSSCollector()
            try:
                results = _run_async(rss_collector.collect(feed_urls=urls, domain=domain, max_items=candidate_limit))
                print(f"[Task] Fallback to RSS success: fetched {len(results)} items")
            except Exception as re_err:
                print(f"[Task] Fallback to RSS error: {re_err}")

    new_results = _select_new_content_items(results, limit)
    saved = _save_content_items(new_results)
    print(f"[Task] collect_folo({domain}): collected={len(results)}, selected_new={len(new_results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_wechat(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """采集外部微信公众号文章并存入内容池。"""
    kw = keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            if d and getattr(d, "search_keywords", None):
                kw = d.search_keywords
        if not kw:
            kw = settings.domains.get(domain, {}).get("wechat_keywords", [])
        if not kw:
            kw = settings.domains.get(domain, {}).get("search_keywords", [])
        kw = _default_wechat_keywords(domain, kw)

    candidate_limit = _candidate_fetch_limit(limit)
    per_keyword = _per_keyword_limit(candidate_limit, kw)
    collector = WeChatArticleCollector()
    results = []
    try:
        results = _run_async(collector.collect(keywords=kw, domain=domain, max_per_keyword=per_keyword))
    except Exception as e:
        print(f"[Task] collect_wechat error: {e}")

    new_results = _select_new_content_items(results, limit)
    saved = _save_content_items(new_results)
    print(f"[Task] collect_wechat({domain}): collected={len(results)}, selected_new={len(new_results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def collect_zhihu(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """通过知乎官方开放平台采集站内搜索内容与热榜内容。"""
    kw = keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            if d and getattr(d, "search_keywords", None):
                kw = d.search_keywords
        if not kw:
            kw = settings.domains.get(domain, {}).get("zhihu_keywords", [])
        if not kw:
            kw = settings.domains.get(domain, {}).get("search_keywords", [])

    candidate_limit = _candidate_fetch_limit(limit)
    per_keyword = _per_keyword_limit(candidate_limit, kw)
    collector = ZhihuCollector()
    results = []
    try:
        # 热榜作为补充信号，关键词搜索作为领域素材来源。
        results = _run_async(
            collector.collect(
                keywords=kw,
                domain=domain,
                max_per_keyword=per_keyword,
                hot_list=True,
                hot_limit=min(candidate_limit or limit or 30, 30),
            )
        )
    except Exception as e:
        print(f"[Task] collect_zhihu error: {e}")

    new_results = _select_new_content_items(results, limit)
    saved = _save_content_items(new_results)
    print(f"[Task] collect_zhihu({domain}): collected={len(results)}, selected_new={len(new_results)}, saved(new)={saved}, per_keyword={per_keyword}")
    return {"collected": len(results), "saved": saved, "domain": domain}


@celery_app.task
def import_wechat_urls(urls: list[str], domain: str = "tech"):
    """按微信文章链接导入外部文章并存入内容池。"""
    collector = WeChatArticleCollector()
    results = []
    try:
        results = _run_async(collector.collect(urls=urls, domain=domain))
    except Exception as e:
        print(f"[Task] import_wechat_urls error: {e}")

    saved = _save_content_items(results)
    print(f"[Task] import_wechat_urls({domain}): collected={len(results)}, saved(new)={saved}")
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


@celery_app.task
def publish_due_articles():
    """发布已经到达 scheduled_publish_at 的审核通过文章。"""
    now = datetime.utcnow()
    publisher = WeChatPublisher()
    published = 0
    with _sync_session_factory() as session:
        rows = session.execute(
            text("""
                SELECT id, title, body, summary
                FROM articles
                WHERE status = :approved_status
                  AND scheduled_publish_at IS NOT NULL
                  AND scheduled_publish_at <= :now
                ORDER BY scheduled_publish_at ASC
                LIMIT 10
            """),
            {"approved_status": article_status_db_label(ArticleStatus.APPROVED), "now": now},
        ).all()
        for row in rows:
            result = _run_async(publisher.publish_article(title=row.title, body=row.body, summary=row.summary))
            if result.get("success"):
                session.execute(
                    text("""
                        UPDATE articles
                        SET status = :published_status,
                            publish_platform_id = :platform_id,
                            published_at = :published_at,
                            scheduled_publish_at = NULL
                        WHERE id = :id
                    """),
                    {
                        "published_status": article_status_db_label(ArticleStatus.PUBLISHED),
                        "platform_id": result.get("media_id", ""),
                        "published_at": now,
                        "id": row.id,
                    },
                )
                published += 1
        session.commit()
    print(f"[Task] publish_due_articles: published={published}")
    return {"published": published}
