import unittest

from app.agents.reviewer import ReviewerAgent


class ReviewerSafetyTests(unittest.TestCase):
    def test_local_precheck_blocks_health_overpromise_numbers_and_unsafe_tips(self):
        reviewer = ReviewerAgent()

        issues = reviewer._local_editorial_precheck(
            title="睡前涂完米诺地尔，多等这一步，发量才能真的长回来",
            body=(
                "有研究提示，一次喷涂只有30%到40%进入毛囊。"
                "如果着急睡觉，可以用保鲜膜或浴帽罩住头发，也可以用吹风机吹干。"
            ),
            summary="多等一步就能长回来",
        )

        details = "\n".join(issue["detail"] for issue in issues)
        self.assertIn("绝对化疗效承诺", details)
        self.assertIn("未经来源支撑的精确数字", details)
        self.assertIn("不安全或不稳妥的健康建议", details)
        self.assertTrue(all(issue["severity"] == "blocker" for issue in issues))

    def test_local_precheck_blocks_workflow_artifacts_and_lifestyle_overpromises(self):
        reviewer = ReviewerAgent()

        issues = reviewer._local_editorial_precheck(
            title="出门前还在把T恤叠成方块？换一种打包逻辑，箱子立刻多装一倍",
            body=(
                "【封面图建议：行李箱打开，衣服整齐排布】\n"
                "这个方法能让箱子立刻多装一倍，减少80%浪费。\n"
                "【内文插图1建议：展示卷衣服的步骤】"
            ),
            summary="换一种打包方式，箱子空间翻倍。",
        )

        details = "\n".join(issue["detail"] for issue in issues)
        self.assertIn("正文泄漏了图片或工作流提示", details)
        self.assertIn("存在未经来源支撑的生活类夸张承诺", details)
        self.assertTrue(any(issue["severity"] == "blocker" for issue in issues))

    def test_local_precheck_warns_when_plain_bullet_list_is_too_long(self):
        reviewer = ReviewerAgent()

        issues = reviewer._local_editorial_precheck(
            title="出门打包前，先换一种分类方式",
            body="\n".join([
                "- 先把衣服按场景分组",
                "- 再处理容易皱的衣服",
                "- 小件放进空隙",
                "- 洗漱包单独封好",
                "- 到酒店先挂起来",
            ]),
            summary="打包建议",
        )

        self.assertIn("普通列表超过 4 条", "\n".join(issue["detail"] for issue in issues))
        self.assertFalse(any(issue["severity"] == "blocker" for issue in issues))

    def test_local_precheck_allows_practical_lifestyle_numbers_without_source(self):
        reviewer = ReviewerAgent()

        issues = reviewer._local_editorial_precheck(
            title="出门打包前，先把衣服按场景分组",
            body="如果只出门3天，可以先拿出5件上衣，再花5分钟做一次取舍。",
            summary="打包前先分类。",
        )

        self.assertNotIn("存在未经来源支撑的精确数字", "\n".join(issue["detail"] for issue in issues))


if __name__ == "__main__":
    unittest.main()
