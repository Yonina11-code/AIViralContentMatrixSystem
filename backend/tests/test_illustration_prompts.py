import unittest

from app.agents.illustration_editor import IllustrationEditorAgent, STYLE_LOCK


class IllustrationPromptTests(unittest.TestCase):
    def test_parse_result_normalizes_copy_ready_prompts(self):
        raw = """
        {
          "visual_style": "consistent watercolor storybook style",
          "cover": {
            "prompt": "hand-drawn watercolor illustration, a girl holding a cup",
            "aspect_ratio": "16:9",
            "style": "watercolor"
          },
          "illustrations": [
            {
              "section_title": "Scene one",
              "prompt": "hand-drawn watercolor illustration, the same girl reading a label",
              "aspect_ratio": "1:1"
            }
          ]
        }
        """

        data = IllustrationEditorAgent()._parse_result(raw)

        self.assertIn(STYLE_LOCK, data["visual_style"])
        self.assertIn("consistent watercolor storybook style", data["visual_style"])
        self.assertIn(STYLE_LOCK, data["cover"]["copy_prompt"])
        self.assertNotIn("white space left for title text overlay", data["cover"]["copy_prompt"].lower())
        self.assertIn(STYLE_LOCK, data["illustrations"][0]["copy_prompt"])

    def test_parse_result_deduplicates_repeated_style_prefixes(self):
        repeated = f"{STYLE_LOCK}, {STYLE_LOCK}, steamed fish on a table"
        raw = f"""
        {{
          "visual_style": "{STYLE_LOCK}, {STYLE_LOCK}, warm oat palette",
          "cover": {{
            "copy_prompt": "{repeated}",
            "aspect_ratio": "16:9"
          }},
          "illustrations": []
        }}
        """

        data = IllustrationEditorAgent()._parse_result(raw)

        self.assertEqual(data["visual_style"].count(STYLE_LOCK), 1)
        self.assertEqual(data["cover"]["copy_prompt"].count(STYLE_LOCK), 1)

    def test_system_prompt_requires_consistent_copy_ready_output(self):
        from app.agents import illustration_editor

        prompt = illustration_editor.SYSTEM_PROMPT

        self.assertIn("visual_style", prompt)
        self.assertIn("copy_prompt", prompt)
        self.assertIn("封面图不要要求留白", prompt)
        self.assertIn("封面图和所有内文插图必须共享同一套 visual_style", prompt)


if __name__ == "__main__":
    unittest.main()
