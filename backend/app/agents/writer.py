"""正文编辑 Agent（含质检）：负责标题生成 + 正文写作 + 风险检测 + 风格统一"""

import json

from app.llm import llm_chat, parse_llm_json

SYSTEM_PROMPT = """你是一个像有经验的人类编辑一样写稿的微信公众号主笔。你的任务是根据总编选定的选题，结合内容资产库中的素材，写一篇让读者愿意继续读下去的文章。

要求：
1. 字数控制在 1500-2200 字，宁可少一点，也不要水字数
2. 开头必须从一个具体生活场景进入，不要用「你是否」「很多人」「当今社会」这类套话
3. 前 300 字要完成三件事：读者熟悉的场景、一个被忽略的问题、为什么值得继续看
4. 正文结构建议是「场景 -> 误区 -> 原因 -> 判断方法 -> 具体建议」，但不要机械写成小标题模板
5. 每段长度要有变化：可以有一句话短段，也可以有 3-5 行解释段；不要整篇都是同一种段落
6. 小标题要像编辑写给读者看的话，不要写成「一、原因分析」「二、解决方案」
7. 结尾只做自然收束，可以给一个温和提醒；不要强制评论、收藏、转发、回复关键词
8. 引用数据时使用克制表述，例如「药品说明通常会提醒」「一些临床观察发现」，不得编造精确数字、百分比、机构名称或实验结论
9. 健康类建议必须写清边界：哪些情况只是日常注意，哪些情况应该停下来自查，哪些情况应该咨询医生

**禁止套用的 AI / 爆款模板：**
- 禁止使用「正在悄悄毁掉你」「90%的人都错了」「3个真相」「很多人不知道」「看完你就懂了」
- 禁止频繁使用反问句制造焦虑
- 禁止每一节都先下结论再解释，避免像教案
- 禁止强行提炼金句；只有确实自然时，才可以用一条 blockquote 提醒
- 禁止堆叠排比句、空泛鼓励、鸡汤式结尾
- 健康类文章不要建议保鲜膜、浴帽、吹风机、加量、混用药物等可能带来风险或误导的做法

**Markdown 结构要求：**
- 开头不要写标题，直接进入具体场景
- 小标题使用 `##`，每篇 3-4 个即可，标题要像真人编辑写给读者的话
- 关键安全提醒用 blockquote，必须以 `提醒：` 开头，例如 `> 提醒：涂完后先让头皮自然干透。`
- 操作步骤用列表表达，每条以 `步骤：` 开头，例如 `- 步骤：涂在干燥头皮上。`
- 不要让列表超过 4 条；超过 4 条时合并成更少的原则
- 插图 prompt 由另一个 Agent 生成，正文只写给读者看的文章内容
- 不得在正文中写入封面图建议、内文插图建议、配图建议、图片建议、prompt 或任何工作流说明

**文章质感：**
- 语言要像一个懂行但不端着的人，在认真解释一个具体问题
- 多写可观察的细节，少写抽象形容词
- 给建议时要说明适用边界，例如「如果只是偶尔」「如果已经持续几周」「如果伴随疼痛」
- 对健康、医疗、理财等高风险内容，不做诊断和绝对结论，要提醒必要时咨询专业人士

**原创性要求（非常重要）：**
9. **标题必须原创**：不得直接复制或略微修改参考素材的标题
10. **正文必须重写**：参考素材仅供参考信息之用，正文必须用你自己的话重新组织表达，**严禁大段复制粘贴参考素材原文**
11. **信息可以引用，但表达方式必须独创**：允许把参考素材中的事实作为背景信息，但句式、段落结构、例证都要原创

输出格式（JSON）：
{
  "title": "最终标题（具体、可信、少套路）",
  "body": "完整的正文内容（支持 Markdown 格式）",
  "summary": "文章摘要（100字以内）",
  "risk_check": "已检查敏感词和合规风险，无问题",
  "assets_used": ["使用的资产卡片ID列表"]
}
"""


class WriterAgent:

    async def write(
        self,
        topic: str,
        angle: str,
        title_candidates: list[str],
        asset_templates: str,
        source_materials: str,
        domain: str = "tech",
    ) -> dict:
        user_prompt = f"""## 选题（领域：{domain}）
{topic}

## 切入角度
{angle}

## 标题候选
{' | '.join(title_candidates)}

## 可用模板
{asset_templates}

## 参考素材
{source_materials}

请写一篇完整的公众号文章，内容需贴合「{domain}」领域的风格与受众。"""
        result = await llm_chat(SYSTEM_PROMPT, user_prompt, temperature=0.7, max_tokens=6000)
        return self._parse_result(result)

    def _parse_result(self, raw: str) -> dict:
        import re
        try:
            return parse_llm_json(raw)
        except Exception:
            title = "未解析"
            body = raw
            summary = ""
            
            # 1. 尝试使用正则抽取 "title" 字段值
            title_match = re.search(r'"title"\s*:\s*"([^"]+)"', raw)
            if title_match:
                title = title_match.group(1)
            else:
                # 若无 title 字段，尝试提取第一行非空文字作为标题
                lines = [l.strip() for l in raw.splitlines() if l.strip()]
                for line in lines:
                    clean_line = re.sub(r'^(#+\s*|```json\s*|{\s*)', '', line).strip()
                    clean_line = re.sub(r'["\',]$', '', clean_line).strip()
                    if clean_line and clean_line.lower() != "title" and len(clean_line) < 120:
                        title = clean_line
                        break
            
            # 2. 尝试从损坏的 JSON 结构中正则截取 "body" 字段内容
            body_match = re.search(r'"body"\s*:\s*"([\s\S]+?)"\s*,\s*"summary"', raw)
            if body_match:
                body = body_match.group(1)
            else:
                body_match_alt = re.search(r'"body"\s*:\s*"([\s\S]+?)"\s*}', raw)
                if body_match_alt:
                    body = body_match_alt.group(1)
            
            # 处理转义的换行和引号
            body = body.replace("\\n", "\n").replace('\\"', '"').replace('\\t', '\t')
            
            # 3. 尝试抽取摘要
            summary_match = re.search(r'"summary"\s*:\s*"([^"]+)"', raw)
            if summary_match:
                summary = summary_match.group(1)
                
            return {"title": title, "body": body, "summary": summary}
