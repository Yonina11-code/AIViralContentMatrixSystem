import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Float, JSON, DateTime, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
import enum


class ArticleStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


def article_status_db_label(status: ArticleStatus | str) -> str:
    """Return the PostgreSQL enum label used by SQLAlchemy's default Enum mapping."""
    if isinstance(status, ArticleStatus):
        return status.name
    normalized = str(status)
    for item in ArticleStatus:
        if normalized == item.name or normalized == item.value:
            return item.name
    return normalized


def article_status_public_value(status: ArticleStatus | str | None) -> str | None:
    """Return the lowercase status value expected by API clients."""
    if status is None:
        return None
    if isinstance(status, ArticleStatus):
        return status.value
    normalized = str(status)
    for item in ArticleStatus:
        if normalized == item.name or normalized == item.value:
            return item.value
    return normalized


def article_status_from_public_value(status: str) -> ArticleStatus:
    for item in ArticleStatus:
        if status == item.value or status == item.name:
            return item
    raise ValueError(f"Unknown article status: {status}")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(String(50), default="wechat")

    # Agent generation trace
    source_content_ids: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)
    agent_trace: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)
    template_combo_id: Mapped[str] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(SAEnum(ArticleStatus), default=ArticleStatus.DRAFT)

    # Publishing
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    scheduled_publish_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    publish_platform_id: Mapped[str] = mapped_column(String(200), nullable=True)

    # Performance metrics (read back after publish)
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
