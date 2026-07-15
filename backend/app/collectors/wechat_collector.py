import hashlib
import logging
import re
from datetime import datetime
from html import unescape
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx

from app.collectors.base import ContentItemData, DataCollector

logger = logging.getLogger(__name__)


class WeChatArticleCollector(DataCollector):
    """微信公众号外部文章采集器。

    采集链路：
    1. 搜狗微信搜索发现文章；
    2. 解析搜狗中间页拼接出的 mp.weixin.qq.com 真实链接；
    3. 解析微信文章页正文与基础元数据。
    """

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    )
    MIN_SEARCH_QUALITY_SCORE = 55

    CREDIBLE_SOURCE_HINTS = (
        "医院", "卫健", "疾控", "医生", "药师", "营养师", "中国中医药报",
        "第十一诊室", "丁香", "赛柏蓝", "官方", "大学附属医院",
    )
    LOW_TRUST_SOURCE_HINTS = ("偏方", "秘方", "大全", "祖传", "土方", "食疗大全")
    RISK_TERMS = (
        "偏方", "秘方", "祖传", "根治", "治愈", "包治", "特效", "神奇",
        "排毒", "防癌", "抗癌", "活到九十", "三百口",
    )
    HARD_RISK_TERMS = ("偏方", "秘方", "祖传", "根治", "治愈", "包治", "特效")
    DEBUNK_TERMS = ("误区", "辟谣", "真相", "深信不疑", "你排毒了吗", "科学")
    TOPIC_TERMS = {
        "饮食误区": ("饮食误区", "膳食指南", "糖尿病饮食", "控糖", "主食", "孕期饮食"),
        "慢病调理": ("糖尿病", "高血压", "血糖", "尿酸", "多囊", "慢病"),
        "日常调理": ("日常调理", "肠道", "过敏", "睡眠", "失眠", "运动"),
        "中医养生": ("中医", "国医", "节气", "三伏", "黄帝内经", "穴位"),
        "健康科普": ("科普", "医生", "药师", "医院", "指南", "建议"),
        "伪养生辟谣": ("排毒", "误区", "谣言", "辟谣", "真相"),
    }

    def get_source_name(self) -> str:
        return "wechat"

    async def collect(
        self,
        *,
        keywords: list[str] | None = None,
        urls: list[str] | None = None,
        domain: str = "tech",
        max_per_keyword: int | None = None,
        min_quality_score: int | None = None,
        **kwargs,
    ) -> list[ContentItemData]:
        results: list[ContentItemData] = []
        seen_urls: set[str] = set()
        min_quality = self.MIN_SEARCH_QUALITY_SCORE if min_quality_score is None else min_quality_score

        async with httpx.AsyncClient(
            timeout=30,
            headers={
                "User-Agent": self.USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
        ) as client:
            for article_url in urls or []:
                item = await self.fetch_article(client, article_url, domain=domain)
                if item and item.url not in seen_urls:
                    results.append(item)
                    seen_urls.add(item.url or "")

            for keyword in keywords or []:
                keyword_count = 0
                try:
                    search_html = await self.fetch_text(
                        client,
                        f"https://weixin.sogou.com/weixin?type=2&query={quote(keyword)}",
                        referer="https://weixin.sogou.com/",
                    )
                    for result in self.parse_sogou_search_results(search_html):
                        if max_per_keyword and keyword_count >= max_per_keyword:
                            break
                        article_url = await self.resolve_sogou_result(client, result["url"])
                        if not article_url or article_url in seen_urls:
                            continue
                        item = await self.fetch_article(client, article_url, domain=domain)
                        if item:
                            if not item.summary and result.get("summary"):
                                item.summary = result["summary"]
                            if self.is_search_collectable(item, min_quality_score=min_quality):
                                results.append(item)
                                seen_urls.add(article_url)
                                keyword_count += 1
                            else:
                                logger.info(
                                    "[WeChatArticleCollector] dropped low-quality article score=%s title=%s",
                                    self.evaluate_quality(item)["score"],
                                    item.title,
                                )
                except Exception as e:
                    logger.warning("[WeChatArticleCollector] keyword=%s failed: %s", keyword, e)

        return sorted(results, key=lambda item: self.evaluate_quality(item)["score"], reverse=True)

    async def fetch_text(self, client: httpx.AsyncClient, url: str, *, referer: str | None = None) -> str:
        headers = {"Referer": referer} if referer else None
        resp = await client.get(self.safe_url(url), headers=headers)
        resp.raise_for_status()
        return resp.text

    async def resolve_sogou_result(self, client: httpx.AsyncClient, url: str) -> str | None:
        if "mp.weixin.qq.com/" in url:
            return url
        html = await self.fetch_text(client, url, referer="https://weixin.sogou.com/")
        parsed = self.parse_sogou_redirect_url(html)
        if parsed:
            return parsed
        return None

    async def fetch_article(
        self,
        client: httpx.AsyncClient,
        article_url: str,
        *,
        domain: str,
    ) -> ContentItemData | None:
        html = await self.fetch_text(client, article_url, referer="https://weixin.sogou.com/")
        return self.parse_wechat_article(html, article_url=article_url, domain=domain)

    def parse_sogou_search_results(self, html: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        blocks = re.findall(r'<li[^>]*id="sogou_vr_.*?</li>', html, re.S)
        for block in blocks:
            title_match = re.search(r'<h3>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not title_match:
                continue
            summary_match = re.search(r'<p class="txt-info"[^>]*>(.*?)</p>', block, re.S)
            title = self.clean_text(title_match.group(2))
            summary = self.clean_text(summary_match.group(1)) if summary_match else ""
            url = urljoin("https://weixin.sogou.com", unescape(title_match.group(1)))
            if title and url:
                results.append({"title": title, "summary": summary, "url": self.safe_url(url)})
        return results

    def parse_sogou_redirect_url(self, html: str) -> str | None:
        parts = re.findall(r"url \+= '([^']*)';", html)
        if not parts:
            redirect_match = re.search(r'window\.location\.replace\(["\']([^"\']+)["\']\)', html)
            return unescape(redirect_match.group(1)) if redirect_match else None
        url = "".join(parts).replace("@", "")
        return url if url.startswith("https://mp.weixin.qq.com/") else None

    def parse_wechat_article(
        self,
        html: str,
        *,
        article_url: str,
        domain: str,
    ) -> Optional[ContentItemData]:
        if any(marker in html for marker in ("请输入验证码", "访问频率", "环境异常")):
            logger.warning("[WeChatArticleCollector] blocked while parsing %s", article_url)
            return None

        title = (
            self.extract_var_text(html, "msg_title")
            or self.extract_meta(html, "og:title", attr="property")
            or self.extract_title_tag(html)
        )
        title = self.clean_text(title)
        if not title:
            return None

        content_html = self.extract_js_content(html)
        body = self.clean_text(content_html)
        if not body:
            return None

        summary = (
            self.extract_html_decode_var(html, "msg_desc")
            or self.extract_meta(html, "description", attr="name")
        )
        source_name = self.extract_source_name(html)
        published_at = self.extract_published_at(html)
        fingerprint = self.build_fingerprint(
            title=title,
            source_name=source_name or "微信公众号",
            published_at=published_at,
            body=body,
        )

        item = ContentItemData(
            title=title,
            body=body,
            summary=self.clean_text(summary)[:500] if summary else body[:200],
            url=article_url,
            source="wechat",
            source_name=source_name or "微信公众号",
            author=None,
            tags=["wechat"],
            published_at=published_at,
            fingerprint=fingerprint,
            domain=domain,
        )
        item.tags = self.build_quality_tags(item)
        return item

    def evaluate_quality(self, item: ContentItemData) -> dict:
        title = item.title or ""
        body = item.body or ""
        summary = item.summary or ""
        source_name = item.source_name or ""
        text = f"{title} {summary} {body[:3000]}"
        score = 50
        reasons: list[str] = []

        if any(hint in source_name for hint in self.CREDIBLE_SOURCE_HINTS):
            score += 15
            reasons.append("credible_source")
        if any(hint in source_name for hint in self.LOW_TRUST_SOURCE_HINTS):
            score -= 22
            reasons.append("low_trust_source")

        body_len = len(body)
        if 1200 <= body_len <= 6000:
            score += 12
            reasons.append("usable_length")
        elif body_len < 900:
            score -= 10
            reasons.append("too_short")
        elif body_len > 9000:
            score -= 8
            reasons.append("too_long")

        if item.published_at:
            year = item.published_at.year
            if year >= 2023:
                score += 10
                reasons.append("recent")
            elif year >= 2020:
                score += 3
                reasons.append("not_old")
            elif year <= 2018:
                score -= 10
                reasons.append("old")

        topics = self.detect_topics(text)
        if topics:
            score += min(12, len(topics) * 4)
            reasons.append("topic_matched")

        if any(term in title for term in ("误区", "科普", "指南", "调理", "真相", "辟谣")):
            score += 8
            reasons.append("useful_title_intent")

        risks = self.detect_risks(text)
        debunk_context = any(term in text for term in self.DEBUNK_TERMS)
        for risk in risks:
            if risk == "排毒" and debunk_context:
                score += 3
                reasons.append("debunk_context")
                continue
            score -= 10 if risk in self.HARD_RISK_TERMS else 5
        if risks:
            reasons.append("risk_terms")

        return {
            "score": max(0, min(100, score)),
            "topics": topics,
            "risks": risks,
            "reasons": reasons,
        }

    def is_search_collectable(self, item: ContentItemData, *, min_quality_score: int | None = None) -> bool:
        quality = self.evaluate_quality(item)
        min_quality = self.MIN_SEARCH_QUALITY_SCORE if min_quality_score is None else min_quality_score
        source_name = item.source_name or ""
        hard_risk_count = sum(1 for risk in quality["risks"] if risk in self.HARD_RISK_TERMS)
        low_trust_source = any(hint in source_name for hint in self.LOW_TRUST_SOURCE_HINTS)
        if low_trust_source and hard_risk_count:
            return False
        return quality["score"] >= min_quality

    def build_quality_tags(self, item: ContentItemData) -> list[str]:
        quality = self.evaluate_quality(item)
        tags = ["wechat", f"quality:{quality['score']}"]
        tags.extend(f"topic:{topic}" for topic in quality["topics"][:3])
        tags.extend(f"risk:{risk}" for risk in quality["risks"][:3])
        return tags

    def build_fingerprint(
        self,
        *,
        title: str,
        source_name: str,
        published_at: datetime | None,
        body: str,
    ) -> str:
        published_key = published_at.strftime("%Y-%m-%d") if published_at else ""
        body_key = hashlib.md5(body[:2000].encode("utf-8")).hexdigest() if body else ""
        base = "|".join([
            "wechat",
            self.clean_text(source_name).lower(),
            self.clean_text(title).lower(),
            published_key,
            body_key,
        ])
        return hashlib.md5(base.encode("utf-8")).hexdigest()

    def detect_topics(self, text: str) -> list[str]:
        return [topic for topic, terms in self.TOPIC_TERMS.items() if any(term in text for term in terms)]

    def detect_risks(self, text: str) -> list[str]:
        return [term for term in self.RISK_TERMS if term in text]

    def extract_js_content(self, html: str) -> str:
        match = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>\s*<script', html, re.S)
        if not match:
            match = re.search(r'<div[^>]+id="js_content"[^>]*>(.*?)</div>', html, re.S)
        return match.group(1) if match else ""

    def extract_source_name(self, html: str) -> str | None:
        match = re.search(r'id="js_name"[^>]*>(.*?)</a>', html, re.S)
        if match:
            return self.clean_text(match.group(1))
        match = re.search(r'class="rich_media_meta[^"]*nickname[^"]*"[^>]*>(.*?)</span>', html, re.S)
        return self.clean_text(match.group(1)) if match else None

    def extract_published_at(self, html: str) -> datetime | None:
        match = re.search(r"create_time:\s*'([^']+)'", html)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                pass
        match = re.search(r"%22publish_time%22%3A(\d+)", html)
        if match:
            try:
                return datetime.fromtimestamp(int(match.group(1)))
            except (ValueError, OSError):
                pass
        return None

    def extract_var_text(self, html: str, name: str) -> str | None:
        match = re.search(rf"var {re.escape(name)} = '([^']*)'(?:\.html\(false\))?;", html)
        return unescape(match.group(1)) if match else None

    def extract_html_decode_var(self, html: str, name: str) -> str | None:
        match = re.search(rf'var {re.escape(name)} = htmlDecode\("([^"]*)"\);', html)
        return unescape(match.group(1)) if match else None

    def extract_quoted_var(self, html: str, name: str) -> str | None:
        match = re.search(rf'var {re.escape(name)} = "([^"]*)";', html)
        return unescape(match.group(1)) if match else None

    def extract_meta(self, html: str, key: str, *, attr: str) -> str | None:
        match = re.search(
            rf'<meta[^>]+{attr}="{re.escape(key)}"[^>]+content="([^"]*)"',
            html,
            re.I,
        )
        return unescape(match.group(1)) if match else None

    def extract_title_tag(self, html: str) -> str | None:
        match = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
        return unescape(match.group(1)) if match else None

    def clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        text = re.sub(r"<[^>]+>", "", value)
        text = unescape(text)
        text = text.replace("\xa0", " ")
        return re.sub(r"\s+", " ", text).strip()

    def safe_url(self, url: str) -> str:
        split = urlsplit(url)
        return urlunsplit(
            (
                split.scheme,
                split.netloc,
                quote(split.path, safe="/"),
                quote(split.query, safe="=&%._-"),
                split.fragment,
            )
        )
