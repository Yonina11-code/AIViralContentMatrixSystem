import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


RISK_TERMS = ("偏方", "秘方", "祖传", "根治", "治愈", "包治", "特效", "神奇", "排毒")
HARD_RISK_TERMS = ("偏方", "秘方", "祖传", "根治", "治愈", "包治", "特效")
HEALTH_TERMS = ("糖尿病", "控糖", "高血压", "尿酸", "睡眠", "饮食", "医生", "科普", "指南", "营养")
AI_TERMS = ("AI", "人工智能", "大模型", "工具", "自媒体", "内容创作", "提示词")
LIFE_TERMS = ("生活", "习惯", "误区", "常识", "避坑", "清洁", "收纳")


def score_material(item: Any) -> dict:
    """Score a content pool item for editorial usefulness."""
    text = _item_text(item)
    source = (getattr(item, "source", "") or "").lower()
    source_name = getattr(item, "source_name", "") or ""
    tags = getattr(item, "tags", None) or []
    score = 50
    reasons: list[str] = []

    if source in {"zhihu", "wechat"}:
        score += 8
        reasons.append("platform_signal")
    if any(isinstance(tag, str) and tag.startswith("quality:") for tag in tags):
        quality = _extract_quality(tags)
        score += max(-20, min(20, int((quality - 70) / 2)))
        reasons.append("collector_quality")
    if any(term in source_name for term in ("医院", "医生", "卫健", "疾控", "官方", "知乎")):
        score += 8
        reasons.append("credible_source")

    engagement = _to_int(getattr(item, "like_count", 0)) + _to_int(getattr(item, "comment_count", 0)) * 2
    if engagement >= 50:
        score += min(16, int(math.log10(engagement + 1) * 7))
        reasons.append("engagement_signal")

    body_len = len(getattr(item, "body", "") or getattr(item, "summary", "") or "")
    if 180 <= body_len <= 6000:
        score += 8
        reasons.append("usable_length")
    elif body_len < 80:
        score -= 10
        reasons.append("thin_content")

    published_at = getattr(item, "published_at", None) or getattr(item, "collected_at", None)
    if isinstance(published_at, datetime):
        if published_at.year >= 2025:
            score += 8
            reasons.append("recent")
        elif published_at.year <= 2020:
            score -= 8
            reasons.append("stale")

    topics = detect_topics(text)
    if topics:
        score += min(10, len(topics) * 4)
        reasons.append("topic_matched")

    risks = [term for term in RISK_TERMS if term in text]
    hard_risks = [term for term in HARD_RISK_TERMS if term in text]
    debunk_context = any(term in text for term in ("不要相信", "别信", "辟谣", "误区", "不可靠"))
    if hard_risks and not debunk_context:
        score -= 28
        reasons.append("hard_risk_terms")
    elif risks and not debunk_context:
        score -= 10
        reasons.append("risk_terms")
    elif risks:
        score += 4
        reasons.append("debunk_context")

    return {
        "score": max(0, min(100, score)),
        "reasons": reasons,
        "topics": topics,
        "risks": risks[:5],
    }


def detect_topics(text: str) -> list[str]:
    topics = []
    if any(term in text for term in HEALTH_TERMS):
        topics.append("健康科普")
    if any(term in text for term in AI_TERMS):
        topics.append("AI工具")
    if any(term in text for term in LIFE_TERMS):
        topics.append("生活常识")
    if "误区" in text or "别再" in text or "不要信" in text:
        topics.append("误区辟谣")
    return topics


def content_similarity(a: Any, b: Any) -> float:
    a_tokens = _tokens(_item_text(a))
    b_tokens = _tokens(_item_text(b))
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return overlap / union if union else 0.0


