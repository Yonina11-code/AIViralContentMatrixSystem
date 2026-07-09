"""Domain 模型 — 领域配置（关键词、RSS 源）"""

from datetime import datetime

from sqlalchemy import Column, DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "tech"
    label: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "科技行业"
    folo_keywords: Mapped[list] = mapped_column(JSON, default=list)
    search_keywords: Mapped[list] = mapped_column(JSON, default=list)
    rss_feed_urls: Mapped[list] = mapped_column(JSON, default=list)
    wechat_ids: Mapped[list] = mapped_column(JSON, default=list)
    xiaohongshu_ids: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
