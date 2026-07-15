"""运营日历与调度 API"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import get_db
from app.models.article import Article, ArticleStatus, article_status_public_value
from app.platform_ops import build_calendar_events

router = APIRouter(prefix="/api/operations", tags=["operations"])


class ScheduleArticleRequest(BaseModel):
    scheduled_publish_at: datetime | None


@router.get("/calendar")
async def get_operations_calendar(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Article).order_by(Article.created_at.desc()).limit(200))).scalars().all()
    events = build_calendar_events(rows, celery_app.conf.beat_schedule or {})
    return {"events": events}


@router.post("/articles/{article_id}/schedule")
async def schedule_article_publish(
    article_id: str,
    body: ScheduleArticleRequest,
    db: AsyncSession = Depends(get_db),
):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    if article_status_public_value(article.status) == ArticleStatus.PUBLISHED.value:
        raise HTTPException(400, "已发布文章不能预约发布")

    article.scheduled_publish_at = body.scheduled_publish_at
    if body.scheduled_publish_at is not None:
        article.status = ArticleStatus.APPROVED
    await db.commit()
    return {
        "article_id": article.id,
        "status": article_status_public_value(article.status),
        "scheduled_publish_at": article.scheduled_publish_at.isoformat() if article.scheduled_publish_at else None,
    }
