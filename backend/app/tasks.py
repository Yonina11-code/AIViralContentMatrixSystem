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


def _check_duplicates_and_serialize(items) -> list[dict]:
    """检查采集到的内容是否重复，并序列化为前端可直接识别的字典列表"""
    res = []
    seen_fingerprints = set()
    with _sync_session_factory() as session:
        for item in items:
            title = item.title
            is_dup = False
            reason = ""
            
            if not item.fingerprint:
                is_dup = True
                reason = "无唯一指纹"
            elif item.fingerprint in seen_fingerprints:
                is_dup = True
                reason = "批次内重复"
            else:
                existing = session.execute(
                    text("SELECT id FROM content_items WHERE fingerprint = :fp"),
                    {"fp": item.fingerprint},
                ).first()
                if existing:
                    is_dup = True
                    reason = "数据库已存在"
            
            if not is_dup:
                seen_fingerprints.add(item.fingerprint)

            res.append({
                "title": title,
                "body": item.body,
                "summary": item.summary,
                "url": item.url,
                "source": item.source,
                "source_name": item.source_name,
                "author": item.author,
                "tags": item.tags or [],
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "read_count": item.read_count,
                "like_count": item.like_count,
                "comment_count": item.comment_count,
                "favorite_count": item.favorite_count,
                "fingerprint": item.fingerprint,
                "domain": item.domain,
                "is_duplicate": is_dup,
                "duplicate_reason": reason,
            })
    return res


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

    collector = RSSCollector()
    results = _run_async(collector.collect(feed_urls=urls, domain=domain, max_items=limit))
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_rss({domain}): collected={len(results)}")
    return {"collected": len(results), "items": items_list, "domain": domain}


