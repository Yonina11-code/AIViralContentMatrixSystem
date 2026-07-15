import unittest
from unittest.mock import AsyncMock, patch

from app.agents.writer import WriterAgent


class WriterClaimPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_writer_prompt_includes_claim_plan_and_quote_guidance(self):
        claim_plan = {
            "core_claim": "只能写白粥配咸菜的早餐组合不够均衡",
            "supported_by_source": False,
            "must_not_claim": ["不要写白粥升糖导致血压波动"],
        }

        with patch("app.agents.writer.llm_chat", new=AsyncMock(return_value='{"title":"t","body":"b","summary":"s"}')) as chat:
            await WriterAgent().write(
                topic="白粥早餐",
                angle="早餐场景",
                title_candidates=["白粥早餐要注意"],
                asset_templates="无",
                source_materials="少盐，警惕隐形盐",
                domain="health_regimen",
                claim_plan=claim_plan,
            )

        user_prompt = chat.await_args.args[1]
        self.assertIn("## 事实边界与 claim_plan", user_prompt)
        self.assertIn("只能写白粥配咸菜的早餐组合不够均衡", user_prompt)
        self.assertIn("不要写白粥升糖导致血压波动", user_prompt)
        self.assertIn("尽量不用双引号", user_prompt)


if __name__ == "__main__":
    unittest.main()
