import uuid
from datetime import datetime

from sqlalchemy import String, Text, Float, Integer, JSON, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
import enum


class AssetCategory(str, enum.Enum):
    TITLE_TEMPLATE = "title_template"
    OPENING_TEMPLATE = "opening_template"
    TRANSITION_TEMPLATE = "transition_template"
    CASE_TEMPLATE = "case_template"
    INTERACTION_TEMPLATE = "interaction_template"
    COMMENT_TEMPLATE = "comment_template"
    IMAGE_STYLE = "image_style"
    PROMPT_TEMPLATE = "prompt_template"
    WRITING_STYLE = "writing_style"
    VIRAL_CASE = "viral_case"
    RISK_RULE = "risk_rule"
    PLATFORM_RULE = "platform_rule"


class AssetCard(Base):
    __tablename__ = "asset_cards"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(SAEnum(AssetCategory), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Version control
    version: Mapped[int] = mapped_column(Integer, default=1)
    version_history: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)

    # Scoring & usage
    score: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    # Tags for semantic retrieval
    tags: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)

    # Platform applicability (empty = all platforms)
    platforms: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TemplateCombo(Base):
    """组合多个 AssetCard 形成完整的写作套路"""
    __tablename__ = "template_combos"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # slots: [{position: "title", asset_card_id: "xxx", weight: 0.3}, ...]
    slots: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    score: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