@celery_app.task
def collect_search(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """搜索引擎采集并存入数据库（关键字均衡分布）"""
    api_key = settings.google_api_key
    cse_id = settings.google_cse_id
    if not api_key or not cse_id or "your_google_api_key" in api_key or "your_custom_search" in cse_id:
        print("[Task] collect_search: Google API key or CSE ID not configured.")
        return {
            "collected": 0,
            "items": [],
            "domain": domain,
            "error": "谷歌搜索服务 API Key 未配置，请在后台 .env 文件中填写真实的 GOOGLE_API_KEY 与 GOOGLE_CSE_ID"
        }

    kw = keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            kw = d.search_keywords if d else []
        if not kw:
            kw = settings.domains.get(domain, {}).get("search_keywords", [])
    per_keyword = max(limit // max(len(kw), 1), 3) if limit else None
    collector = SearchEngineCollector()
    results = _run_async(collector.collect(keywords=kw, domain=domain, max_per_keyword=per_keyword))
    if limit and len(results) > limit:
        results = results[:limit]
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_search({domain}): collected={len(results)}, per_keyword={per_keyword}")
    return {"collected": len(results), "items": items_list, "domain": domain}


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
    per_keyword = max(limit // max(len(kw), 1), 3) if limit else None
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
                results = _run_async(rss_collector.collect(feed_urls=urls, domain=domain, max_items=limit))
                print(f"[Task] Fallback to RSS success: fetched {len(results)} items")
            except Exception as re_err:
                print(f"[Task] Fallback to RSS error: {re_err}")

    if limit and len(results) > limit:
        results = results[:limit]
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_folo({domain}): collected={len(results)}, per_keyword={per_keyword}")
    return {"collected": len(results), "items": items_list, "domain": domain}


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
def collect_tavily(keywords: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """Tavily AI 搜索引擎采集（关键字均衡分布）"""
    kw = keywords
    if not kw:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            kw = d.search_keywords if d else []
        if not kw:
            kw = settings.domains.get(domain, {}).get("search_keywords", [])
    per_keyword = max(limit // max(len(kw), 1), 3) if limit else None
    from app.collectors.tavily_collector import TavilyCollector
    collector = TavilyCollector()
    results = _run_async(collector.collect(keywords=kw, domain=domain, max_per_keyword=per_keyword))
    if limit and len(results) > limit:
        results = results[:limit]
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_tavily({domain}): collected={len(results)}")
    return {"collected": len(results), "items": items_list, "domain": domain}


@celery_app.task
def collect_wechat(wechat_ids: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """微信公众号采集（支持手输 ID 订阅拉取，以及手输关键词 site:mp.weixin.qq.com 搜索）"""
    ids = wechat_ids
    if not ids:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            ids = d.wechat_ids if d else []
            
    if not ids:
        return {"collected": 0, "items": [], "domain": domain}
        
    import re
    results = []
    rss_ids = []
    search_keywords = []

    for item_id in ids:
        if not item_id:
            continue
        # 只要包含非 ASCII/非微信号合法字符，或者含有空格，就判定为搜索关键词
        if not re.match(r'^[a-zA-Z0-9_\-]+$', item_id):
            search_keywords.append(f"site:mp.weixin.qq.com {item_id}")
        else:
            rss_ids.append(item_id)

    # 1. 订阅拉取模式
    if rss_ids:
        rsshub_base = getattr(settings, "rsshub_base_url", "https://rsshub.app")
        urls = [f"{rsshub_base}/wechat/mp/msghistory/{mp_id}" for mp_id in rss_ids]
        collector_rss = RSSCollector()
        try:
            res_rss = _run_async(collector_rss.collect(feed_urls=urls, domain=domain, max_items=limit))
            results.extend(res_rss)
        except Exception as e:
            print(f"[Task] collect_wechat RSS failed: {e}")

    # 2. 全文搜索模式
    task_error = None
    if search_keywords:
        import os
        has_tavily = bool(settings.tavily_api_key or os.environ.get("TAVILY_API_KEY"))
        has_google = bool(settings.google_api_key and "your_google_api" not in settings.google_api_key)
        
        if has_tavily:
            from app.collectors.tavily_collector import TavilyCollector
            collector_search = TavilyCollector()
            try:
                res_search = _run_async(collector_search.collect(keywords=search_keywords, domain=domain, max_per_keyword=limit))
                results.extend(res_search)
            except Exception as e:
                print(f"[Task] collect_wechat Tavily failed: {e}")
        elif has_google:
            collector_search = SearchEngineCollector()
            try:
                res_search = _run_async(collector_search.collect(keywords=search_keywords, domain=domain, max_per_keyword=limit))
                results.extend(res_search)
            except Exception as e:
                print(f"[Task] collect_wechat Google failed: {e}")
        else:
            task_error = "未配置 Google (GOOGLE_API_KEY) 或 Tavily (TAVILY_API_KEY) 搜索 Key，无法执行微信公众号全文检索。"

    # 重写 source_name 和 source
    for item in results:
        item.source = "wechat"
        if not item.source_name or item.source_name in ("RSS", "GoogleSearch"):
            item.source_name = "微信公众号"
            
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_wechat({domain}): collected={len(results)}")
    
    ret_val = {"collected": len(results), "items": items_list, "domain": domain}
    if task_error:
        ret_val["error"] = task_error
    return ret_val


@celery_app.task
def collect_xhs(xhs_ids: list[str] | None = None, domain: str = "tech", limit: int = 20):
    """小红书博主内容采集（支持手输 ID 订阅拉取，以及手输关键词 site:xiaohongshu.com 搜索）"""
    ids = xhs_ids
    if not ids:
        with _sync_session_factory() as session:
            from app.models.domain import Domain
            d = session.get(Domain, domain)
            ids = d.xiaohongshu_ids if d else []
            
    if not ids:
        return {"collected": 0, "items": [], "domain": domain}
        
    import re
    results = []
    rss_ids = []
    search_keywords = []

    for item_id in ids:
        if not item_id:
            continue
        if not re.match(r'^[a-zA-Z0-9_\-]+$', item_id):
            search_keywords.append(f"site:xiaohongshu.com {item_id}")
        else:
            rss_ids.append(item_id)

    # 1. 订阅拉取模式
    if rss_ids:
        rsshub_base = getattr(settings, "rsshub_base_url", "https://rsshub.app")
        urls = [f"{rsshub_base}/xiaohongshu/user/{user_id}" for user_id in rss_ids]
        collector_rss = RSSCollector()
        try:
            res_rss = _run_async(collector_rss.collect(feed_urls=urls, domain=domain, max_items=limit))
            results.extend(res_rss)
        except Exception as e:
            print(f"[Task] collect_xhs RSS failed: {e}")

    # 2. 全文搜索模式
    task_error = None
    if search_keywords:
        import os
        has_tavily = bool(settings.tavily_api_key or os.environ.get("TAVILY_API_KEY"))
        has_google = bool(settings.google_api_key and "your_google_api" not in settings.google_api_key)
        
        if has_tavily:
            from app.collectors.tavily_collector import TavilyCollector
            collector_search = TavilyCollector()
            try:
                res_search = _run_async(collector_search.collect(keywords=search_keywords, domain=domain, max_per_keyword=limit))
                results.extend(res_search)
            except Exception as e:
                print(f"[Task] collect_xhs Tavily failed: {e}")
        elif has_google:
            collector_search = SearchEngineCollector()
            try:
                res_search = _run_async(collector_search.collect(keywords=search_keywords, domain=domain, max_per_keyword=limit))
                results.extend(res_search)
            except Exception as e:
                print(f"[Task] collect_xhs Google failed: {e}")
        else:
            task_error = "未配置 Google (GOOGLE_API_KEY) 或 Tavily (TAVILY_API_KEY) 搜索 Key，无法执行小红书全文检索。"

    # 重写 source_name 和 source
    for item in results:
        item.source = "xhs"
        if not item.source_name or item.source_name in ("RSS", "GoogleSearch"):
            item.source_name = "小红书博主"
            
    items_list = _check_duplicates_and_serialize(results)
    print(f"[Task] collect_xhs({domain}): collected={len(results)}")
    
    ret_val = {"collected": len(results), "items": items_list, "domain": domain}
    if task_error:
        ret_val["error"] = task_error
    return ret_val

