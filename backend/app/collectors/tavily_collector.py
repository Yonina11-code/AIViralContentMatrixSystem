import hashlib
import httpx
from app.collectors.base import DataCollector, ContentItemData
from app.config import settings

class TavilyCollector(DataCollector):
    """Tavily AI 搜索引擎采集器 (更适合国内自媒体/养生科普的精准全文匹配)"""

    def get_source_name(self) -> str:
        return "tavily"

    async def collect(self, keywords: list[str] | None = None, *, domain: str = "tech", max_per_keyword: int | None = None, **kwargs) -> list[ContentItemData]:
        api_key = settings.tavily_api_key
        
        if not api_key:
            import os
            api_key = os.environ.get("TAVILY_API_KEY")

        if not api_key:
            print("[TavilyCollector] TAVILY_API_KEY not configured. Using fallback dummy data or skipped.")
            return []

        words = keywords or []
        if not words:
            return []

        results: list[ContentItemData] = []
        limit = max_per_keyword or 10

        async with httpx.AsyncClient(timeout=30) as client:
            for keyword in words:
                try:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": keyword,
                            "search_depth": "advanced",
                            "include_answer": False,
                            "max_results": limit,
                        }
                    )
                    if resp.status_code != 200:
                        print(f"[TavilyCollector] API error for '{keyword}': {resp.status_code} {resp.text}")
                        continue

                    data = resp.json()
                    for item in data.get("results", []):
                        title = item.get("title", "")
                        content = item.get("content", "")
                        url = item.get("url", "")
                        
                        if not title:
                            continue

                        fingerprint_str = f"{title}{url}"
                        fingerprint = hashlib.md5(fingerprint_str.encode()).hexdigest()

                        results.append(ContentItemData(
                            title=title,
                            summary=content[:300] if content else "",
                            body=content,
                            url=url,
                            source="search_engine", # 前端为了统一图标显示为搜索引擎，但也可以标为 "tavily"
                            source_name="Tavily AI搜索",
                            fingerprint=fingerprint,
                            domain=domain,
                        ))
                except Exception as e:
                    print(f"[TavilyCollector] Failed for '{keyword}': {e}")

        return results
