import unittest

from app.api.articles import (
    _apply_source_boundary_fallback,
    _find_unsupported_core_claims,
    _find_unsupported_precise_claims,
    _find_unsupported_relative_claims,
    _review_and_repair_written,
)


class FakeReviewer:
    def __init__(self):
        self.check_calls = 0

    async def check(self, title, body, summary):
        self.check_calls += 1
        if self.check_calls == 1:
            return {
                "passed": False,
                "issues": [{"severity": "blocker", "detail": "初审失败"}],
                "overall_comment": "需修改",
                "keyword_hits": 0,
            }
        return {
            "passed": False,
            "issues": [{"severity": "blocker", "detail": "复审仍失败"}],
            "overall_comment": "仍需修改",
            "keyword_hits": 0,
        }

    async def fix(self, title, body, summary, issues):
        return {
            "title": title.replace("立刻多装一倍", "更好装"),
            "body": body.replace("【封面图建议：不要出现在正文】", ""),
            "summary": summary,
            "changes": "删除工作流提示，弱化承诺",
        }


class WarningRepairReviewer:
    def __init__(self):
        self.check_calls = 0
        self.fixed_issues = None

    async def check(self, title, body, summary):
        self.check_calls += 1
        if self.check_calls == 1:
            return {
                "passed": True,
                "issues": [{
                    "type": "factual_error",
                    "severity": "warning",
                    "detail": "健康数据缺少来源",
                }],
                "overall_comment": "建议修稿",
                "keyword_hits": 0,
            }
        return {
            "passed": True,
            "issues": [],
            "overall_comment": "已更稳妥",
            "keyword_hits": 0,
        }

    async def fix(self, title, body, summary, issues):
        self.fixed_issues = issues
        return {
            "title": title.replace("才能稳得住", "需要注意"),
            "body": body.replace("780毫克", "钠含量可能较高"),
            "summary": summary,
            "changes": "弱化缺少来源的健康数据表述",
        }


class SourceBoundaryReviewer:
    def __init__(self):
        self.check_calls = 0
        self.fixed_issues = []

    async def check(self, title, body, summary):
        self.check_calls += 1
        return {
            "passed": True,
            "issues": [],
            "overall_comment": "本地来源边界校验负责拦截",
            "keyword_hits": 0,
        }

    async def fix(self, title, body, summary, issues):
        self.fixed_issues.append(issues)
        return {
            "title": title,
            "body": (
                body
                .replace("钠含量每15毫升是 680 毫克。", "钠含量并不一定低。")
                .replace("同样 15 毫升，钠含量 700 毫克。", "同样规格下，不同品牌差异不小。")
            ),
            "summary": summary,
            "changes": "删除素材未支撑的酱油包装实测数字",
        }


