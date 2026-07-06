"""文稿校验 Agent：敏感词检测、事实校核、公众号合规检查 + 自动修正"""

import json
import os
import re

from app.llm import llm_chat

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_SENSITIVE_WORDS_PATH = os.path.join(_DATA_DIR, "sensitive_words.json")

_CHECK_PROMPT = """你是一个专业的微信公众号文稿审核编辑。你的任务是对一篇文章进行发布前的最终审查。

## 审查维度

### 1. 事实校核
- 文中是否有明显的事实错误或数据矛盾
- 引用的来源是否可信（未经证实的传闻、伪科学内容）
- 是否有过度的夸大表述
- 健康/医疗内容是否存在绝对疗效承诺、未经来源支撑的精确数字、不安全操作建议

### 2. 敏感内容（上下文感知）
- 虽然进行了关键词过滤，但仍需判断上下文是否有隐晦的违规表达
- 是否存在诱导分享、诱导关注的表述
- 是否包含不实的健康/医疗/金融建议

### 3. 公众号内容规范
- 是否有广告法违禁用语
- 是否有侵权风险（未经授权使用他人品牌、肖像等）
- 内容是否符合「公共利益」导向

### 4. 插图 prompt 审核（如有）
- 封面图 prompt 是否与文章主题相关
- 内文插图 prompt 数量是否充足（封面1张 + 内文2-4张）
- 所有 prompt 是否保持水彩绘本风格

## 输出格式（JSON）

{
  "passed": true/false,
  "issues": [
    {
      "type": "factual_error | sensitive_content | compliance | illustration",
      "severity": "blocker | warning | suggestion",
      "location": "问题所在的段落或具体位置",
      "detail": "问题的具体描述",
      "suggestion": "修改建议"
    }
  ],
  "overall_comment": "整体评价（20字以内）"
}

注意：
- passed = false 当且仅当存在 severity 为 "blocker" 的 issues
- 如果只有 warning/suggestion 级别的问题，passed 仍为 true，但需要展示出来
- 客观公正，不要过度审查正常内容
"""

_FIX_PROMPT = """你是一个专业的微信公众号文章修改编辑。根据审核意见对原文进行修改，保留原有风格和结构，只修改有问题的部分。

## 修改原则
1. 保留原文的标题、段落结构和整体风格
2. 只针对 issues 中指出的问题做针对性修改
3. 如果有 blocker 级别问题必须替换/删除对应内容
4. 对于 warning 级别问题，优化表述方式
5. 保持文章的长度和可读性
6. 使用更安全、合规的表述替代违规内容
7. 健康/医疗内容必须删除绝对疗效承诺、未经来源支撑的精确数字和不安全操作建议

## 输出格式（JSON）
{
  "title": "修改后的标题（如标题无问题则保持原样）",
  "body": "修改后的正文（Markdown格式）",
  "summary": "修改后的摘要",
  "changes": "简要说明做了哪些修改"
}
"""


def _load_sensitive_words() -> dict:
    """加载敏感词库"""
    if os.path.exists(_SENSITIVE_WORDS_PATH):
        with open(_SENSITIVE_WORDS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}


