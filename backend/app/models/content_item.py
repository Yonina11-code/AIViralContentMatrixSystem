import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
import enum


class ContentSource(str, enum.Enum):
    RSS = "rss"
    SEARCH_ENGINE = "search_engine"
    FOLO = "folo"
    WECHAT = "wechat"


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_name: Mapped[str] = mapped_column(String(100), nullable=True)
    author: Mapped[str] = mapped_column(String(200), nullable=True)
    tags: Mapped[dict] = mapped_column(JSON, nullable=True, default=list)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Domain label for multi-domain support
    domain: Mapped[str] = mapped_column(String(50), nullable=False, default="tech", index=True)

    # Engagement metrics (as collected from source)
    read_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)

    # Fingerprint for dedup
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=True, unique=True, index=True)

    # Whether this item has been used for article generation
    used_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, default=None)
