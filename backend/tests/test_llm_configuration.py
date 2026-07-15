import unittest

from fastapi import HTTPException

from app.api.articles import GenerateParams, generate_article
from app.llm import LLMConfigurationError, get_llm_client


class LLMConfigurationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import app.llm as llm_module

        self.llm_module = llm_module
        self.original_client = llm_module._client
        self.original_api_key = llm_module.settings.llm_api_key
        llm_module._client = None
        llm_module.settings.llm_api_key = ""

    def tearDown(self):
        self.llm_module._client = self.original_client
        self.llm_module.settings.llm_api_key = self.original_api_key

    def test_missing_llm_key_raises_configuration_error(self):
        with self.assertRaises(LLMConfigurationError) as ctx:
            get_llm_client()

        self.assertIn("LLM_API_KEY", str(ctx.exception))

    async def test_generate_returns_service_unavailable_when_llm_key_missing(self):
        with self.assertRaises(HTTPException) as ctx:
            await generate_article(GenerateParams(domain="life_common_knowledge"), db=None)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("LLM_API_KEY", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
