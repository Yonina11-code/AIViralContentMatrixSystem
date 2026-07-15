import unittest

from app.api.articles import _strip_workflow_artifacts_from_body


class ArticleWorkflowArtifactCleanupTests(unittest.TestCase):
    def test_strips_cover_and_illustration_prompt_blocks(self):
        body = """> **[待生成封面图 Prompt]**: hand-drawn watercolor illustration, 16:9 aspect ratio

上周五下班回家，邻居老张正抱着一条厚被子。

> **[待生成插图 1 Prompt]**：soft watercolor shadows, elderly figure, 1:1 aspect ratio

你看，身体比我们诚实多了。
"""

        cleaned = _strip_workflow_artifacts_from_body(body)

        self.assertNotIn("待生成封面图 Prompt", cleaned)
        self.assertNotIn("待生成插图 1 Prompt", cleaned)
        self.assertNotIn("hand-drawn watercolor", cleaned)
        self.assertIn("邻居老张", cleaned)
        self.assertIn("身体比我们诚实", cleaned)

    def test_keeps_regular_blockquotes(self):
        body = """> 提醒：如果已经持续不舒服，建议咨询医生。

正文继续。"""

        cleaned = _strip_workflow_artifacts_from_body(body)

        self.assertIn("提醒：如果已经持续不舒服", cleaned)


if __name__ == "__main__":
    unittest.main()
