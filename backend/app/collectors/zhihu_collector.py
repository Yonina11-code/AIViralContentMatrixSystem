import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime
from html import unescape
from typing import Any

import httpx

from app.collectors.base import ContentItemData, DataCollector
from app.config import settings

logger = logging.getLogger(__name__)


class ZhihuCollector(DataCollector):
    """知乎官方开放平台采集器。

    使用 developer.zhihu.com 的 Bearer Access Secret 调用站内搜索和热榜 API。
    """

    API_BASE = "https://developer.zhihu.com/api/v1/content"
    RATE_LIMIT_CODE = 30001

    def __init__(
        self,
        access_secret: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        request_interval: float = 1.1,
    ):
        self.access_secret = access_secret if access_secret is not None else settings.zhihu_access_secret
        self.transport = transport
        self.request_interval = request_interval

    def get_source_name(self) -> str:
        return "zhihu"

    async def collect(
        self,
        *,
        keywords: list[str] | None = None,
        domain: str = "tech",
        max_per_keyword: int | None = None,
        hot_list: bool = False,
        hot_limit: int = 30,
        **kwargs,
    ) -> list[ContentItemData]:
        if not self.access_secret:
            logger.warning("[ZhihuCollector] zhihu_access_secret 未配置，跳过知乎采集")
            return []

        results: list[ContentItemData] = []
        seen: set[str] = set()

        async with httpx.AsyncClient(timeout=30, transport=self.transport) as client:
            if hot_list:
                for item in await self.fetch_hot_list(client, limit=hot_limit, domain=domain):
                    self._append_unique(results, seen, item)

            for keyword in keywords or []:
                count = max_per_keyword or 10
                for item in await self.fetch_search(client, query=keyword, count=count, domain=domain):
                    self._append_unique(results, seen, item)
                if self.request_interval:
                    await asyncio.sleep(self.request_interval)

        return results

    async def fetch_search(
        self,
        client: httpx.AsyncClient,
        *,
        query: str,
        count: int,
        domain: str,
    ) -> list[ContentItemData]:
        count = max(1, min(count, 10))
        data = await self._get(
            client,
            "/zhihu_search",
            params={"Query": query, "Count": count},
        )
        if not data:
            return []

        items = data.get("Items") or []
        return [
            item
            for raw in items
            if (item := self._search_item_to_content(raw, domain=domain))
        ]

    async def fetch_hot_list(
        self,
        client: httpx.AsyncClient,
        *,
        limit: int,
        domain: str,
    ) -> list[ContentItemData]:
        limit = max(1, min(limit, 30))
        data = await self._get(client, "/hot_list", params={"Limit": limit})
        if not data:
            return []

        items = data.get("Items") or []
        return [
            item
            for raw in items
            if (item := self._hot_item_to_content(raw, domain=domain))
        ]

    async def _get(self, client: httpx.AsyncClient, path: str, *, params: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Authorization": f"Bearer {self.access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        }
        resp = await client.get(f"{self.API_BASE}{path}", params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        code = payload.get("Code")
        if code == 0:
            return payload.get("Data") or {}
        if code == self.RATE_LIMIT_CODE:
            logger.warning("[ZhihuCollector] rate limited: %s", payload.get("Message"))
            return None
        logger.warning("[ZhihuCollector] api error code=%s message=%s", code, payload.get("Message"))
        return None

    def _search_item_to_content(self, raw: dict[str, Any], *, domain: str) -> ContentItemData | None:
        title = self.clean_text(raw.get("Title") or "")
        url = raw.get("Url") or ""
        body = self.clean_text(raw.get("ContentText") or "")
        if not title or not url:
            return None

        content_type = raw.get("ContentType") or "Unknown"
        authority = str(raw.get("AuthorityLevel") or "")
        author = raw.get("AuthorName") or None
        edit_time = self._timestamp_to_datetime(raw.get("EditTime"))
        comment_count = self._to_int(raw.get("CommentCount"))
        vote_count = self._to_int(raw.get("VoteUpCount"))
        fingerprint = self._fingerprint(raw.get("ContentID") or url or title)
        comments = raw.get("CommentInfoList") or []
        tags = ["zhihu", f"type:{content_type}"]
        if authority:
            tags.append(f"authority:{authority}")
        if comments:
            tags.append("has_featured_comments")

        return ContentItemData(
            title=title,
            body=body,
            summary=body[:500] if body else title,
            url=url,
            source="zhihu",
            source_name="知乎",
            author=author,
            tags=tags,
            published_at=edit_time,
            like_count=vote_count,
            comment_count=comment_count,
            fingerprint=fingerprint,
            domain=domain,
        )

    def _hot_item_to_content(self, raw: dict[str, Any], *, domain: str) -> ContentItemData | None:
        title = self.clean_text(raw.get("Title") or "")
        url = raw.get("Url") or ""
        summary = self.clean_text(raw.get("Summary") or "")
        if not title or not url:
            return None

        return ContentItemData(
            title=title,
            body=summary,
            summary=summary[:500] if summary else title,
            url=url,
            source="zhihu",
            source_name="知乎热榜",
            tags=["zhihu", "zhihu_hot"],
            fingerprint=self._fingerprint(url),
            domain=domain,
        )

    def clean_text(self, text: str) -> str:
        text = unescape(text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _append_unique(self, results: list[ContentItemData], seen: set[str], item: ContentItemData) -> None:
        key = item.fingerprint or item.url or item.title
        if key in seen:
            return
        results.append(item)
        seen.add(key)

    def _fingerprint(self, value: str) -> str:
        return hashlib.md5(f"zhihu:{value}".encode("utf-8")).hexdigest()

    def _timestamp_to_datetime(self, value: Any) -> datetime | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(timestamp) if timestamp > 0 else None

    def _to_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
