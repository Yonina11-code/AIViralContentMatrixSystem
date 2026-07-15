"""插图编辑 Agent：为文章生成封面和内文插图的 AI 绘图 prompt

输出统一的「手绘水彩插画」风格 prompt，供用户复制到 Midjourney /
DALL·E / Stable Diffusion 等模型中使用。
"""

import json

from app.llm import llm_chat

STYLE_LOCK = "hand-drawn watercolor illustration, soft wet-on-wet technique, visible brushstrokes, paper texture visible, watercolor bleeds, no digital hard edges, zen aesthetic, serene and calming atmosphere"

SYSTEM_PROMPT = """你是一个专业的绘本插画师。你只为文章生成**纯手绘水彩风格**的插图 prompt，这些 prompt 将用于 AI 图像生成器。

## 风格锁定（每次生成必须强制使用）

风格词（必须原词嵌入 prompt，不得替换）：
`hand-drawn watercolor illustration, soft wet-on-wet technique, visible brushstrokes, paper texture visible, watercolor bleeds, no digital hard edges, zen aesthetic, serene botanical art, slow life illustration`

禁止出现：photorealistic, photograph, 3d render, CGI, digital art, sharp edges, hyperrealistic

## 一致性规则

- 封面图和所有内文插图必须共享同一套 visual_style，包括画法、人物体态、柔和色彩、材质、线条和宁静的世界观。
- 先定义一个 `visual_style`，再把同一段风格描述完整嵌入每一个 `copy_prompt`。
- 整体风格要符合中老年养生、健康慢生活的调性，强调宁静、松弛、优雅与自然信任感。

## 构图规则

- 人物：采用正常舒缓的人体比例，面部神态安详、松弛，展现健康活力的中老年人或舒缓的自然场景。避免夸张的卡通或儿童化比例。
- 线条：用 **faint pencil outline** 或 **soft charcoal sketch** 淡淡打底，甚至不着痕迹，主要靠水彩的晕染来塑造形体。
- 背景：富有呼吸感的淡雅水彩背景。内文插图可以有自然的留白（soft vignetting / white background wash），封面图则需要画面完整。
- 封面图不要要求留白，不要为了标题文字预留空白区域；封面应该是一张完整可直接使用的水彩画面。
- 色调：采用草本植物色（herbal greens）、松石蓝（soft teal）、暖燕麦色（warm oat）、淡雅琥珀色（soft amber），拒绝高饱和度色及刺眼的亮色。

## 输出格式（JSON）

{
  "visual_style": "整篇文章所有图片共用的一段英文风格描述，包含风格词、角色比例、色彩、材质、线条",
  "cover": {
    "copy_prompt": "可以直接复制粘贴到图像生成器的一整段英文 prompt，包含 visual_style + 封面画面描述 + 16:9 aspect ratio，不拆字段",
    "aspect_ratio": "16:9"
  },
  "illustrations": [
    {
      "section_title": "对应的段落主题",
      "copy_prompt": "可以直接复制粘贴到图像生成器的一整段英文 prompt，包含同一个 visual_style + 插图画面描述 + 1:1 aspect ratio，不拆字段",
      "aspect_ratio": "1:1"
    }
  ]
}

## Prompt 写作规则

1. **全部用英文输出**（AI 图像模型对英文风格词理解更准确）
2. `copy_prompt` 必须是一整段可复制 prompt，不要把尺寸、内容、风格拆成多个说明
3. **风格词必须放在 copy_prompt 最前面**，用逗号分隔
4. 画面描述用简洁的视觉词汇，不描述抽象情绪
5. 封面图不要写 `white space left for title text overlay`，不要要求 title area、blank area、copy space
6. 每张图 copy_prompt 控制在 90-150 词以内
7. **禁止任何摄影相关的词**：photo, realistic, real, camera, lens, shadow（除非是水彩画出来的阴影）"""


