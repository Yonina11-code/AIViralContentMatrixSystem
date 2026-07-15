from datetime import datetime
from typing import Any


def compute_asset_performance(articles: list[Any]) -> dict[str, dict]:
    """Compute weighted performance by asset id from published article traces."""
    perf: dict[str, dict] = {}
    for article in articles:
        if _public_status(article) != "published":
            continue
        asset_ids = _extract_assets_used(getattr(article, "agent_trace", None))
        if not asset_ids:
            continue
        reads = _to_int(getattr(article, "read_count", 0))
        shares = _to_int(getattr(article, "share_count", 0))
        favorites = _to_int(getattr(article, "favorite_count", 0))
        article_score = reads + shares * 8 + favorites * 5
        for asset_id in asset_ids:
            row = perf.setdefault(asset_id, {
                "usage_count": 0,
                "total_reads": 0,
                "total_shares": 0,
                "total_favorites": 0,
                "score": 0.0,
            })
            row["usage_count"] += 1
            row["total_reads"] += reads
            row["total_shares"] += shares
            row["total_favorites"] += favorites
            row["score"] += article_score

    for row in perf.values():
        usage = max(row["usage_count"], 1)
        row["avg_reads"] = round(row["total_reads"] / usage, 1)
        # Bayesian-ish damping: avoid one-hit templates dominating too hard.
        row["score"] = round((row["score"] / usage) * (usage / (usage + 2)), 1)
    return perf


def build_calendar_events(articles: list[Any], beat_schedule: dict[str, dict]) -> list[dict]:
    events: list[dict] = []
    for article in articles:
        published_at = getattr(article, "published_at", None)
        scheduled_at = getattr(article, "scheduled_publish_at", None)
        if isinstance(published_at, datetime):
            events.append({
                "id": getattr(article, "id", ""),
                "type": "published_article",
                "title": getattr(article, "title", ""),
                "time": published_at.isoformat(),
                "status": _public_status(article),
            })
        if isinstance(scheduled_at, datetime):
            events.append({
                "id": getattr(article, "id", ""),
                "type": "scheduled_article",
                "title": getattr(article, "title", ""),
                "time": scheduled_at.isoformat(),
                "status": _public_status(article),
            })

    for name, cfg in beat_schedule.items():
        task = cfg.get("task", "")
        if not task:
            continue
        events.append({
            "id": name,
            "type": "collection_job" if "collect" in task else "background_job",
            "title": _task_label(name, task),
            "time": None,
            "status": "active",
            "interval_seconds": cfg.get("schedule"),
            "task": task,
        })

    events.sort(key=lambda event: event.get("time") or "9999-12-31T23:59:59")
    return events


def _extract_assets_used(agent_trace: Any) -> list[str]:
    if not isinstance(agent_trace, list):
        return []
    for trace in agent_trace:
        if isinstance(trace, dict) and isinstance(trace.get("assets_used"), list):
            return [str(x) for x in trace["assets_used"] if x]
    return []


def _public_status(article: Any) -> str:
    status = getattr(article, "status", "")
    value = getattr(status, "value", None) or str(status)
    return value.lower()


def _task_label(name: str, task: str) -> str:
    if task.endswith("collect_zhihu"):
        return "知乎定时采集"
    if task.endswith("collect_wechat"):
        return "微信定时采集"
    if task.endswith("collect_rss"):
        return "RSS 定时采集"
    if task.endswith("collect_search"):
        return "搜索引擎定时采集"
    if task.endswith("sync_wechat_stats"):
        return "微信数据回读"
    return name.replace("-", " ")


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
