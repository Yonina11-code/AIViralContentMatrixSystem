"""内容资产层 API（AssetCard CRUD）"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.asset_card import AssetCard, AssetCategory

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.get("/cards")
async def list_cards(
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AssetCard).order_by(AssetCard.score.desc())
    if category:
        query = query.where(AssetCard.category == category)
    rows = (await db.execute(query)).scalars().all()
    return {
        "items": [{
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
            "version": r.version,
            "score": r.score,
            "usage_count": r.usage_count,
            "tags": r.tags,
        } for r in rows],
        "total": len(rows),
    }


@router.get("/cards/{card_id}")
async def get_card(card_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(AssetCard, card_id)
    if not row:
        raise HTTPException(404, "卡片不存在")
    return row


@router.post("/cards")
async def create_card(data: dict, db: AsyncSession = Depends(get_db)):
    card = AssetCard(
        name=data["name"],
        category=data.get("category", AssetCategory.PROMPT_TEMPLATE),
        content=data["content"],
        description=data.get("description", ""),
        tags=data.get("tags", []),
        platforms=data.get("platforms", []),
    )
    db.add(card)
    await db.commit()
    return {"id": card.id, "name": card.name, "category": card.category}


@router.put("/cards/{card_id}")
async def update_card(card_id: str, data: dict, db: AsyncSession = Depends(get_db)):
    card = await db.get(AssetCard, card_id)
    if not card:
        raise HTTPException(404, "卡片不存在")

    # Version control: save old version to history
    version_entry = {
        "version": card.version,
        "content": card.content,
        "score": card.score,
        "updated_at": card.updated_at.isoformat(),
    }
    history = list(card.version_history or [])
    history.append(version_entry)

    card.content = data.get("content", card.content)
    card.description = data.get("description", card.description)
    card.tags = data.get("tags", card.tags)
    card.version = card.version + 1
    card.version_history = history

    await db.commit()
    return {"id": card.id, "version": card.version}
