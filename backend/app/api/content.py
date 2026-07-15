"""Content Pool API"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.content_intelligence import build_material_insights, build_topic_cards, score_material
from app.models.content_item import ContentItem
from app.models.domain import Domain
from app.tasks import collect_rss, collect_search, collect_folo, collect_wechat, collect_zhihu, import_wechat_urls

router = APIRouter(prefix="/api/content", tags=["content"])


@router.post("/collect")
async def trigger_collection(
    source: str = Query("all", description="rss / folo / search / wechat / zhihu / all"),
    domain: str = Query("tech", description="领域标识"),
    limit: int = Query(20, ge=1, le=100, description="采集条数"),
):
    """手动触发内容采集"""
    tasks = []
    if source in ("rss", "all"):
        task = collect_rss.delay(domain=domain, limit=limit)
        tasks.append({"source": "rss", "task_id": task.id, "domain": domain, "limit": limit})
    if source in ("folo", "all"):
        task = collect_folo.delay(domain=domain, limit=limit)
        tasks.append({"source": "folo", "task_id": task.id, "domain": domain, "limit": limit})
    if source in ("search", "search_engine", "all"):
        task = collect_search.delay(domain=domain, limit=limit)
        tasks.append({"source": "search_engine", "task_id": task.id, "domain": domain, "limit": limit})
    if source in ("wechat", "all"):
        task = collect_wechat.delay(domain=domain, limit=limit)
        tasks.append({"source": "wechat", "task_id": task.id, "domain": domain, "limit": limit})
    if source in ("zhihu", "all"):
        task = collect_zhihu.delay(domain=domain, limit=limit)
        tasks.append({"source": "zhihu", "task_id": task.id, "domain": domain, "limit": limit})
    if not tasks:
        raise HTTPException(400, f"无效的 source: {source}，可选: rss, folo, search, wechat, zhihu, all")
    return {"message": "采集任务已提交", "tasks": tasks}


@router.get("/collect/status/{task_id}")
def get_collection_task_status(task_id: str):
    """查询异步采集任务的当前状态与执行结果"""
    from celery.result import AsyncResult
    from app.celery_app import celery_app
    res = AsyncResult(task_id, app=celery_app)
    state = res.state
    info = None
    if state == "SUCCESS":
        info = res.result
    elif state == "FAILURE":
        info = str(res.result)
    return {
        "task_id": task_id,
        "status": state,
        "result": info
    }


@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db)):
    """返回可用的领域列表（供前端筛选器使用）"""
    rows = (await db.execute(select(Domain).order_by(Domain.created_at))).scalars().all()
    items = [{"id": d.id, "label": d.label} for d in rows]
    return {"domains": items}


@router.get("/folo/status")
def get_folo_status():
    """获取 FoloCLI 当前的登录状态（非阻塞、带缓存）"""
    from app.collectors.folo_collector import get_folo_status_sync
    return get_folo_status_sync()


@router.post("/folo/login")
async def trigger_folo_login():
    """唤起本地默认浏览器进行 FoloCLI 登录授权"""
    import subprocess
    from app.collectors.folo_collector import FOLOCLI, clear_folo_status_cache
    try:
        # 唤起登录的同时清除原先的缓存状态，以便后续轮询或刷新时获取最新检测结果
        clear_folo_status_cache()
        # 异步拉起 FoloCLI login，它会自动在 Windows 桌面上弹开默认的浏览器登录网页
        subprocess.Popen(f"{FOLOCLI} login", shell=True)
        return {"message": "已成功在你的浏览器中唤起 Folo 登录页，请在弹出的网页中完成登录。"}
    except Exception as e:
        raise HTTPException(500, f"唤起 Folo 登录失败: {e}")


@router.get("")
async def list_content(
    source: str | None = Query(None, description="按来源过滤"),
    domain: str | None = Query(None, description="按领域过滤"),
    keyword: str | None = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(ContentItem).order_by(ContentItem.collected_at.desc())

    if source:
        query = query.where(ContentItem.source == source)
    if domain:
        query = query.where(ContentItem.domain == domain)
    if keyword:
        query = query.where(
            ContentItem.title.ilike(f"%{keyword}%") | ContentItem.summary.ilike(f"%{keyword}%")
        )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [{
            "id": r.id,
            "title": r.title,
            "body": r.body[:500] if r.body else None,
            "summary": r.summary,
            "url": r.url,
            "source": r.source,
            "source_name": r.source_name,
            "author": r.author,
            "tags": r.tags,
            "quality": score_material(r),
            "domain": r.domain,
            "used_at": r.used_at.isoformat() if r.used_at else None,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "collected_at": r.collected_at.isoformat(),
            "read_count": r.read_count,
            "like_count": r.like_count,
            "comment_count": r.comment_count,
            "favorite_count": r.favorite_count,
        } for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class BatchDeleteRequest(BaseModel):
    ids: list[str]


class WeChatImportRequest(BaseModel):
    urls: list[str]
    domain: str = "tech"


@router.get("/insights")
async def get_content_insights(
    domain: str | None = Query(None, description="按领域过滤"),
    source: str | None = Query(None, description="按来源过滤"),
    limit: int = Query(80, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
):
    query = select(ContentItem).where(ContentItem.used_at.is_(None)).order_by(ContentItem.collected_at.desc())
    if domain:
        query = query.where(ContentItem.domain == domain)
    if source:
        query = query.where(ContentItem.source == source)
    rows = (await db.execute(query.limit(limit))).scalars().all()
    insights = build_material_insights(rows)
    return {
        "items": insights,
        "summary": {
            "total": len(insights),
            "high_quality": len([x for x in insights if x["score"] >= 75 and not x["duplicate_group"]]),
            "duplicates": len([x for x in insights if x["duplicate_group"]]),
            "risky": len([x for x in insights if x["risks"]]),
        },
    }


@router.get("/topic-cards")
async def get_topic_cards(
    domain: str | None = Query(None, description="按领域过滤"),
    limit: int = Query(6, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    query = select(ContentItem).where(ContentItem.used_at.is_(None)).order_by(ContentItem.collected_at.desc())
    if domain:
        query = query.where(ContentItem.domain == domain)
    rows = (await db.execute(query.limit(120))).scalars().all()
    cards = build_topic_cards(rows, limit=limit)
    return {"cards": cards, "total_materials": len(rows)}


@router.post("/wechat/import")
async def trigger_wechat_import(body: WeChatImportRequest):
    """按微信文章链接导入外部公众号文章。"""
    urls = [u.strip() for u in body.urls if u and u.strip()]
    if not urls:
        raise HTTPException(400, "urls 不能为空")
    task = import_wechat_urls.delay(urls=urls, domain=body.domain)
    return {
        "message": "微信文章导入任务已提交",
        "tasks": [{"source": "wechat", "task_id": task.id, "domain": body.domain, "limit": len(urls)}],
    }


@router.get("/sources")
async def list_sources(db: AsyncSession = Depends(get_db)):
    query = select(ContentItem.source, func.count().label("count")).group_by(ContentItem.source)
    rows = (await db.execute(query)).all()
    return {"sources": [{"source": r[0], "count": r[1]} for r in rows]}


@router.get("/{item_id}")
async def get_content_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """查看单条内容的完整详情"""
    item = await db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "内容不存在")
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "summary": item.summary,
        "url": item.url,
        "source": item.source,
        "source_name": item.source_name,
        "author": item.author,
        "tags": item.tags,
        "domain": item.domain,
        "used_at": item.used_at.isoformat() if item.used_at else None,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "collected_at": item.collected_at.isoformat(),
        "read_count": item.read_count,
        "like_count": item.like_count,
        "comment_count": item.comment_count,
        "favorite_count": item.favorite_count,
    }


@router.post("/batch-delete")
async def batch_delete_content(body: BatchDeleteRequest, db: AsyncSession = Depends(get_db)):
    """批量删除内容"""
    if not body.ids:
        raise HTTPException(400, "ids 不能为空")
    result = await db.execute(select(ContentItem).where(ContentItem.id.in_(body.ids)))
    items = result.scalars().all()
    deleted_ids = []
    for item in items:
        await db.delete(item)
        deleted_ids.append(item.id)
    await db.commit()
    return {"message": f"已删除 {len(deleted_ids)} 条内容", "deleted_ids": deleted_ids, "total_requested": len(body.ids)}


@router.delete("/{item_id}")
async def delete_content_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """删除单条内容"""
    item = await db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "内容不存在")
    await db.delete(item)
    await db.commit()
    return {"message": "已删除", "id": item_id}
