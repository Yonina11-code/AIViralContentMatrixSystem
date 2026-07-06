import hashlib
from datetime import datetime

import feedparser

from app.collectors.base import DataCollector, ContentItemData


class RSSCollector(DataCollector):
    """RSS feed 采集器"""

    def __init__(self, feed_urls: list[str] | None = None):
        self.feed_urls = feed_urls or []

    def get_source_name(self) -> str:
        return "rss"

    async def collect(self, feed_urls: list[str] | None = None, *, domain: str = "tech", max_items: int | None = None, **kwargs) -> list[ContentItemData]:
        urls = feed_urls or self.feed_urls
        results: list[ContentItemData] = []

        for url in urls:
            if max_items and len(results) >= max_items:
                break
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    if max_items and len(results) >= max_items:
                        break
                    title = entry.get("title", "")
                    body = entry.get("description") or entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""
                    link = entry.get("link", "")
                    author = entry.get("author", "")
                    published = entry.get("published_parsed")
                    published_at = datetime(*published[:6]) if published else None
                    tags = [t.get("term", "") for t in entry.get("tags", []) if t.get("term")]

                    fingerprint = hashlib.md5(f"{title}{link}".encode()).hexdigest()

                    results.append(ContentItemData(
                        title=title,
                        body=body,
                        summary=body[:300] if body else "",
                        url=link,
                        source="rss",
                        source_name=feed.feed.get("title", url),
                        author=author,
                        tags=tags,
                        published_at=published_at,
                        fingerprint=fingerprint,
                        domain=domain,
                    ))
            except Exception as e:
                print(f"[RSSCollector] Failed to parse {url}: {e}")

        return results
