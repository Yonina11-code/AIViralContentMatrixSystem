from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ContentItemData:
    title: str
    body: str | None = None
    summary: str | None = None
    url: str | None = None
    source: str = "unknown"
    source_name: str | None = None
    author: str | None = None
    tags: list[str] | None = None
    published_at: datetime | None = None
    read_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0
    fingerprint: str | None = None
    domain: str = "tech"


class DataCollector(ABC):
    """所有数据源采集器的抽象接口"""

    @abstractmethod
    async def collect(self, **kwargs) -> list[ContentItemData]:
        """执行采集，返回内容条目列表"""
        ...

    @abstractmethod
    def get_source_name(self) -> str:
        """返回数据源名称标识"""
        ...
