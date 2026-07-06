import unittest

from app.agents import editor_in_chief, writer
from app.agents.publisher import PublisherAgent


class EditorialStyleTests(unittest.TestCase):
    def test_editor_prompt_discourages_formulaic_fear_titles(self):
        prompt = editor_in_chief.SYSTEM_PROMPT

        self.assertIn("不要使用恐吓式标题", prompt)
        self.assertIn("真人编辑", prompt)
        self.assertNotIn("有爆款潜质", prompt)
        self.assertNotIn("情绪张力", prompt)

    def test_writer_prompt_removes_forced_engagement_and_golden_quotes(self):
        prompt = writer.SYSTEM_PROMPT

        self.assertIn("像有经验的人类编辑", prompt)
        self.assertIn("禁止套用", prompt)
        self.assertNotIn("全文提炼 **3-5 个金句**", prompt)
        self.assertNotIn("互动引导模板", prompt)
        self.assertNotIn("SEO 关键词要求", prompt)

    def test_writer_prompt_requires_medical_boundaries_and_structured_markdown(self):
        prompt = writer.SYSTEM_PROMPT

        self.assertIn("1500-2200 字", prompt)
        self.assertIn("不得编造精确数字", prompt)
        self.assertIn("不要建议保鲜膜、浴帽、吹风机", prompt)
        self.assertIn("提醒：", prompt)
        self.assertIn("步骤：", prompt)
        self.assertIn("插图 prompt 由另一个 Agent 生成", prompt)
        self.assertIn("不得在正文中写入封面图建议", prompt)

    def test_publisher_does_not_add_decorative_symbol_to_quote(self):
        html = PublisherAgent()._markdown_to_wechat_html("> **提醒**：这只是一个判断线索。")

        self.assertIn("提醒", html)
        self.assertNotIn("✨", html)

    def test_publisher_renders_notice_and_steps_with_distinct_layout(self):
        html = PublisherAgent()._markdown_to_wechat_html(
            "## 真正要记住的不是按摩\n\n"
            "> 提醒：涂完后先让头皮自然干透。\n\n"
            "- 步骤：涂在干燥头皮上\n"
            "- 步骤：四小时内别洗头\n"
        )

        self.assertIn("border-left:4px solid #2563eb", html)
        self.assertIn("background:#eff6ff", html)
        self.assertIn("border:1px solid #e4e4e7", html)
        self.assertIn("真正要记住的不是按摩", html)
        self.assertNotIn("<p style=\"margin:14px 0 8px;line-height:1.75;font-size:15px;color:#222;font-weight:500;\"><p", html)


if __name__ == "__main__":
    unittest.main()