def build_material_insights(items: list[Any]) -> list[dict]:
    insights: list[dict] = []
    representatives: list[tuple[Any, dict]] = []
    for item in items:
        quality = score_material(item)
        duplicate_of = None
        for rep_item, rep in representatives:
            if content_similarity(item, rep_item) >= 0.72:
                duplicate_of = rep["id"]
                break

        insight = {
            "id": getattr(item, "id", ""),
            "title": getattr(item, "title", ""),
            "source": getattr(item, "source", ""),
            "source_name": getattr(item, "source_name", None),
            "score": quality["score"],
            "reasons": quality["reasons"],
            "topics": quality["topics"],
            "risks": quality["risks"],
            "duplicate_group": bool(duplicate_of),
            "duplicate_of": duplicate_of,
        }
        insights.append(insight)
        if not duplicate_of:
            representatives.append((item, insight))
    return insights


def build_topic_cards(items: list[Any], *, limit: int = 6) -> list[dict]:
    clusters: dict[str, list[Any]] = defaultdict(list)
    for item in items:
        topics = score_material(item)["topics"] or ["综合选题"]
        clusters[topics[0]].append(item)

    cards = []
    for topic, group in clusters.items():
        scored = sorted(group, key=lambda x: score_material(x)["score"], reverse=True)
        avg_score = round(sum(score_material(x)["score"] for x in scored) / max(len(scored), 1), 1)
        sources = dict(Counter((getattr(x, "source", "") or "unknown") for x in scored))
        titles = [getattr(x, "title", "") for x in scored[:3]]
        cards.append({
            "topic": topic,
            "suggested_angle": _suggest_angle(topic, titles),
            "why_now": _why_now(topic, sources, avg_score),
            "material_count": len(scored),
            "avg_quality": avg_score,
            "sources": sources,
            "item_ids": [getattr(x, "id", "") for x in scored[:5] if getattr(x, "id", "")],
            "sample_titles": titles,
            "outline": _outline(topic),
        })

    cards.sort(key=lambda x: (x["avg_quality"], x["material_count"]), reverse=True)
    return cards[:limit]


def _suggest_angle(topic: str, titles: list[str]) -> str:
    if topic == "健康科普":
        return "把高频误区拆成可执行的日常判断清单，强调边界和医生建议。"
    if topic == "AI工具":
        return "从真实工作流切入，比较工具在选题、写作、配图和复盘中的位置。"
    if topic == "误区辟谣":
        return "用一个反常识问题开头，逐条拆解为什么常见做法并不可靠。"
    return f"围绕「{topic}」提炼一个具体生活场景，给出读者能立刻使用的判断框架。"


def _why_now(topic: str, sources: dict[str, int], avg_score: float) -> str:
    source_label = "、".join(f"{k} {v} 条" for k, v in sources.items() if k)
    return f"当前内容池有 {source_label or '多来源'} 素材，平均质量分 {avg_score}，适合作为今日候选选题。"


def _outline(topic: str) -> list[str]:
    return [
        f"用一个具体场景引出「{topic}」的问题",
        "列出读者最容易踩中的 3 个判断误区",
        "结合素材给出可执行建议和边界提醒",
        "用清单式结尾引导收藏、转发或留言",
    ]


def _item_text(item: Any) -> str:
    return " ".join(str(x or "") for x in [
        getattr(item, "title", ""),
        getattr(item, "summary", ""),
        getattr(item, "body", ""),
        getattr(item, "source_name", ""),
    ])


def _tokens(text: str) -> set[str]:
    text = re.sub(r"<[^>]+>", "", text.lower())
    zh = set(re.findall(r"[\u4e00-\u9fff]{2,}", text))
    words = set(re.findall(r"[a-z0-9]{2,}", text))
    bigrams = {token[i:i + 2] for token in zh for i in range(max(len(token) - 1, 0))}
    return zh | words | bigrams


def _extract_quality(tags: list[Any]) -> int:
    for tag in tags:
        if isinstance(tag, str) and tag.startswith("quality:"):
            try:
                return int(tag.split(":", 1)[1])
            except ValueError:
                return 70
    return 70


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
