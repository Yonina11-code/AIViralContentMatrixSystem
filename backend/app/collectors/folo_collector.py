"""Folo 采集器 — 基于 Folo CLI 的智能数据源发现与内容采集

Folo (https://folo.is) 是一个 AI RSS 阅读器，支持 24+ 平台的数据源，
包括 RSS、小红书、知乎、B站、微博等。

采集模式：
1. 搜索发现模式：根据关键词搜索数据源，自动订阅并获取内容
2. 时间线模式：从已订阅的数据源拉取最新内容
"""

import hashlib
import json
import logging
import subprocess
from datetime import datetime
from typing import Optional

from app.collectors.base import DataCollector, ContentItemData

logger = logging.getLogger(__name__)

FOLOCLI = "npx --yes folocli@latest"
_FOLO_AUTH_CHECKED = False


def _ensure_folo_auth() -> bool:
    """确保 Folo 已登录，返回 True 表示已认证"""
    global _FOLO_AUTH_CHECKED
    if _FOLO_AUTH_CHECKED:
        return True
    try:
        result = subprocess.run(
            f"{FOLOCLI} whoami",
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        data = json.loads(result.stdout)
        if data.get("ok") and data.get("data", {}).get("user"):
            _FOLO_AUTH_CHECKED = True
            return True
        logger.warning("Folo 未登录，请运行 `folocli login`")
        return False
    except Exception as e:
        logger.warning(f"Folo 认证检查失败: {e}")
        return False


class FoloCollector(DataCollector):
    """Folo 智能数据源采集器"""

    def get_source_name(self) -> str:
        return "folo"

    async def collect(
        self,
        *,
        search_keywords: list[str] | None = None,
        domain: str = "tech",
        max_per_keyword: int | None = None,
        **kwargs,
    ) -> list[ContentItemData]:
        """
        使用 Folo 搜索发现数据源并采集内容。

        Args:
            search_keywords: 搜索关键词列表，用于发现数据源。如果为 None 则跳过搜索。
            domain: 内容领域标识。
        """
        if not _ensure_folo_auth():
            return []

        keywords = search_keywords or []
        if not keywords:
            logger.info(f"[FoloCollector] domain={domain} 未配置搜索关键词，跳过")
            return []

        results: list[ContentItemData] = []

        for keyword in keywords:
            keyword_count = 0
            try:
                feeds = self._search_feeds(keyword)
                for feed_info in feeds:
                    if max_per_keyword and keyword_count >= max_per_keyword:
                        break
                    feed_title = feed_info.get("feed", {}).get("title", "") or ""
                    feed_url = feed_info.get("feed", {}).get("url", "") or ""

                    if feed_url:
                        self._subscribe(feed_url)

                    entries = feed_info.get("entries", [])
                    for entry in entries:
                        if max_per_keyword and keyword_count >= max_per_keyword:
                            break
                        item = self._entry_to_item(entry, feed_title, feed_url, domain)
                        if item:
                            results.append(item)
                            keyword_count += 1

                    logger.info(
                        f"[FoloCollector] keyword={keyword} feed={feed_title} "
                        f"entries={len(entries)}"
                    )
            except Exception as e:
                logger.error(f"[FoloCollector] keyword={keyword} 搜索失败: {e}")

        return results

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _search_feeds(self, keyword: str) -> list[dict]:
        """通过 Folo CLI 搜索数据源"""
        cmd = f'{FOLOCLI} search discover "{keyword}"'
        try:
            raw = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            data = json.loads(raw.stdout)
            if data.get("ok"):
                return data.get("data", [])
            logger.warning(f"Folo discover 返回异常: {data.get('error')}")
        except json.JSONDecodeError:
            logger.error(f"Folo discover 返回非 JSON: {raw.stdout[:200]}")
        except subprocess.TimeoutExpired:
            logger.error(f"Folo discover 超时 (keyword={keyword})")
        except Exception as e:
            logger.error(f"Folo discover 异常: {e}")
        return []

    def _subscribe(self, feed_url: str) -> bool:
        """订阅数据源，重复订阅会自动忽略"""
        cmd = f'{FOLOCLI} subscription add --feed "{feed_url}"'
        try:
            raw = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=15
            )
            data = json.loads(raw.stdout)
            return data.get("ok", False)
        except Exception:
            return False

    def _entry_to_item(
        self,
        entry: dict,
        feed_title: str,
        feed_url: str,
        domain: str,
    ) -> Optional[ContentItemData]:
        """将 Folo 条目转换为 ContentItemData"""
        title = (entry.get("title") or "").strip()
        if not title:
            return None

        entry_url = entry.get("url") or ""
        unique_id = entry.get("id") or ""
        content_html = entry.get("content") or ""
        summary = entry.get("description") or ""

        # 尝试提取纯文本摘要
        plain_summary = summary[:500] if summary else ""
        if not plain_summary and content_html:
            # 简单去除 HTML 标签
            import re
            plain_summary = re.sub(r"<[^>]+>", "", content_html)[:500]

        # 发布日期
        published_at = None
        pub_str = entry.get("publishedAt") or entry.get("publishedAt")
        if pub_str:
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # 作者
        author = entry.get("author") or None

        # 指纹（去重用）
        fingerprint_str = f"{title}{entry_url or unique_id}"
        fingerprint = hashlib.md5(fingerprint_str.encode()).hexdigest()

        return ContentItemData(
            title=title,
            body=content_html or summary,
            summary=plain_summary,
            url=entry_url,
            source="folo",
            source_name=feed_title or "Folo",
            author=author,
            published_at=published_at,
            fingerprint=fingerprint,
            domain=domain,
        )
