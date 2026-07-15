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
10. 参考素材摘录是事实边界：只有素材中明确出现的数字、机构名、机制解释才能写成具体事实；素材没有提供来源时，必须改成「可能」「通常」「部分产品」「以营养成分表为准」等保守表达
11. 健康类标题必须弱承诺，避免「才能」「稳得住」「更管用」「治好」「改善」等暗示确定效果的表达
12. 禁止虚构“实测型场景数字”：不得写“我随手拿起某产品看到680毫克”“某品牌每15毫升700毫克”等包装实测细节，除非参考素材摘录中原样提供该数字
13. 尽量不用双引号装饰概念词。除真实人物对话、书名/文件名、法律/指南原文外，不要把普通词语写成“清淡”“健康”“隐形盐”这种形式；直接写清淡、健康、隐形盐
14. 禁止无来源比较型健康结论：素材没有明确比较时，不得写“多一倍”“比回锅肉/热汤面/薯片还高”“超过一天推荐摄入量一半”“最容易”等强比较；改写为“可能比想象中多”“需要额外留意”“并不等于低盐”
15. 不要把蔬菜、高钾食物写成高盐饮食的补救、对冲或抵消方式；只能写“搭配蔬菜让这一餐更均衡”，同时强调少喝汤、少用酱料、控制总钠摄入才是关键

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
        claim_plan: dict | None = None,
    ) -> dict:
        claim_plan_text = json.dumps(claim_plan or {}, ensure_ascii=False, indent=2)
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

## 事实边界与 claim_plan
{claim_plan_text}

请写一篇完整的公众号文章，内容需贴合「{domain}」领域的风格与受众。

写作时必须遵守：
- 不得使用参考素材摘录之外的具体数字、机构名、研究结论或产品检测结果
- 不得为了增强现场感而编造购物、包装、检测、实测数字；可以写“我翻到营养成分表，发现不同产品差异很大”，但不要写具体毫克数
- 不得使用素材没有支撑的倍数、跨食物比较或占比判断，例如多一倍、比某菜还高、超过一天推荐量一半
- 不得写“半天的盐”“十倍”“一整罐盐”“接近一天推荐量的一半”等无来源夸张表达
- 如果素材没有直接出现该生活场景，只能把它作为场景化提醒，不要写成该场景的确定营养结论
- 必须优先服从 claim_plan；如果 angle 和 claim_plan 冲突，以 claim_plan 为准
- claim_plan.must_not_claim 中的内容绝对不能写，也不能换个说法写
- 如果要提醒读者关注某类食品的钠、糖、脂肪等成分，优先写「看营养成分表/配料表」和「不同品牌差异很大」
- 标题从候选中择优时可以改写，必须降低健康疗效承诺感
- 尽量不用双引号装饰普通词语；除真实对话外，少写“清淡”“健康”“刺客”这类加引号的词"""
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
