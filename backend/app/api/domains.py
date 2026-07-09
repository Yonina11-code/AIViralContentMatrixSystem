"""Domain CRUD API — 领域配置管理"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.domain import Domain

router = APIRouter(prefix="/api/domains", tags=["domains"])


# ── Schemas ──────────────────────────────────────────────────────────

class DomainCreate(BaseModel):
    id: str  # 领域标识，如 "tech"
    label: str
    description: str = ""
    folo_keywords: list[str] = []
    search_keywords: list[str] = []
    rss_feed_urls: list[str] = []
    wechat_ids: list[str] = []
    xiaohongshu_ids: list[str] = []


class DomainUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    folo_keywords: list[str] | None = None
    search_keywords: list[str] | None = None
    rss_feed_urls: list[str] | None = None
    wechat_ids: list[str] | None = None
    xiaohongshu_ids: list[str] | None = None


class DomainOut(BaseModel):
    id: str
    label: str
    description: str
    folo_keywords: list[str]
    search_keywords: list[str]
    rss_feed_urls: list[str]
    wechat_ids: list[str]
    xiaohongshu_ids: list[str]
    created_at: str | None = None
    updated_at: str | None = None


# ── CRUD ─────────────────────────────────────────────────────────────

@router.get("")
async def list_domains(db: AsyncSession = Depends(get_db)):
    """列出所有领域"""
    rows = (await db.execute(select(Domain).order_by(Domain.created_at))).scalars().all()
    return {"domains": [_domain_to_dict(d) for d in rows]}


@router.get("/{domain_id}")
async def get_domain(domain_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个领域详情"""
    d = await db.get(Domain, domain_id)
    if not d:
        raise HTTPException(404, "领域不存在")
    return _domain_to_dict(d)


@router.post("", status_code=201)
async def create_domain(data: DomainCreate, db: AsyncSession = Depends(get_db)):
    """创建新领域"""
    existing = await db.get(Domain, data.id)
    if existing:
        raise HTTPException(409, f"领域 '{data.id}' 已存在")

    d = Domain(
        id=data.id,
        label=data.label,
        description=data.description,
        folo_keywords=data.folo_keywords,
        search_keywords=data.search_keywords,
        rss_feed_urls=data.rss_feed_urls,
        wechat_ids=data.wechat_ids,
        xiaohongshu_ids=data.xiaohongshu_ids,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return _domain_to_dict(d)


@router.put("/{domain_id}")
async def update_domain(domain_id: str, data: DomainUpdate, db: AsyncSession = Depends(get_db)):
    """更新领域配置"""
    d = await db.get(Domain, domain_id)
    if not d:
        raise HTTPException(404, "领域不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(d, key, value)

    await db.commit()
    await db.refresh(d)
    return _domain_to_dict(d)


@router.delete("/{domain_id}")
async def delete_domain(domain_id: str, db: AsyncSession = Depends(get_db)):
    """删除领域"""
    d = await db.get(Domain, domain_id)
    if not d:
        raise HTTPException(404, "领域不存在")
    await db.delete(d)
    await db.commit()
    return {"message": f"领域 '{domain_id}' 已删除"}


# ── Helper ───────────────────────────────────────────────────────────

def _domain_to_dict(d: Domain) -> dict:
    return {
        "id": d.id,
        "label": d.label,
        "description": d.description or "",
        "folo_keywords": d.folo_keywords or [],
        "search_keywords": d.search_keywords or [],
        "rss_feed_urls": d.rss_feed_urls or [],
        "wechat_ids": getattr(d, "wechat_ids", []) or [],
        "xiaohongshu_ids": getattr(d, "xiaohongshu_ids", []) or [],
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