class GenerationReviewGateTests(unittest.IsolatedAsyncioTestCase):
    def test_finds_precise_health_numbers_not_present_in_source_materials(self):
        claims = _find_unsupported_precise_claims(
            "减盐酱油钠含量每15毫升是 680 毫克，但每日盐摄入控制在5克以内。",
            "正确做法：每天盐的摄入量控制在5克以内，少放酱油、味精和豆瓣酱。",
        )

        self.assertIn("680 毫克", claims)
        self.assertNotIn("5克", claims)

    def test_source_boundary_ignores_nutrition_label_basis_units(self):
        claims = _find_unsupported_precise_claims(
            "看营养成分表时，常见单位是每100克或每100毫升。",
            "正确做法：少放酱油、味精和豆瓣酱。",
        )

        self.assertEqual(claims, [])

    def test_source_boundary_fallback_softens_unsupported_thresholds(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "超市货架上的健康陷阱：这些食品的盐比薯片还多",
                "body": "如果每100克钠含量超过400毫克，建议放回去。这个数值通常意味着钠含量较高。",
                "summary": "钠含量超过400mg/100g就放回去。",
            },
            ["400毫克", "400mg"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("400毫克", combined)
        self.assertNotIn("400mg", combined)
        self.assertNotIn("比薯片还多", combined)
        self.assertIn("钠含量明显偏高", fixed["body"])

    def test_source_boundary_fallback_softens_unsupported_low_sodium_thresholds_naturally(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "早餐面包要看钠",
                "body": "提醒：判断一款面包是否高钠，最直接的办法是看营养成分表。每100克含钠低于300毫克，可以算作相对低钠的选择。尽量选每100克钠含量在300毫克以下的。",
                "summary": "选择每100克钠含量低于300毫克的面包。",
            },
            ["300毫克"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("300毫克", combined)
        self.assertNotIn("明显偏高", combined)
        self.assertIn("对比不同产品", fixed["body"])

    def test_source_boundary_fallback_cleans_serving_size_fragments(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "调味料里的隐形盐",
                "body": "许多蚝油产品每15克里的钠含量，轻轻松松就超过了半克。而刚才那勺蚝油，我大概用了快20克。",
                "summary": "每15克蚝油要留意。",
            },
            ["15克", "20克"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("15克", combined)
        self.assertNotIn("20克", combined)
        self.assertNotIn("每明显偏高", combined)
        self.assertIn("许多蚝油产品的钠含量并不低", fixed["body"])

    def test_source_boundary_fallback_cleans_label_basis_parentheticals(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "减盐酱油没那么简单",
                "body": "真正该看的是背面的营养成分表里，每份（通常是15毫升或10毫升）的钠含量是多少毫克。找到钠这一行，看每份（通常是15毫升）的含量。",
                "summary": "看每15毫升钠含量。",
            },
            ["15毫升", "10毫升"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("15毫升", combined)
        self.assertNotIn("10毫升", combined)
        self.assertNotIn("明显偏高或明显偏高", combined)
        self.assertNotIn("每份（通常是明显偏高", combined)
        self.assertIn("看每份钠含量", fixed["body"])

    def test_finds_oil_sodium_claim_when_source_only_supports_controlling_oil(self):
        claims = _find_unsupported_core_claims(
            "有些油本身就可能含钠。调味油、复合油可能是厨房里的隐形钠。",
            "植物油、坚果和油炸豆制品等高油素食，同样会损伤血管。素食人群同样要控油。",
        )

        self.assertTrue(any("油" in claim and "钠" in claim for claim in claims))

    def test_finds_unsupported_relative_salt_comparisons(self):
        claims = _find_unsupported_relative_claims(
            "那碟凉拌菜里的盐，比你想象的多一倍。钠摄入可能比炒一盘回锅肉还高，甚至超过一天推荐摄入量一半。",
            "正确做法：少放酱油、味精和豆瓣酱，警惕方便面、薯片等隐形盐。",
        )

        self.assertTrue(any("多一倍" in claim for claim in claims))
        self.assertTrue(any("回锅肉" in claim for claim in claims))
        self.assertTrue(any("一半" in claim for claim in claims))

    def test_finds_unsupported_takeaway_half_day_and_tenfold_claims(self):
        claims = _find_unsupported_relative_claims(
            "那碗酸菜鱼里的汤，可能比鸡汤咸十倍。外卖小哥递过来的不只是饭，还有半天的盐。里面的盐可能已经接近一天推荐量的一半。",
            "正确做法：少放酱油、味精和豆瓣酱，警惕方便面、薯片等隐形盐。",
        )

        self.assertTrue(any("十倍" in claim for claim in claims))
        self.assertTrue(any("半天的盐" in claim for claim in claims))
        self.assertTrue(any("接近一天推荐量的一半" in claim for claim in claims))

    def test_relative_claim_detector_does_not_flag_generic_hypertension_context(self):
        claims = _find_unsupported_relative_claims(
            "很多人觉得高血压离自己很远，或者认为只要少吃咸菜、少放酱油就够了。根据指南建议，每人每天食盐摄入量不超过5克。",
            "正确做法：每天盐的摄入量控制在5克以内，少放酱油、味精和豆瓣酱。",
        )

        self.assertEqual(claims, [])

    def test_source_boundary_fallback_softens_unsupported_relative_comparisons(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "那碟凉拌菜里的盐，比你想象的多一倍",
                "body": "那一口下去，钠摄入量可能比炒一盘回锅肉还高。一盘凉拌菜可能超过一天推荐摄入量一半的钠。",
                "summary": "凉拌菜里的盐可能比热汤面还高。",
            },
            ["那碟凉拌菜里的盐，比你想象的多一倍", "钠摄入量可能比炒一盘回锅肉还高", "超过一天推荐摄入量一半"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("多一倍", combined)
        self.assertNotIn("回锅肉还高", combined)
        self.assertNotIn("超过一天推荐摄入量一半", combined)
        self.assertIn("可能没有你想的那么清淡", fixed["title"])

    def test_source_boundary_fallback_softens_generic_processed_food_comparisons(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "一片吐司下肚，你吃进去的钠可能比半碗挂面还多",
                "body": "你觉得自己吃得挺清淡，实际上钠摄入总量可能比一个正常吃咸菜的人还高。那两片吐司里的钠，可能比你中午炒菜放的盐还多。",
                "summary": "白吐司、挂面、饼干等不咸食物可能钠含量惊人。",
            },
            ["一片吐司下肚，你吃进去的钠可能比半碗挂面还多", "比一个正常吃咸菜的人还高", "比你中午炒菜放的盐还多"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("比半碗挂面还多", combined)
        self.assertNotIn("咸菜的人还高", combined)
        self.assertNotIn("炒菜放的盐还多", combined)
        self.assertIn("加工主食里的钠，可能比你想象中多", fixed["title"])

    def test_source_boundary_fallback_cleans_generic_obvious_high_fragments(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "隐形盐提醒",
                "body": "部分市售白吐司每100克的钠含量可达明显偏高。部分品牌的挂面钠含量甚至达到每100克明显偏高以上。有研究认为，每日减少明显偏高盐的摄入，血压可能下降明显偏高。一汤匙酱油大约含明显偏高盐。",
                "summary": "钠含量明显偏高的加工食品要留意。",
            },
            ["300毫克", "1.2毫米汞柱"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("可达明显偏高", combined)
        self.assertNotIn("明显偏高以上", combined)
        self.assertNotIn("下降明显偏高", combined)
        self.assertNotIn("含明显偏高盐", combined)
        self.assertIn("减少盐摄入有助于血压管理", fixed["body"])

    def test_source_boundary_fallback_softens_takeaway_half_day_and_potassium_rescue(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "外卖小哥递过来的不只是饭，还有半天的盐",
                "body": "里面的盐可能已经接近一天推荐量的一半。还有一个补救办法：额外加一份蔬菜。蔬菜里含有钾，钾能帮助身体代谢多余的钠。",
                "summary": "用额外蔬菜帮助代谢钠摄入。",
            },
            ["半天的盐", "接近一天推荐量的一半", "蔬菜里含有钾，钾能帮助身体代谢多余的钠"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("半天的盐", combined)
        self.assertNotIn("接近一天推荐量的一半", combined)
        self.assertNotIn("补救办法", combined)
        self.assertNotIn("帮助身体代谢多余的钠", combined)
        self.assertIn("搭配一份蔬菜", fixed["body"])

    def test_source_boundary_fallback_softens_high_potassium_sodium_claims(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "蒸菜调味要留意",
                "body": "另外，搭配一些高钾食物，比如菠菜、土豆、香蕉，可以帮助身体排出多余的钠。但这只是辅助手段，不能代替少放调料。",
                "summary": "搭配高钾食物帮助身体排出多余的钠。",
            },
            ["高钾食物可以帮助身体排出多余的钠"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("帮助身体排出多余的钠", combined)
        self.assertIn("搭配蔬菜", fixed["body"])
        self.assertIn("不能抵消", fixed["body"])

    def test_finds_unsupported_instant_noodle_sauce_comparisons(self):
        claims = _find_unsupported_relative_claims(
            "酱料包里的钠含量，可能比面饼本身还高出一大截。酱料包和粉包加起来的钠含量，可能占到整包泡面的六成甚至更多。",
            "正确做法：少放酱油、味精和豆瓣酱，警惕方便面、薯片、挂面、饼干和腌制肉制品等隐形盐。",
        )

        self.assertTrue(any("比面饼" in claim for claim in claims))
        self.assertTrue(any("六成" in claim for claim in claims))

    def test_source_boundary_fallback_softens_instant_noodle_sauce_claims(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "那包酱料里，到底装了什么",
                "body": "酱料包里的钠含量，可能比面饼本身还高出一大截。一些产品里，酱料包和粉包加起来的钠含量，可能占到整包泡面的六成甚至更多。常见泡面每百克钠含量通常在数百到上千毫克不等。下次泡面时，只放一半或者三分之一。用开水涮一下酱料包再挤，这样能冲掉一部分盐分。",
                "summary": "通过少放酱料，可以轻松减少钠摄入。",
            },
            ["酱料包里的钠含量，可能比面饼本身还高出一大截", "六成甚至更多", "数百到上千毫克", "只放一半或者三分之一"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("比面饼本身还高", combined)
        self.assertNotIn("六成", combined)
        self.assertNotIn("数百到上千毫克", combined)
        self.assertNotIn("三分之一", combined)
        self.assertNotIn("轻松减少", combined)
        self.assertIn("不同产品差异很大", fixed["body"])

    def test_source_boundary_fallback_reframes_oil_sodium_claims(self):
        fixed = _apply_source_boundary_fallback(
            {
                "title": "厨房里的那瓶油，可能比酱油更影响你的血压",
                "body": "## 你以为在吃油，其实可能在吃“隐形钠”\n有些油本身就可能含钠。市面上很多调味油、复合油会加入盐或其他含钠添加剂。",
                "summary": "本文揭示油的“隐形钠”和高温烹饪隐患。",
            },
            ["有些油本身就可能含钠。", "调味油、复合油会加入盐或其他含钠添加剂。"],
        )

        combined = fixed["title"] + fixed["body"] + fixed["summary"]
        self.assertNotIn("隐形钠", combined)
        self.assertNotIn("有些油本身就可能含钠", combined)
        self.assertIn("高油饮食", fixed["body"])
        self.assertIn("用油习惯", fixed["summary"])

    async def test_review_gate_rechecks_after_fix_and_blocks_failed_draft(self):
        written = {
            "title": "出门前换一种打包逻辑，箱子立刻多装一倍",
            "body": "【封面图建议：不要出现在正文】正文",
            "summary": "打包方式",
        }

        repaired, review_trace, passed = await _review_and_repair_written(written, FakeReviewer())

        self.assertFalse(passed)
        self.assertEqual(repaired["title"], "出门前换一种打包逻辑，箱子更好装")
        self.assertIn("fixed", review_trace)
        self.assertIn("second_review", review_trace)
        self.assertEqual(review_trace["second_review"]["issues"][0]["detail"], "复审仍失败")

    async def test_review_gate_repairs_health_factual_warnings_before_passing(self):
        reviewer = WarningRepairReviewer()
        written = {
            "title": "早餐吃对，血压才能稳得住",
            "body": "某网红麦片每100克钠含量780毫克。",
            "summary": "早餐控钠提醒",
        }

        repaired, review_trace, passed = await _review_and_repair_written(written, reviewer)

        self.assertTrue(passed)
        self.assertEqual(repaired["title"], "早餐吃对，血压需要注意")
        self.assertIn("钠含量可能较高", repaired["body"])
        self.assertIn("fixed", review_trace)
        self.assertIn("second_review", review_trace)
        self.assertEqual(reviewer.check_calls, 2)
        self.assertEqual(reviewer.fixed_issues[0]["type"], "factual_error")

    async def test_review_gate_repairs_source_unsupported_precise_numbers(self):
        reviewer = SourceBoundaryReviewer()
        written = {
            "title": "买酱油要看背面这个数字",
            "body": "减盐酱油钠含量每15毫升是 680 毫克。同样 15 毫升，钠含量 700 毫克。",
            "summary": "酱油控钠提醒",
        }
        source_materials = "正确做法：每天盐的摄入量控制在5克以内，少放酱油、味精和豆瓣酱。"

        repaired, review_trace, passed = await _review_and_repair_written(
            written,
            reviewer,
            source_materials=source_materials,
        )

        self.assertTrue(passed)
        self.assertNotIn("680 毫克", repaired["body"])
        self.assertNotIn("700 毫克", repaired["body"])
        self.assertIn("fixed", review_trace)
        self.assertEqual(reviewer.check_calls, 2)
        self.assertIn("素材未提供", reviewer.fixed_issues[0][0]["detail"])


if __name__ == "__main__":
    unittest.main()