class IllustrationEditorAgent:

    async def edit(
        self,
        title: str,
        body: str,
        summary: str | None = None,
    ) -> dict:
        """分析文章标题与正文，生成封面和内文插图 prompt。"""
        # 取正文前 3000 字作为分析素材，避免 token 超限
        body_excerpt = body[:3000]
        if len(body) > 3000:
            body_excerpt += "\n\n（正文较长，以上为前3000字摘要）"

        user_prompt = f"""## 文章标题
{title}

## 文章摘要
{summary or '（无摘要）'}

## 文章正文（开头部分）
{body_excerpt}

请根据以上文章内容，生成封面图和2-4张内文插图的 AI 绘图 prompt。

规则：
- 每张图的 copy_prompt 必须以风格词开头："{STYLE_LOCK}"
- 全部用英文输出
- 封面图比例 16:9，内文插图比例 1:1；比例信息要写进 copy_prompt 末尾，例如 "16:9 aspect ratio"
- 封面图不要说明留白，不要写 title text overlay、copy space、blank area
- 封面图和所有内文插图必须共享同一套 visual_style，并把这套 visual_style 嵌入每个 copy_prompt
- 人物采用正常舒缓的人体比例，面部神态安详、松弛，展现健康活力的中老年人或舒缓的自然场景，避免夸张的卡通或儿童化比例"""
        result = await llm_chat(SYSTEM_PROMPT, user_prompt, temperature=0.7)
        return self._parse_result(result)

    def _parse_result(self, raw: str) -> dict:
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            if "cover" not in data:
                data["cover"] = {"copy_prompt": raw[:500], "aspect_ratio": "16:9"}
            if "illustrations" not in data:
                data["illustrations"] = []
            return self._normalize_result(data)
        except json.JSONDecodeError:
            return self._normalize_result({
                "visual_style": STYLE_LOCK,
                "cover": {
                    "copy_prompt": f"{STYLE_LOCK}, parsing failed, create one cohesive watercolor storybook cover illustration inspired by the article, 16:9 aspect ratio",
                    "aspect_ratio": "16:9",
                },
                "illustrations": [],
            })

    def _normalize_result(self, data: dict) -> dict:
        visual_style = data.get("visual_style") or STYLE_LOCK
        if STYLE_LOCK not in visual_style:
            visual_style = f"{STYLE_LOCK}, {visual_style}"
        visual_style = self._dedupe_style_lock(visual_style)
        data["visual_style"] = visual_style
        data["cover"] = self._normalize_prompt_item(data.get("cover") or {}, visual_style, "16:9", is_cover=True)
        data["illustrations"] = [
            self._normalize_prompt_item(item, visual_style, "1:1", is_cover=False)
            for item in (data.get("illustrations") or [])
        ]
        return data

    def _normalize_prompt_item(self, item: dict, visual_style: str, default_ratio: str, is_cover: bool) -> dict:
        ratio = item.get("aspect_ratio") or default_ratio
        prompt = item.get("copy_prompt") or item.get("prompt") or ""
        prompt = self._strip_cover_whitespace_instruction(prompt) if is_cover else prompt
        if STYLE_LOCK not in prompt:
            prompt = f"{visual_style}, {prompt}".strip(" ,")
        prompt = self._dedupe_style_lock(prompt)
        if ratio not in prompt:
            prompt = f"{prompt}, {ratio} aspect ratio"

        normalized = dict(item)
        normalized["copy_prompt"] = prompt
        normalized["prompt"] = prompt
        normalized["aspect_ratio"] = ratio
        normalized.pop("style", None)
        return normalized

    def _dedupe_style_lock(self, text: str) -> str:
        if not text:
            return text
        first = text.find(STYLE_LOCK)
        if first < 0:
            return text
        before = text[: first + len(STYLE_LOCK)]
        after = text[first + len(STYLE_LOCK):].replace(STYLE_LOCK, "")
        cleaned = f"{before}{after}"
        return " ".join(cleaned.replace(", ,", ",").replace(",,", ",").split()).strip(" ,")

    def _strip_cover_whitespace_instruction(self, prompt: str) -> str:
        banned_phrases = [
            "white space left for title text overlay",
            "white space for title text overlay",
            "title text overlay",
            "copy space",
            "blank area",
            "title area",
        ]
        cleaned = prompt
        for phrase in banned_phrases:
            cleaned = cleaned.replace(phrase, "")
        return " ".join(cleaned.replace(" ,", ",").split())
