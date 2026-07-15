import unittest

from app.agents.publisher import PublisherAgent


class PublisherStyleTests(unittest.TestCase):
    def test_removes_decorative_quotes_but_keeps_dialogue(self):
        publisher = PublisherAgent()

        text = publisher._reduce_stylistic_quotes(
            "这不是“清淡”，而是早餐组合问题。她说：“最近血压不太稳。”"
        )

        self.assertIn("这不是清淡", text)
        self.assertIn("她说：“最近血压不太稳。”", text)

    def test_removes_common_concept_quotes_in_generated_health_articles(self):
        publisher = PublisherAgent()

        text = publisher._reduce_stylistic_quotes(
            "不要只看“减盐”字样，控的是“总钠量”，不是“少放盐”。调味品里的“隐形盐”也要留意。“钠超标”不是靠“高钾食物”对冲。"
        )

        self.assertEqual(
            text,
            "不要只看减盐字样，控的是总钠量，不是少放盐。调味品里的隐形盐也要留意。钠超标不是靠高钾食物对冲。",
        )


if __name__ == "__main__":
    unittest.main()
