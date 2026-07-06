import hashlib
from datetime import datetime
from urllib.parse import quote_plus

import httpx

from app.collectors.base import DataCollector, ContentItemData
from app.config import settings


class SearchEngineCollector(DataCollector):
    """搜索引擎采集器（Google Custom Search API）"""

    def get_source_name(self) -> str:
        return "search_engine"

    async def collect(self, keywords: list[str] | None = None, *, domain: str = "tech", max_per_keyword: int | None = None, **kwargs) -> list[ContentItemData]:
        api_key = settings.google_api_key
        cse_id = settings.google_cse_id
        if not api_key or not cse_id:
            print("[SearchEngineCollector] Google API key or CSE ID not configured")
            return []

        words = keywords or settings.search_keywords
        results: list[ContentItemData] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for keyword in words:
                keyword_count = 0
                try:
                    resp = await client.get(
                        "https://www.googleapis.com/customsearch/v1",
                        params={
                            "key": api_key,
                            "cx": cse_id,
                            "q": keyword,
                            "num": 10,
                            "lr": "lang_zh-CN",
                        },
                    )
                    if resp.status_code != 200:
                        print(f"[SearchEngineCollector] API error for '{keyword}': {resp.status_code}")
                        continue

                    data = resp.json()
                    for item in data.get("items", []):
                        if max_per_keyword and keyword_count >= max_per_keyword:
                            break
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        link = item.get("link", "")
                        source_name = item.get("displayLink", "")

                        fingerprint = hashlib.md5(f"{title}{link}".encode()).hexdigest()

                        results.append(ContentItemData(
                            title=title,
                            summary=snippet,
                            body=snippet,
                            url=link,
                            source="search_engine",
                            source_name=source_name,
                            fingerprint=fingerprint,
                            domain=domain,
                        ))
                        keyword_count += 1
                except Exception as e:
                    print(f"[SearchEngineCollector] Failed for '{keyword}': {e}")

        return results
