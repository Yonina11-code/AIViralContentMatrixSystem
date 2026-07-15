import unittest
from datetime import datetime
from types import SimpleNamespace

from app.content_intelligence import (
    build_material_insights,
    build_topic_cards,
    content_similarity,
    score_material,
)


def item(**kwargs):
    defaults = {
        "id": "1",
        "title": "糖尿病饮食误区科普",
        "summary": "医生科普控糖饮食，提醒不要相信偏方。",
        "body": "医生建议关注主食、蔬菜、蛋白质和运动，不要相信祖传偏方。",
        "source": "zhihu",
        "source_name": "知乎",
        "author": "医生",
        "tags": ["zhihu", "type:Answer", "authority:2"],
        "published_at": datetime(2026, 7, 1),
        "collected_at": datetime(2026, 7, 2),
        "read_count": 0,
        "like_count": 394,
        "comment_count": 76,
        "favorite_count": 0,
        "url": "https://www.zhihu.com/question/1/answer/2",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class ContentIntelligenceTests(unittest.TestCase):
    def test_score_material_rewards_credible_engaged_recent_content(self):
        result = score_material(item())

        self.assertGreaterEqual(result["score"], 75)
        self.assertIn("platform_signal", result["reasons"])
        self.assertIn("engagement_signal", result["reasons"])
        self.assertIn("recent", result["reasons"])
        self.assertIn("健康科普", result["topics"])

    def test_score_material_penalizes_hard_pseudoscience(self):
        result = score_material(item(
            title="祖传秘方根治糖尿病",
            summary="三天见效，包治百病。",
            body="祖传秘方可以根治糖尿病，三天见效，包治疑难杂症。",
            source_name="偏方大全",
            like_count=0,
            comment_count=0,
            published_at=datetime(2018, 1, 1),
        ))

        self.assertLess(result["score"], 55)
        self.assertIn("hard_risk_terms", result["reasons"])
        self.assertIn("偏方", result["risks"])

    def test_content_similarity_detects_near_duplicate_titles_and_body(self):
        a = item(title="糖尿病饮食误区：这些控糖习惯别再信", body="控糖饮食 主食 蔬菜 蛋白质 运动 医生 科普")
        b = item(title="糖尿病饮食误区 这些控糖习惯不要信", body="控糖饮食 主食 蔬菜 蛋白质 运动 医生 科普")

        self.assertGreaterEqual(content_similarity(a, b), 0.72)

    def test_build_material_insights_marks_duplicates(self):
        items = [
            item(id="a", title="糖尿病饮食误区：这些控糖习惯别再信", body="控糖饮食 主食 蔬菜 蛋白质 运动 医生 科普"),
            item(id="b", title="糖尿病饮食误区 这些控糖习惯不要信", body="控糖饮食 主食 蔬菜 蛋白质 运动 医生 科普"),
            item(id="c", title="AI 工具怎么选", body="自媒体 AI 工具 标题 配图 复盘"),
        ]

        insights = build_material_insights(items)

        duplicate = next(x for x in insights if x["id"] == "b")
        self.assertTrue(duplicate["duplicate_group"])
        self.assertEqual(duplicate["duplicate_of"], "a")

    def test_build_topic_cards_groups_sources_and_suggests_outline(self):
        cards = build_topic_cards([
            item(id="a", source="zhihu", title="糖尿病饮食误区：这些控糖习惯别再信"),
            item(id="b", source="wechat", title="控糖饮食科普指南", tags=["wechat", "quality:92"]),
        ], limit=3)

        self.assertGreaterEqual(len(cards), 1)
        first = cards[0]
        self.assertIn("topic", first)
        self.assertIn("suggested_angle", first)
        self.assertGreaterEqual(first["material_count"], 1)
        self.assertTrue(first["outline"])


if __name__ == "__main__":
    unittest.main()
