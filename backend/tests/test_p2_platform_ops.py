import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.platform_ops import build_calendar_events, compute_asset_performance


def article(**kwargs):
    defaults = {
        "id": "a1",
        "title": "控糖饮食误区",
        "status": "PUBLISHED",
        "read_count": 1200,
        "share_count": 80,
        "favorite_count": 40,
        "published_at": datetime(2026, 7, 10, 9, 0),
        "scheduled_publish_at": None,
        "agent_trace": [{}, {"assets_used": ["asset-title", "asset-opening"]}],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class P2PlatformOpsTests(unittest.TestCase):
    def test_compute_asset_performance_scores_assets_from_published_articles(self):
        result = compute_asset_performance([
            article(read_count=1000, share_count=50, favorite_count=30),
            article(id="a2", read_count=300, share_count=5, favorite_count=5, agent_trace=[{}, {"assets_used": ["asset-title"]}]),
        ])

        title = result["asset-title"]
        opening = result["asset-opening"]
        self.assertEqual(title["usage_count"], 2)
        self.assertGreater(title["total_reads"], opening["total_reads"])
        self.assertEqual(opening["usage_count"], 1)

    def test_compute_asset_performance_ignores_unpublished_articles(self):
        result = compute_asset_performance([
            article(status="DRAFT", read_count=5000, agent_trace=[{}, {"assets_used": ["asset-title"]}])
        ])

        self.assertEqual(result, {})

    def test_build_calendar_events_includes_published_and_scheduled_articles_and_collection_jobs(self):
        scheduled_at = datetime.utcnow() + timedelta(days=1)
        events = build_calendar_events(
            articles=[
                article(),
                article(id="a2", title="待发布文章", status="APPROVED", published_at=None, scheduled_publish_at=scheduled_at),
            ],
            beat_schedule={
                "collect-zhihu-every-2hours": {"task": "app.tasks.collect_zhihu", "schedule": 7200.0},
            },
        )

        event_types = {event["type"] for event in events}
        self.assertIn("published_article", event_types)
        self.assertIn("scheduled_article", event_types)
        self.assertIn("collection_job", event_types)
        self.assertTrue(any(event["title"] == "待发布文章" for event in events))


if __name__ == "__main__":
    unittest.main()
