import unittest

from app.api.articles import _review_and_repair_written


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


class GenerationReviewGateTests(unittest.IsolatedAsyncioTestCase):
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


if __name__ == "__main__":
    unittest.main()
