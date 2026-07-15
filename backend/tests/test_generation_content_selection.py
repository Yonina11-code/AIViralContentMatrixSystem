import unittest
from datetime import datetime
from types import SimpleNamespace

from app.api.articles import (
    _build_source_materials,
    _normalize_claim_plan,
    _normalize_generated_title,
    _content_quality_score,
    _is_auto_selectable_content,
    _sort_content_for_generation,
)


def item(source, title, tags=None, published_at=None):
    return SimpleNamespace(
        source=source,
        title=title,
        tags=tags or [],
        published_at=published_at,
        collected_at=published_at,
    )


def content_item(title, body=None, summary=None, url=None):
    return SimpleNamespace(
        source="wechat",
        title=title,
        source_name="河北大学附属医院门诊部",
        domain="life_common_knowledge",
        summary=summary,
        body=body,
        url=url,
    )


class GenerationContentSelectionTests(unittest.TestCase):
    def test_quality_score_reads_wechat_quality_tag(self):
        content = item("wechat", "控糖误区", ["wechat", "quality:92"])

        self.assertEqual(_content_quality_score(content), 92)

    def test_auto_selection_filters_low_quality_wechat_only(self):
        low_wechat = item("wechat", "偏方大全", ["wechat", "quality:22"])
        good_wechat = item("wechat", "高血压饮食误区", ["wechat", "quality:96"])
        rss_content = item("rss", "果壳健康科普")

        self.assertFalse(_is_auto_selectable_content(low_wechat))
        self.assertTrue(_is_auto_selectable_content(good_wechat))
        self.assertTrue(_is_auto_selectable_content(rss_content))

    def test_generation_sort_prefers_high_quality_wechat(self):
        low = item("wechat", "旧泛养生", ["wechat", "quality:50"], datetime(2026, 7, 1))
        mid = item("wechat", "控糖误区", ["wechat", "quality:92"], datetime(2025, 1, 1))
        high = item("wechat", "高尿酸指南", ["wechat", "quality:100"], datetime(2024, 1, 1))

        sorted_items = _sort_content_for_generation([low, mid, high])

        self.assertEqual([x.title for x in sorted_items], ["高尿酸指南", "控糖误区", "旧泛养生"])

    def test_source_materials_include_body_excerpt_and_url(self):
        materials = _build_source_materials([
            content_item(
                "纠正饮食误区，守护血压平稳",
                body="早餐里不只咸菜含盐，面包、加工肉和调味麦片也要看营养成分表。",
                summary="高血压人群应关注全天钠摄入。",
                url="https://example.com/article",
            )
        ])

        self.assertIn("纠正饮食误区，守护血压平稳", materials)
        self.assertIn("早餐里不只咸菜含盐", materials)
        self.assertIn("https://example.com/article", materials)

    def test_claim_plan_blocks_unsupported_glucose_mechanism(self):
        decision = {
            "selected_topic": "那碗白粥，可能不清淡",
            "angle": "从白粥升糖快、胰岛素影响血压切入",
            "claim_plan": {
                "core_claim": "白粥升糖快，胰岛素会影响血压",
                "supported_by_source": True,
                "must_not_claim": [],
            },
        }
        source_materials = "素材摘录：少盐不等于不吃盐，警惕隐形盐；高油素食也要控油。"

        plan = _normalize_claim_plan(decision, source_materials)

        self.assertFalse(plan["supported_by_source"])
        self.assertIn("素材未支持血糖或胰岛素机制", plan["core_claim"])
        self.assertTrue(any("胰岛素" in item for item in plan["must_not_claim"]))

    def test_claim_plan_blocks_unsupported_takeaway_salt_comparisons(self):
        decision = {
            "selected_topic": "点外卖时，我多看了一眼调料包",
            "angle": "写外卖调料包、汤底、酱料包可能带来半天的盐",
            "claim_plan": {
                "core_claim": "一份普通外卖的钠含量可能接近或超过全天推荐摄入量的一半",
                "supported_by_source": True,
                "must_not_claim": [],
            },
        }
        source_materials = "素材摘录：少放酱油、味精和豆瓣酱，警惕方便面、薯片、挂面、饼干和腌制肉制品等隐形盐。"

        plan = _normalize_claim_plan(decision, source_materials)

        self.assertFalse(plan["supported_by_source"])
        self.assertIn("素材未支持外卖", plan["core_claim"])
        self.assertTrue(any("半天" in item or "一半" in item for item in plan["must_not_claim"]))

    def test_generated_title_falls_back_when_writer_returns_body_paragraph(self):
        written = {
            "title": "直到我偶然翻到蚝油瓶子上的营养成分表，才发现事情不太对。每15克蚝油里的钠含量，轻轻松松就超过了半克。"
        }
        decision = {
            "selected_topic": "你家的低盐饮食，可能败给了这瓶调味料",
            "suggested_title_candidates": ["晚餐加了蚝油和番茄酱，控盐要多看一眼"],
        }

        self.assertEqual(
            _normalize_generated_title(written, decision),
            "晚餐加了蚝油和番茄酱，控盐要多看一眼",
        )


if __name__ == "__main__":
    unittest.main()