class ReviewerAgent:

    def __init__(self):
        self.sensitive_words = _load_sensitive_words()

    async def check(
        self,
        title: str,
        body: str,
        summary: str | None = None,
        cover_prompt: str | None = None,
        illustrations: list | None = None,
    ) -> dict:
        """执行文稿校验：关键词匹配 + LLM 深度审查"""
        issues = []

        # ---- 第一轮：关键词快速匹配 ----
        full_text = f"{title}\n{body}\n{summary or ''}"
        issues.extend(self._local_editorial_precheck(title, body, summary))

        for severity, words in self.sensitive_words.items():
            for word in words:
                if word.endswith("类") or len(word) <= 1:
                    continue
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                matches = list(pattern.finditer(full_text))
                if matches:
                    for m in matches:
                        start = max(0, m.start() - 20)
                        end = min(len(full_text), m.end() + 20)
                        context = full_text[start:end].replace("\n", " ")
                        issues.append({
                            "type": "sensitive_content",
                            "severity": severity,
                            "location": f"...{context}...",
                            "detail": f"匹配到{'违禁词' if severity == 'blocker' else '敏感词'}: 「{word}」",
                            "suggestion": "请替换为合规表述" if severity == "blocker" else "建议替换或用引号标注",
                        })

        # ---- 第二轮：插图 prompt 审核 ----
        illus_list = illustrations or []
        if not cover_prompt and not illus_list:
            issues.append({
                "type": "illustration",
                "severity": "warning",
                "location": "整体",
                "detail": "文章缺少插图 prompt，建议生成封面图和内文插图",
                "suggestion": "生成封面图 + 2-4张内文插图 prompt",
            })
        else:
            if not cover_prompt:
                issues.append({
                    "type": "illustration",
                    "severity": "warning",
                    "location": "封面图",
                    "detail": "缺少封面图 prompt",
                    "suggestion": "生成一张 16:9 的封面图 prompt",
                })
            if len(illus_list) < 2:
                issues.append({
                    "type": "illustration",
                    "severity": "warning",
                    "location": "内文插图",
                    "detail": f"内文插图仅 {len(illus_list)} 张，建议至少 2 张",
                    "suggestion": "为每个主要段落配一张水彩风格插图 prompt",
                })

        # ---- 第三轮：LLM 深度审查 ----
        illus_info = ""
        if cover_prompt or illus_list:
            illus_info = f"""
## 插图 prompt 信息
- 封面图: {'已生成' if cover_prompt else '(无)'}
- 内文插图数量: {len(illus_list)} 张
"""
            for i, ill in enumerate(illus_list, 1):
                illus_info += f"  - 第{i}张: {ill.get('section_title', '未命名')} → {ill.get('prompt', '')[:80]}...\n"

        user_prompt = f"""## 文章标题
{title}

## 文章摘要
{summary or '(无摘要)'}

## 文章正文
{body[:4000]}
{illus_info}

请对以上文章进行内容安全审查。"""

        llm_result = await llm_chat(_CHECK_PROMPT, user_prompt, temperature=0.3, max_tokens=2048)
        llm_issues = self._parse_issues(llm_result)

        existing_details = {i["detail"] for i in issues}
        for li in llm_issues:
            if li["detail"] not in existing_details:
                issues.append(li)
                existing_details.add(li["detail"])

        passed = not any(i["severity"] == "blocker" for i in issues)

        return {
            "passed": passed,
            "issues": issues,
            "overall_comment": llm_result.get("overall_comment", "") if isinstance(llm_result, dict) else "",
            "keyword_hits": len([i for i in issues if i["type"] == "sensitive_content"]),
        }

    def _local_editorial_precheck(self, title: str, body: str, summary: str | None = None) -> list[dict]:
        """Deterministic editorial checks for issues that should not wait for the LLM."""
        text = f"{title}\n{body}\n{summary or ''}"
        issues = []

        overpromise_patterns = [
            r"才能真的?长回来",
            r"一定(会|能)",
            r"彻底(解决|治好|改善)",
            r"根治",
            r"保证(有效|见效)",
            r"必然(有效|改善)",
        ]
        if any(re.search(pattern, text) for pattern in overpromise_patterns):
            issues.append({
                "type": "medical_safety",
                "severity": "blocker",
                "location": "标题/正文",
                "detail": "存在绝对化疗效承诺",
                "suggestion": "改为“可能影响效果”“需要注意”“建议咨询医生”等更稳妥表述",
            })

        health_context_pattern = re.compile(
            r"(米诺地尔|药|用药|头皮|毛囊|发量|脱发|医生|临床|疗效|治疗|诊断|剂量|症状)"
        )
        precise_number_pattern = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|成|小时|分钟|天|周|个月|年)")
        if (
            precise_number_pattern.search(text)
            and health_context_pattern.search(text)
            and not re.search(r"(药品说明|说明书|指南|Mayo|DailyMed|医生建议|医嘱)", text)
        ):
            issues.append({
                "type": "factual_error",
                "severity": "blocker",
                "location": "数据表述",
                "detail": "存在未经来源支撑的精确数字",
                "suggestion": "补充可靠来源，或改成“通常需要一段时间”“应按说明书要求”等克制表达",
            })

        unsafe_terms = ["保鲜膜", "浴帽", "吹风机", "自行加量", "加大剂量", "混用药"]
        hit_terms = [term for term in unsafe_terms if term in text]
        if hit_terms:
            issues.append({
                "type": "medical_safety",
                "severity": "blocker",
                "location": "操作建议",
                "detail": f"出现不安全或不稳妥的健康建议：{'、'.join(hit_terms)}",
                "suggestion": "删除这些建议，改为提前安排用药时间、遵循说明书或咨询医生",
            })

        workflow_artifact_pattern = re.compile(
            r"(【[^】]*(封面图建议|内文插图|配图建议|图片建议|prompt)[^】]*】|"
            r"(封面图建议|内文插图|配图建议|图片建议|prompt)\s*[：:])",
            re.IGNORECASE,
        )
        if workflow_artifact_pattern.search(body):
            issues.append({
                "type": "workflow_artifact",
                "severity": "blocker",
                "location": "正文",
                "detail": "正文泄漏了图片或工作流提示",
                "suggestion": "删除这些面向生成流程的说明；正文只保留读者可直接阅读的内容",
            })

        lifestyle_overpromise_patterns = [
            r"(立刻|马上|瞬间).{0,8}(多装|翻倍|省出|变大|提升)",
            r"(多装|空间|容量).{0,8}(一倍|翻倍|2倍|两倍)",
            r"(减少|节省|省下).{0,6}\d+(?:\.\d+)?\s*(?:%|％|成)",
        ]
        if any(re.search(pattern, text) for pattern in lifestyle_overpromise_patterns):
            issues.append({
                "type": "factual_error",
                "severity": "blocker",
                "location": "标题/正文",
                "detail": "存在未经来源支撑的生活类夸张承诺",
                "suggestion": "改为可验证、弱承诺表达，例如“更好装”“更容易留出空间”“减少临时翻找”",
            })

        plain_bullet_lines = [
            line for line in body.splitlines()
            if re.match(r"^\s*[-*]\s+", line) and not re.match(r"^\s*[-*]\s+步骤：", line)
        ]
        if len(plain_bullet_lines) > 4:
            issues.append({
                "type": "readability",
                "severity": "warning",
                "location": "列表",
                "detail": "普通列表超过 4 条，阅读节奏容易像清单稿",
                "suggestion": "合并为 3-4 条原则，或改成短段落解释",
            })

        return issues

    async def fix(self, title: str, body: str, summary: str | None,
                  issues: list[dict]) -> dict:
        """根据审核意见修正文章"""
        issues_text = json.dumps(issues, ensure_ascii=False, indent=2)
        user_prompt = f"""## 原标题
{title}

## 原摘要
{summary or '(无摘要)'}

## 原文
{body[:5000]}

## 审核问题
{issues_text}

请根据以上审核问题，对原文进行修改。修改时请保持原文风格和结构。"""
        result = await llm_chat(_FIX_PROMPT, user_prompt, temperature=0.5, max_tokens=4096)
        return self._parse_fix_result(result, title, body, summary)

    def _parse_issues(self, raw) -> list[dict]:
        """解析 LLM 审查结果"""
        try:
            if isinstance(raw, str):
                data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            else:
                data = raw
            return data.get("issues", [])
        except (json.JSONDecodeError, AttributeError):
            return []

    def _parse_fix_result(self, raw: str, orig_title: str, orig_body: str, orig_summary: str | None) -> dict:
        """解析 LLM 修正结果，回退到原文"""
        try:
            data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            return {
                "title": data.get("title", orig_title),
                "body": data.get("body", orig_body),
                "summary": data.get("summary", orig_summary),
                "changes": data.get("changes", ""),
            }
        except json.JSONDecodeError:
            return {
                "title": orig_title,
                "body": orig_body,
                "summary": orig_summary,
                "changes": "（LLM解析失败，未做修改）",
            }
