"""图片生成器：使用阿里云 Model Studio（OpenAI 兼容格式）生成封面图和内文插图"""

import re
from openai import OpenAI
from app.config import settings
from app.agents.illustration_editor import STYLE_LOCK


def _sanitize_prompt(prompt: str) -> str:
    """清理 prompt 中的特殊字符"""
    return re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]', '', prompt).strip()


def _make_client() -> OpenAI:
    return OpenAI(
        api_key=settings.image_api_key or settings.llm_api_key,
        base_url=settings.image_base_url,
    )


class ImageGenerator:
    """基于阿里云 Model Studio 的免费图生图"""

    def generate_cover(self, title: str, summary: str | None = None) -> str | None:
        """生成封面图（16:9），返回图片 URL，失败返回 None"""
        style = (
            f"{STYLE_LOCK}, consistent character proportions, soft pastel palette, "
            "pencil sketch outline under watercolor washes, 16:9 aspect ratio"
        )
        subject = f"{title}" + (f", {summary}" if summary else "")
        prompt = f"{style}, {subject}"

        try:
            resp = _make_client().images.generate(
                model=settings.image_model,
                prompt=_sanitize_prompt(prompt),
                size="1344x768",
                n=1,
            )
            return resp.data[0].url if resp.data else None
        except Exception as e:
            print(f"[ImageGenerator] 封面图生成失败: {e}")
            return None

    def generate_illustration(
        self,
        section_title: str,
        body_excerpt: str,
        aspect_ratio: str = "1:1",
    ) -> str | None:
        """生成内文插图，返回图片 URL，失败返回 None"""
        style = (
            f"{STYLE_LOCK}, consistent character proportions, soft pastel palette, "
            "pencil sketch outline under watercolor washes"
        )
        context = body_excerpt[:200] if body_excerpt else section_title
        prompt = f"{style}, {section_title}: {context}"
        size = "1024x1024" if aspect_ratio == "1:1" else "1344x768"

        try:
            resp = _make_client().images.generate(
                model=settings.image_model,
                prompt=_sanitize_prompt(prompt),
                size=size,
                n=1,
            )
            return resp.data[0].url if resp.data else None
        except Exception as e:
            print(f"[ImageGenerator] 内文插图生成失败: {e}")
            return None


image_generator = ImageGenerator()
