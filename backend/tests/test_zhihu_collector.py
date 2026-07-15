import unittest
from datetime import datetime

import httpx

from app.collectors.zhihu_collector import ZhihuCollector


class ZhihuCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_search_maps_zhihu_items_to_content_items(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "Bearer test-secret")
            self.assertIn("X-Request-Timestamp", request.headers)
            self.assertEqual(request.url.params["Query"], "AI工具")
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Message": "success",
                    "Data": {
                        "Items": [
                            {
                                "Title": "自媒体 AI 工具怎么选 - 知乎",
                                "ContentType": "Answer",
                                "ContentID": "2058576654612558642",
                                "ContentText": "<em>AI工具</em>选择要看完整内容流程。",
                                "Url": "https://www.zhihu.com/question/1/answer/2?utm_medium=openapi_platform",
                                "CommentCount": 3,
                                "VoteUpCount": 12,
                                "AuthorName": "知乎作者",
                                "EditTime": 1783582920,
                                "AuthorityLevel": "2",
                                "RankingScore": 0.91,
                            }
                        ]
                    },
                },
            )

        collector = ZhihuCollector(access_secret="test-secret", transport=httpx.MockTransport(handler))

        items = await collector.collect(keywords=["AI工具"], domain="tech", max_per_keyword=5)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.title, "自媒体 AI 工具怎么选 - 知乎")
        self.assertEqual(item.source, "zhihu")
        self.assertEqual(item.source_name, "知乎")
        self.assertEqual(item.author, "知乎作者")
        self.assertEqual(item.like_count, 12)
        self.assertEqual(item.comment_count, 3)
        self.assertEqual(item.body, "AI工具选择要看完整内容流程。")
        self.assertEqual(item.summary, "AI工具选择要看完整内容流程。")
        self.assertEqual(item.domain, "tech")
        self.assertEqual(item.published_at, datetime.fromtimestamp(1783582920))
        self.assertIn("zhihu", item.tags)
        self.assertIn("type:Answer", item.tags)
        self.assertIn("authority:2", item.tags)
        self.assertIsNotNone(item.fingerprint)

    async def test_collect_hot_list_maps_hot_items(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(str(request.url), "https://developer.zhihu.com/api/v1/content/hot_list?Limit=2")
            return httpx.Response(
                200,
                json={
                    "Code": 0,
                    "Message": "success",
                    "Data": {
                        "Total": 2,
                        "Items": [
                            {
                                "Title": "今天的知乎热榜问题",
                                "Url": "https://www.zhihu.com/question/123",
                                "ThumbnailUrl": "https://pic.zhimg.com/hot.jpg",
                                "Summary": "热榜摘要",
                            }
                        ],
                    },
                },
            )

        collector = ZhihuCollector(access_secret="test-secret", transport=httpx.MockTransport(handler))

        items = await collector.collect(hot_list=True, hot_limit=2, domain="tech")

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.title, "今天的知乎热榜问题")
        self.assertEqual(item.body, "热榜摘要")
        self.assertEqual(item.summary, "热榜摘要")
        self.assertEqual(item.url, "https://www.zhihu.com/question/123")
        self.assertIn("zhihu_hot", item.tags)

    async def test_rate_limit_response_is_nonfatal(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"Code": 30001, "Message": "second limit exceeded", "Data": None})

        collector = ZhihuCollector(access_secret="test-secret", transport=httpx.MockTransport(handler))

        items = await collector.collect(keywords=["控糖"], domain="health_regimen")

        self.assertEqual(items, [])

    async def test_missing_access_secret_skips_collection(self):
        collector = ZhihuCollector(access_secret="")

        items = await collector.collect(keywords=["AI工具"], domain="tech")

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
