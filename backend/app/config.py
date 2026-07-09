from pydantic_settings import BaseSettings


from typing import Any


class Settings(BaseSettings):
    # App
    app_name: str = "AIViralContentMatrixSystem"
    debug: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/aiviral"

    # Celery / Redis
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # LLM (DeepSeek)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"

    # Image Generation (Alibaba Cloud Model Studio, OpenAI compatible)
    image_api_key: str = ""   # 同 llm_api_key
    image_base_url: str = "https://llm-aeoei8igg5ogjx2a.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    image_model: str = "qwen-image-2.0-pro"

    # Google Custom Search
    google_api_key: str = ""
    google_cse_id: str = ""

    # Tavily AI Search
    tavily_api_key: str = ""

    # WeChat Official Account
    wechat_app_id: str = ""
    wechat_app_secret: str = ""

    # Collection — 领域分组配置（v2 多领域支持）
    # 每个 key 是领域标识，value 包含 label / rss_feed_urls / search_keywords
    domains: dict[str, dict[str, Any]] = {
        "tech": {
            "label": "科技行业",
            "rss_feed_urls": [
                "https://36kr.com/feed",
                "https://www.huxiu.com/rss/0.xml",
                "https://www.woshipm.com/feed",
            ],
            "folo_keywords": [
                "科技行业", "人工智能", "AI",
            ],
            "search_keywords": [
                "自媒体", "内容创作", "爆款文章", "公众号运营",
                "AI工具", "副业", "流量变现", "个人IP",
            ],
        },
        "life_common_knowledge": {
            "label": "生活常识",
            "rss_feed_urls": [
            ],
            "folo_keywords": [
                "生活常识", "健康科普", "冷知识", "养生误区",
                "健康误区", "锻炼误区", "日常科普",
            ],
            "search_keywords": [
                "生活常识", "健康误区", "冷知识", "养生误区",
                "锻炼误区", "日常习惯", "科普",
            ],
        },
    }
    search_daily_limit: int = 100

    # Publishing

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # 兼容旧属性 — 从 domains 中取默认领域（第一个）
    @property
    def rss_feed_urls(self) -> list[str]:
        first = next(iter(self.domains.values()))
        return first.get("rss_feed_urls", [])

    @property
    def search_keywords(self) -> list[str]:
        first = next(iter(self.domains.values()))
        return first.get("search_keywords", [])


settings = Settings()
