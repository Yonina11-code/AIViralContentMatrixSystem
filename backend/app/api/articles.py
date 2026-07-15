"""文章生成 + 发布 API"""

import io
import json
import re
import uuid
from datetime import datetime
from urllib.parse import quote

import xlrd

from fastapi import APIRouter, Depends, HTTPException, Response, Query, UploadFile, File
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.article import (
    Article,
    ArticleStatus,
    article_status_db_label,
    article_status_from_public_value,
    article_status_public_value,
)
from app.models.content_item import ContentItem
from app.models.asset_card import AssetCard, AssetCategory
from app.agents import EditorInChiefAgent, WriterAgent, PublisherAgent, IllustrationEditorAgent, ReviewerAgent
from app.publishers import WeChatPublisher
from app.llm import LLMConfigurationError, ensure_llm_configured, llm_chat, parse_llm_json

router = APIRouter(prefix="/api/articles", tags=["articles"])
editor_in_chief = EditorInChiefAgent()
writer = WriterAgent()
publisher_agent = PublisherAgent()
illustration_editor = IllustrationEditorAgent()
reviewer = ReviewerAgent()
wechat = WeChatPublisher()


def _content_quality_score(item: ContentItem) -> int:
    """Extract collector quality score from tags; non-WeChat sources stay neutral."""
    if item.source != "wechat":
        return 60
    for tag in item.tags or []:
        if isinstance(tag, str) and tag.startswith("quality:"):
            try:
                return int(tag.split(":", 1)[1])
            except (ValueError, TypeError):
                return 0
    return 0


def _is_auto_selectable_content(item: ContentItem) -> bool:
    """Keep automatic generation away from low-quality WeChat health material."""
    if item.source != "wechat":
        return True
    return _content_quality_score(item) >= 75


def _sort_content_for_generation(items: list[ContentItem]) -> list[ContentItem]:
    """Prefer high-quality WeChat material, then newer collected content."""
    return sorted(
        items,
        key=lambda item: (
            _content_quality_score(item),
            item.published_at or item.collected_at or datetime.min,
            item.collected_at or datetime.min,
        ),
        reverse=True,
    )


def _trim_text(text: str | None, limit: int = 1200) -> str:
    if not text:
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _normalize_lookup_text(text_value: str | None) -> str:
    if not text_value:
        return ""
    return re.sub(r"[\s《》<>【】\[\]（）()|｜:：，,。.!！?？、\-—_]+", "", text_value).lower()


def _article_retry_focus(article: Article) -> str:
    trace = article.agent_trace if isinstance(article.agent_trace, list) else []
    decision = trace[0] if trace and isinstance(trace[0], dict) else {}
    topic = decision.get("selected_topic") or article.title
    angle = decision.get("angle") or ""
    issues = []
    if len(trace) > 3 and isinstance(trace[3], dict):
        review = trace[3].get("second_review") or trace[3].get("review") or {}
        if isinstance(review, dict):
            issues = [x.get("detail") or x.get("suggestion") for x in review.get("issues", []) if isinstance(x, dict)]
    issue_text = "\n".join(f"- {x}" for x in issues[:5] if x)
    return (
        f"请基于失败记录重新生成文章。保留原选题：{topic}。\n"
        f"原角度：{angle}\n"
        "必须修复上次审核失败的问题，所有具体数字、比较、医学/营养结论都必须来自素材，素材未提供时改成保守表达。"
        + (f"\n上次失败问题：\n{issue_text}" if issue_text else "")
    )


async def _infer_retry_content_ids(article: Article, db: AsyncSession) -> list[str]:
    source_ids = article.source_content_ids if isinstance(article.source_content_ids, list) else []
    if source_ids:
        return [str(x) for x in source_ids if x]

    trace = article.agent_trace if isinstance(article.agent_trace, list) else []
    decision = trace[0] if trace and isinstance(trace[0], dict) else {}
    reference_text = " ".join(str(x) for x in decision.get("source_references", []) if x)
    haystack = _normalize_lookup_text(" ".join([reference_text, decision.get("reason", "")]))
    if not haystack:
        return []

    rows = (await db.execute(select(ContentItem).order_by(ContentItem.collected_at.desc()).limit(300))).scalars().all()
    matched: list[str] = []
    for item in rows:
        title_key = _normalize_lookup_text(item.title)
        source_key = _normalize_lookup_text(item.source_name)
        if title_key and (title_key in haystack or haystack in title_key):
            matched.append(item.id)
        elif source_key and source_key in haystack and title_key and any(part and part in haystack for part in re.split(r"[，,：:|｜]", item.title)):
            matched.append(item.id)
        if len(matched) >= 5:
            break
    return matched


def _build_source_materials(items: list[ContentItem]) -> str:
    """Build grounded source excerpts for the writer instead of passing titles only."""
    if not items:
        return "无可用参考素材正文。请只做保守、常识性表达，不编造具体数字或来源。"

    blocks = []
    for idx, item in enumerate(items[:8], 1):
        excerpt = _trim_text(item.body or item.summary, limit=1400)
        if not excerpt:
            excerpt = "（该素材没有正文摘录；只能引用其标题和来源，不得补写具体数字或机构结论。）"
        blocks.append(
            "\n".join([
                f"### 素材 {idx}",
                f"- 标题：{item.title}",
                f"- 来源：{item.source_name or item.source}",
                f"- 领域：{item.domain}",
                f"- 链接：{item.url or '无'}",
                f"- 摘录：{excerpt}",
            ])
        )
    return "\n\n".join(blocks)


def _normalize_claim_plan(decision: dict, source_materials: str | None) -> dict:
    """Ensure writer receives a source-grounded claim plan, with risky mechanisms downgraded."""
    raw_plan = decision.get("claim_plan") if isinstance(decision.get("claim_plan"), dict) else {}
    text_to_check = "\n".join([
        decision.get("selected_topic", ""),
        decision.get("angle", ""),
        raw_plan.get("core_claim", ""),
        " ".join(raw_plan.get("must_not_claim", []) or []),
    ])
    source = source_materials or ""
    source_norm = _normalize_claim_text(source)

    plan = {
        "core_claim": raw_plan.get("core_claim") or decision.get("angle") or decision.get("selected_topic", ""),
        "supported_by_source": bool(raw_plan.get("supported_by_source", True)),
        "must_not_claim": list(raw_plan.get("must_not_claim") or []),
    }

    glucose_terms = re.compile(r"(白粥|粥|米饭|碳水|血糖|升糖|胰岛素|糖尿病)")
    source_has_glucose_support = any(term in source_norm for term in ["血糖", "升糖", "胰岛素", "糖尿病", "碳水"])
    if glucose_terms.search(text_to_check) and not source_has_glucose_support:
        plan["supported_by_source"] = False
        plan["core_claim"] = (
            "素材未支持血糖或胰岛素机制；只能围绕素材中的控盐、隐形盐、控油、"
            "高油素食、饮食均衡、规律服药和必要时咨询医生来写。"
        )
        plan["must_not_claim"].extend([
            "不要写白粥升糖导致血压波动",
            "不要写胰岛素促进钠重吸收导致血压上升",
            "不要把血糖/胰岛素机制作为主线",
        ])

    oil_sodium_terms = re.compile(r"(食用油|植物油|花生油|调味油|复合油).{0,30}(隐形钠|含钠|含盐|加盐)")
    if oil_sodium_terms.search(text_to_check) and not _source_supports_oil_sodium_claim(source):
        plan["supported_by_source"] = False
        plan["core_claim"] = (
            "素材未支持食用油是隐形钠来源；如果写厨房用油，只能围绕控油、"
            "高油饮食、血脂、血管状态和烹饪方式来写。"
        )
        plan["must_not_claim"].extend([
            "不要写食用油本身是隐形钠来源",
            "不要写调味油或复合油含钠会影响血压，除非素材明确提供",
        ])

    takeaway_terms = re.compile(r"(外卖|酸菜鱼|麻辣烫|黄焖鸡|调料包|调味包|酱料包|汤底)")
    unsupported_takeaway_comparison = re.compile(r"(半天的盐|一天推荐量的一半|全天推荐摄入量的一半|一半|十倍|多一倍|比[^，。！？!?；;]{1,16}(?:还|更)(?:咸|高|多))")
    source_has_takeaway_support = any(term in source_norm for term in ["外卖", "酸菜鱼", "麻辣烫", "黄焖鸡", "调料包", "酱料包", "汤底"])
    if takeaway_terms.search(text_to_check) and unsupported_takeaway_comparison.search(text_to_check) and not source_has_takeaway_support:
        plan["supported_by_source"] = False
        plan["core_claim"] = (
            "素材未支持外卖、调料包或汤底的具体钠含量比较；如果写外卖场景，"
            "只能作为控盐/隐形盐的生活化演绎，提醒少用酱料、少喝汤、看配料和控制总钠摄入。"
        )
        plan["must_not_claim"].extend([
            "不要写外卖有半天的盐",
            "不要写一份外卖接近或超过全天推荐摄入量的一半",
            "不要写酸菜鱼、麻辣烫、黄焖鸡等外卖品类的钠含量强比较",
            "不要写比鸡汤咸十倍或类似倍数标题",
        ])

    cold_dish_terms = re.compile(r"(凉拌菜|凉菜|拍黄瓜|拌黄瓜|凉拌)")
    sauce_salt_terms = re.compile(r"(酱料|生抽|酱油|蚝油|辣椒酱|卤汁|豆瓣酱).{0,40}(钠|盐|含钠|含盐|隐形盐)")
    source_has_cold_dish_support = any(term in source_norm for term in ["凉拌菜", "凉菜", "拍黄瓜", "拌黄瓜", "凉拌", "蚝油", "辣椒酱", "卤汁"])
    if cold_dish_terms.search(text_to_check) and sauce_salt_terms.search(text_to_check) and not source_has_cold_dish_support:
        plan["supported_by_source"] = False
        plan["core_claim"] = (
            "素材只支持控盐、少放酱油/味精/豆瓣酱和警惕隐形盐；凉拌菜只能作为生活化场景切入，"
            "不能写成素材已证明的凉拌菜酱料钠含量营养结论。"
        )
        plan["must_not_claim"].extend([
            "不要把凉拌菜酱料写成素材已证明的隐形盐大户或营养结论",
            "不要写凉拌菜里的盐/钠比炒菜、热汤面或其他菜更多",
            "不要写生抽、蚝油、辣椒酱、卤汁的具体钠含量或毫克数，除非素材明确提供",
            "不要用口干、喝水、眼皮浮肿、手指发胀来判断钠摄入偏高",
            "凉拌菜只能作为控盐场景，核心建议应回到少放酱油、味精、豆瓣酱和查看配料/营养成分表",
        ])

    plan["must_not_claim"] = list(dict.fromkeys([item for item in plan["must_not_claim"] if item]))
    return plan


def _normalize_generated_title(written: dict, decision: dict) -> str:
    """Keep malformed writer output from using a body paragraph as the article title."""
    title = (written.get("title") or "").strip()
    candidates = [c for c in (decision.get("suggested_title_candidates") or []) if isinstance(c, str) and c.strip()]
    fallback = candidates[0].strip() if candidates else (decision.get("selected_topic") or "未命名文章").strip()

    sentence_count = len(re.findall(r"[。！？!?]", title))
    if not title or len(title) > 48 or sentence_count >= 2 or "\n" in title:
        return fallback
    return title


def _normalize_claim_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _find_unsupported_precise_claims(text: str, source_materials: str | None) -> list[str]:
    """Find health-sensitive exact numbers in generated text that are absent from source excerpts."""
    if not text:
        return []

    source_norm = _normalize_claim_text(source_materials or "")
    claim_pattern = re.compile(
        r"\d+(?:\.\d+)?\s*(?:到|至|~|-|—|－)?\s*\d*(?:\.\d+)?\s*"
        r"(?:毫克|mg|克|g|%|％|mmhg|毫米汞柱|毫升|ml|周|天|个月|年)",
        re.IGNORECASE,
    )
    health_context_pattern = re.compile(
        r"(钠|盐|酱油|血压|高血压|低盐|减盐|薄盐|控盐|膳食|营养|味蕾|心率|酒精|药|症状)"
    )

    unsupported: list[str] = []
    seen: set[str] = set()
    label_basis_units = {
        "100克", "100g", "100毫升", "100ml",
        "每100克", "每100g", "每100毫升", "每100ml",
    }
    for match in claim_pattern.finditer(text):
        claim = match.group(0).strip()
        if _normalize_claim_text(claim) in {_normalize_claim_text(unit) for unit in label_basis_units}:
            continue
        start = max(0, match.start() - 24)
        end = min(len(text), match.end() + 24)
        context = text[start:end]
        if not health_context_pattern.search(context):
            continue
        claim_norm = _normalize_claim_text(claim)
        if claim_norm and claim_norm not in source_norm and claim_norm not in seen:
            unsupported.append(claim)
            seen.add(claim_norm)
    return unsupported


def _split_claim_sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？!?；;])\s*|\n+", text or "")
        if part.strip()
    ]


def _source_supports_oil_sodium_claim(source_materials: str | None) -> bool:
    source = source_materials or ""
    oil_terms = r"(食用油|植物油|花生油|橄榄油|亚麻籽油|核桃油|紫苏油|调味油|复合油|炒菜油|厨房用油)"
    sodium_terms = r"(钠|含钠|盐|含盐|隐形钠|隐形盐)"
    for sentence in _split_claim_sentences(source):
        if re.search(oil_terms, sentence) and re.search(sodium_terms, sentence):
            return True
    return False


def _find_unsupported_core_claims(text: str, source_materials: str | None) -> list[str]:
    """Find generated core health claims that shift beyond the selected source material."""
    if not text or not source_materials:
        return []

    unsupported: list[str] = []
    seen: set[str] = set()
    oil_terms = r"(食用油|植物油|花生油|橄榄油|亚麻籽油|核桃油|紫苏油|调味油|复合油|炒菜油|厨房用油|那瓶油)"
    sodium_terms = r"(隐形钠|含钠|钠含量|含盐|加盐|含钠添加剂)"
    source_supports_oil_sodium = _source_supports_oil_sodium_claim(source_materials)

    for sentence in _split_claim_sentences(text):
        if re.search(oil_terms, sentence) and re.search(sodium_terms, sentence) and not source_supports_oil_sodium:
            normalized = _normalize_claim_text(sentence)
            if normalized not in seen:
                unsupported.append(sentence)
                seen.add(normalized)

    return unsupported


def _find_unsupported_relative_claims(text: str, source_materials: str | None) -> list[str]:
    """Find unsupported comparative health claims such as倍数、超过一半、比某菜更高."""
    if not text or not source_materials:
        return []

    source_norm = _normalize_claim_text(source_materials)
    unsupported: list[str] = []
    seen: set[str] = set()
    salt_context = re.compile(r"(盐|钠|咸|控盐|减盐|低盐|高血压|血压|调料|调味|生抽|酱油|蚝油|凉拌菜|外卖|酸菜鱼|麻辣烫|汤底|酱料|酱料包|粉包|泡面|面饼)")
    relative_patterns = [
        r"[^。！？!?；;\n]{0,24}(?:超过|超出|远高于|接近|比|占到|高出|多出)[^。！？!?；;\n]{0,24}(?:一倍|两倍|十倍|几倍|半天|半|一半|三分之一|六成|七成|八成|推荐量|推荐摄入量|回锅肉|热汤面|薯片|咸菜|鸡汤|面饼)[^。！？!?；;\n]{0,24}",
        r"[^。！？!?；;\n]{0,24}(?:半天的盐|一天推荐量的一半|全天推荐摄入量的一半|推荐摄入量一半)[^。！？!?；;\n]{0,24}",
        r"[^。！？!?；;\n]{0,24}(?:比[^。！？!?；;\n]{1,12}(?:还|更)(?:高|多|咸))[^。！？!?；;\n]{0,24}",
        r"[^。！？!?；;\n]{0,24}(?:最容易|最常见|大户|推手)[^。！？!?；;\n]{0,24}",
    ]

    for pattern in relative_patterns:
        for match in re.finditer(pattern, text):
            claim = match.group(0).strip(" ，。！？!?；;\n")
            if not claim or not salt_context.search(claim):
                continue
            claim_norm = _normalize_claim_text(claim)
            if claim_norm in source_norm or claim_norm in seen:
                continue
            unsupported.append(claim)
            seen.add(claim_norm)
    return unsupported


def _apply_source_boundary_fallback(written: dict, unsupported_claims: list[str]) -> dict:
    """Deterministically soften source-unsupported numeric claims after LLM repair."""
    if not unsupported_claims:
        return written

    updated = dict(written)
    title = updated.get("title", "")
    body = updated.get("body", "")
    summary = updated.get("summary", "")

    has_oil_sodium_claim = any(re.search(r"(油|花生油|橄榄油|调味油|复合油).{0,20}(钠|盐|隐形钠|含钠)", claim) for claim in unsupported_claims)
    if has_oil_sodium_claim:
        title = title.replace("比酱油更影响你的血压", "也会影响你的血压管理")
        title = title.replace("可能比酱油更值得你关注", "也值得你关注")
        body = re.sub(r"##\s*你以为在吃油，其实可能在吃[“\"]隐形钠[”\"]", "## 控盐之外，控油也别忽略", body)
        body = re.sub(r"先别急着把油瓶扔了。.*?如果每100克含钠量较高，那就得留个心眼了——它可能比你想象的更[“\"]咸[”\"]。", "先别急着把油瓶扔了。素材真正提醒我们的不是“油里藏着多少钠”，而是高油饮食同样会拖累血脂和血管状态。植物油、坚果、油炸豆制品这些看起来不咸的食物，如果吃得太多，也可能让血压管理变得更难。所以下次做饭时，除了少放盐，也要留意油放了多少、怎么烹饪。", body, flags=re.DOTALL)
        body = re.sub(r"有些油本身就可能含钠。", "高油饮食本身就值得留意。", body)
        body = re.sub(r"市面上很多调味油、复合油、甚至某些[“\"]炒菜香[”\"]的花生油，在生产过程中会加入盐或其他含钠添加剂来提升风味。", "一些调味油、复合油的配料更复杂，购买时可以顺手看一眼配料表和营养成分表。", body)
        body = re.sub(r"不同品牌含钠量可能存在差异，有的每100克含钠量能差出不少。", "不同品牌配方可能存在差异，建议购买时查看配料表和营养成分表。", body)
        body = re.sub(r"就算每克油含钠很少，累积起来也不容小觑。", "油本身热量高，用量一多也不容小觑。", body)
        body = body.replace("翻到背面看营养成分表，重点看“钠”那一栏。", "翻到背面看配料表和营养成分表。")
        body = body.replace("下次打开厨房柜门的时候，不妨多看一眼那瓶油——它可能比酱油更值得你关注。", "下次打开厨房柜门的时候，不妨多看一眼那瓶油——用油习惯也值得你关注。")
        summary = re.sub(r"油的[“\"]隐形钠[”\"]、?", "", summary)
        summary = summary.replace("厨房用油对血压的影响", "厨房用油习惯对血压管理的影响")
        if "用油习惯" not in summary:
            summary = "本文提醒关注厨房用油习惯、高温烹饪和高油饮食对血压管理的影响，并给出更稳妥的选油和用油建议。"
        if "高油饮食" not in body:
            body = body.replace("## 控盐之外，控油也别忽略", "## 控盐之外，控油也别忽略\n\n高油饮食会通过血脂、体重和血管状态，间接影响血压管理。")

    title = re.sub(r"[:：]?这些食品的盐比薯片还多", "：这些食品可能藏着不少盐", title)
    title = title.replace("比薯片还多", "可能并不低")
    title = re.sub(r"那碟凉拌菜里的盐，比你想象的多一倍", "那碟凉拌菜，可能没有你想的那么清淡", title)
    title = title.replace("比你想象的多一倍", "可能比你想的多")
    title = re.sub(r"外卖小哥递过来的不只是饭，还有半天的盐", "点外卖时，调料包和汤底要多留意", title)
    title = re.sub(r"那碗酸菜鱼里的汤，可能比[^，。！？!?；;]{1,16}咸十倍", "那碗酸菜鱼里的汤，可能比你想的更该少喝", title)
    title = title.replace("半天的盐", "不少隐形盐")
    title = re.sub(r"一片吐司下肚，你吃进去的钠可能比半碗挂面还多", "加工主食里的钠，可能比你想象中多", title)
    title = re.sub(r"一片面包里的钠，可能比你炒菜放的盐还多", "一片面包里的钠，可能比你想象中多", title)

    body = re.sub(r"钠的?摄入量可能比炒一盘回锅肉还高", "钠摄入可能比你想象中高", body)
    title = re.sub(r"凉拌菜里那勺盐，比你想象的可能要多", "凉拌菜看着清爽，调味料也别忽略", title)
    title = re.sub(r"凉拌菜里那勺盐，?可能比你炒菜加的还多", "凉拌菜看着清爽，调味料也别忽略", title)
    body = re.sub(r"##\s*酱料才是真正的[“\"]?隐形盐大户[”\"]?", "## 看着清爽，也别忽略调味料", body)
    body = re.sub(r"酱料才是真正的[“\"]?隐形盐大户[”\"]?", "调味料也值得留意", body)
    body = re.sub(r"有的生抽每?\s*\d+\s*(?:毫升|ml|mL)[^。！？!?；;]*。", "不同调味品的配方差异很大，使用前可以看一眼配料表和营养成分表。", body)
    body = re.sub(r"有的生抽[^。！？!?；;]*(?:\d+多?毫克|\d+\s*mg)[^。！？!?；;]*。", "不同调味品的配方差异很大，使用前可以看一眼配料表和营养成分表。", body, flags=re.IGNORECASE)
    body = re.sub(r"凉拌菜的钠可能比[^。！？!?；;]{1,18}(?:还|更)?(?:多|高|咸)[^。！？!?；;]*。", "凉拌菜本身可以很清爽，但调味料用量仍然要留意。", body)
    body = re.sub(r"如果你吃完凉拌菜后[^。！？!?；;]*(?:口干|想喝水|眼皮|手指|发胀|浮肿)[^。！？!?；;]*。", "如果你需要控制血压或日常盐摄入，更稳妥的做法是少放酱油、味精、豆瓣酱，并留意加工食品里的隐形盐。", body)
    summary = re.sub(r"凉拌菜里的盐可能比你想象中多", "凉拌菜看着清爽，但调味料也要留意", summary)
    summary = re.sub(r"吃完[^。！？!?；;]*(?:口干|想喝水|眼皮|手指|发胀|浮肿)[^。！？!?；;]*。?", "", summary)
    body = re.sub(r"钠含量可能比一碗热汤面还高", "钠含量可能并不低", body)
    body = re.sub(r"钠摄入总量可能比一个正常吃咸菜的人还高", "钠摄入总量可能比你想象中高", body)
    body = re.sub(r"那两片吐司里的钠，可能比你中午炒菜放的盐还多", "那两片吐司里的钠，可能比你想象中多", body)
    body = re.sub(r"一片吐司[^。！？!?；;]*比半碗挂面还多", "加工主食里的钠，可能比你想象中多", body)
    body = re.sub(r"可能是超过一天推荐摄入量一半的钠", "可能已经摄入了不少钠", body)
    body = re.sub(r"超过一天推荐摄入量一半的钠", "不少钠", body)
    body = re.sub(r"每100克含钠明显偏高，可以算作相对低钠的选择。", "可以对比不同产品，优先选择钠含量较低的那一款。", body)
    body = re.sub(r"尽量选每100克钠含量在明显偏高以下的。", "尽量选同类产品里钠含量较低的。", body)
    body = re.sub(r"选择每100克钠含量明显偏高的([^，。！？!?；;]*)", r"选择钠含量较低的\1", body)
    body = re.sub(r"里面的盐可能已经接近一天推荐量的一半", "里面的盐可能已经不少", body)
    body = re.sub(r"接近(?:或超过)?(?:一|全)天推荐(?:摄入)?量的一半", "已经不少", body)
    body = re.sub(r"还有一个补救办法：额外加一份蔬菜。", "更稳妥的做法，是少喝汤、少用酱料，再搭配一份蔬菜。", body)
    body = re.sub(r"蔬菜里含有钾，钾能帮助身体代谢多余的钠，辅助平衡钠钾摄入。", "蔬菜能增加钾和膳食纤维摄入，让这一餐更均衡；但它不能抵消已经吃进去的盐。", body)
    body = re.sub(r"可以用这种方式帮身体代谢一下", "可以把下一餐吃得更清淡一些", body)
    body = re.sub(r"搭配一些高钾食物[^。！？!?]*可以帮助身体排出多余的钠。", "搭配蔬菜和水果能让这一餐更均衡，但不能抵消已经吃进去的盐。", body)
    body = re.sub(r"高钾食物[^。！？!?]*帮助身体排出多余的钠", "搭配蔬菜和水果让饮食更均衡", body)
    body = re.sub(r"酱料包[^。！？!?]*钠含量[^。！？!?]*比面饼[^。！？!?]*。", "酱料包和汤底同样值得留意，不能只盯着面饼。", body)
    body = re.sub(r"一些产品里，酱料包和粉包加起来的钠含量[^。！？!?]*。", "不同产品差异很大，酱料包、粉包和面饼都要看营养成分表。", body)
    body = re.sub(r"常见泡面每百克钠含量通常在[^。！？!?]*。", "不同品牌、不同口味的泡面钠含量差异很大。", body)
    body = re.sub(r"泡面时，酱料包只放[^。！？!?]*。", "泡面时，酱料包可以先少放一点，尝过之后再决定要不要继续加。", body)
    body = re.sub(r"下次泡面时，[^。！？!?]*只放一半[^。！？!?]*。", "下次泡面时，可以先少放一点酱料，尝过之后再调整。", body)
    body = re.sub(r"用开水涮一下酱料包再挤[^。！？!?]*。", "如果想控盐，更直接的做法是少放酱料、少喝汤。", body)
    body = re.sub(r"这样能冲掉一部分盐分[^。！？!?]*。?", "", body)
    summary = re.sub(r"凉拌菜里的盐可能比[^，。！？!?；;]+还高", "凉拌菜里的盐可能比你想象中多", summary)
    summary = summary.replace("用额外蔬菜帮助代谢钠摄入", "搭配蔬菜并控制总钠摄入")
    summary = summary.replace("帮助代谢钠摄入", "让这一餐更均衡")
    summary = summary.replace("搭配高钾食物帮助身体排出多余的钠", "搭配蔬菜并控制总钠摄入")
    summary = summary.replace("帮助身体排出多余的钠", "让饮食更均衡")
    summary = summary.replace("可以轻松减少钠摄入", "有助于减少不必要的钠摄入")

    numeric_claims = [
        claim for claim in unsupported_claims
        if not re.search(r"100\s*(?:克|g|毫升|ml)", claim, re.IGNORECASE)
        and not re.search(r"(酱料包|粉包|泡面|面饼|一半|三分之一|六成|数百|上千)", claim)
    ]
    for claim in numeric_claims:
        escaped = re.escape(claim)
        body = re.sub(
            rf"每份（通常是[^）]*{escaped}[^）]*）的钠含量是多少毫克",
            "每份钠含量是多少",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            rf"看每份（通常是[^）]*{escaped}[^）]*）的含量",
            "看每份钠含量",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            rf"每份（通常是[^）]*{escaped}[^）]*）",
            "每份",
            body,
            flags=re.IGNORECASE,
        )
        body = re.sub(
            rf"(?:超过|高于|低于|达到|约|大约)?\s*{escaped}\s*(?:/\s*100\s*(?:g|克))?",
            "明显偏高",
            body,
            flags=re.IGNORECASE,
        )
        summary = re.sub(
            rf"(?:超过|高于|低于|达到|约|大约)?\s*{escaped}\s*(?:/\s*100\s*(?:g|克))?",
            "明显偏高",
            summary,
            flags=re.IGNORECASE,
        )

    body = re.sub(r"许多蚝油产品每明显偏高里?的钠含量[^。]*。", "许多蚝油产品的钠含量并不低。", body)
    body = re.sub(r"每明显偏高里?的钠含量", "钠含量", body)
    body = re.sub(r"每明显偏高", "", body)
    body = re.sub(r"快明显偏高", "不少", body)
    body = re.sub(r"([^。！？!?；;]{0,18})钠含量可达明显偏高", r"\1钠含量可能较高", body)
    body = re.sub(r"钠含量甚至达到每100克明显偏高以上", "钠含量可能较高", body)
    body = re.sub(r"每日减少明显偏高盐的摄入，血压可能下降明显偏高", "减少盐摄入有助于血压管理", body)
    body = re.sub(r"一汤匙酱油大约含明显偏高盐", "一汤匙酱油含盐量不低", body)
    body = re.sub(r"可能明显偏高", "可能比你想象中多", body)
    body = re.sub(r"每100克含钠明显偏高，可以算作相对低钠的选择。", "可以对比不同产品，优先选择钠含量较低的那一款。", body)
    body = re.sub(r"尽量选每100克钠含量在明显偏高以下的。", "尽量选同类产品里钠含量较低的。", body)
    body = re.sub(r"选择每100克钠含量明显偏高的([^，。！？!?；;]*)", r"选择钠含量较低的\1", body)
    body = re.sub(r"每份（通常是(?:明显偏高)(?:或明显偏高)+）的钠含量是多少毫克", "每份钠含量是多少", body)
    body = re.sub(r"看每份（通常是明显偏高）?的含量", "看每份钠含量", body)
    body = re.sub(r"每份（通常是明显偏高(?:或明显偏高)*）", "每份", body)
    summary = re.sub(r"每明显偏高", "", summary)
    summary = re.sub(r"快明显偏高", "不少", summary)
    summary = re.sub(r"选择每100克钠含量明显偏高的([^，。！？!?；;]*)", r"选择钠含量较低的\1", summary)
    summary = summary.replace("每100克钠含量明显偏高", "钠含量较低")

    body = re.sub(r"如果每100克钠含量明显偏高，建议放回去。", "如果钠含量明显偏高，建议谨慎选择。", body)
    body = re.sub(r"钠含量明显偏高/100g", "钠含量明显偏高", body, flags=re.IGNORECASE)
    summary = re.sub(r"钠含量明显偏高就放回去", "钠含量明显偏高就谨慎选择", summary)
    summary = re.sub(r"钠含量明显偏高/100g", "钠含量明显偏高", summary, flags=re.IGNORECASE)

    updated["title"] = title
    updated["body"] = body
    updated["summary"] = summary
    existing_changes = updated.get("changes", "")
    fallback_note = "本地来源边界校验已将素材未支撑的具体数字改为定性表达。"
    updated["changes"] = f"{existing_changes}\n{fallback_note}".strip()
    return updated


def _append_source_boundary_issues(review_result: dict, written: dict, source_materials: str | None) -> dict:
    if not source_materials:
        return review_result

    text = "\n".join([
        written.get("title", ""),
        written.get("body", ""),
        written.get("summary", "") or "",
    ])
    unsupported = _find_unsupported_precise_claims(text, source_materials)
    unsupported_core = _find_unsupported_core_claims(text, source_materials)
    unsupported_relative = _find_unsupported_relative_claims(text, source_materials)
    unsupported_all = unsupported + unsupported_core + unsupported_relative
    if not unsupported_all:
        return review_result

    issues = list(review_result.get("issues", []))
    detail = "素材未提供这些健康/营养具体数字或核心论点，请删除、改成素材支持的表达：" + "、".join(unsupported_all[:8])
    if detail not in {issue.get("detail") for issue in issues}:
        issues.append({
            "type": "factual_error",
            "severity": "blocker",
            "location": "标题/正文/摘要中的具体数字",
            "detail": detail,
            "suggestion": "不得编造包装实测数字或素材没有的核心论点；如果素材只支持控油，请回到“高油饮食、血脂、血管、烹饪方式”等稳妥表达。",
        })
    updated = dict(review_result)
    updated["issues"] = issues
    updated["passed"] = False
    return updated


async def _summarize_content_pool(
    db: AsyncSession,
    domain: str | None = None,
    item_ids: list[str] | None = None
) -> tuple[str, list[ContentItem]]:
    """从 Content Pool 中生成摘要用于总编决策，排除已使用过的内容（若指定了特定的 item_ids 则直接使用它们作为数据源）"""
    if item_ids:
        query = select(ContentItem).where(ContentItem.id.in_(item_ids))
        rows = (await db.execute(query)).scalars().all()
    else:
        query = select(ContentItem).where(ContentItem.used_at.is_(None)).order_by(ContentItem.collected_at.desc())
        if domain:
            query = query.where(ContentItem.domain == domain)
        query = query.limit(100)
        rows = (await db.execute(query)).scalars().all()
        rows = _sort_content_for_generation([r for r in rows if _is_auto_selectable_content(r)])[:30]

    if not rows:
        return "暂无采集数据", []
    summaries = []
    for r in rows:
        quality_note = f", 质量分: {_content_quality_score(r)}" if r.source == "wechat" else ""
        summaries.append(f"- [{r.source}] {r.title} (ID: {r.id}, 来源: {r.source_name}, 领域: {r.domain}{quality_note})")
    return "\n".join(summaries), rows


async def _summarize_assets(db: AsyncSession) -> str:
    """从资产库中提取可用模板"""
    query = select(AssetCard).where(
        AssetCard.category.in_([
            AssetCategory.TITLE_TEMPLATE,
            AssetCategory.OPENING_TEMPLATE,
            AssetCategory.PROMPT_TEMPLATE,
        ])
    ).order_by(AssetCard.score.desc()).limit(20)
    rows = (await db.execute(query)).scalars().all()
    if not rows:
        return "可用模板：暂无，Agent 将自行创作"
    summaries = []
    for r in rows:
        excerpt = (r.content or "").strip().replace("\n", " ")
        if len(excerpt) > 240:
            excerpt = excerpt[:240].rstrip() + "..."
        summaries.append(f"- ID:{r.id} [{r.category.value}] {r.name} (评分: {r.score}, 使用: {r.usage_count})：{excerpt}")
    return "\n".join(summaries)


async def _list_recent_article_titles(db: AsyncSession, limit: int = 20) -> list[str]:
    """获取近期文章标题，供总编去重参考"""
    query = select(Article.title).order_by(Article.created_at.desc()).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    return rows


async def _review_and_repair_written(
    written: dict,
    review_agent: ReviewerAgent,
    source_materials: str | None = None,
) -> tuple[dict, dict, bool]:
    """Review raw Markdown, repair blockers once, then recheck before article creation."""
    review_result = await review_agent.check(
        title=written.get("title", ""),
        body=written.get("body", ""),
        summary=written.get("summary", ""),
    )
    review_result = _append_source_boundary_issues(review_result, written, source_materials)
    review_trace = {"review": review_result}
    if review_result["passed"] and not _has_repairable_review_issues(review_result):
        return written, review_trace, True

    fixed = await review_agent.fix(
        title=written.get("title", ""),
        body=written.get("body", ""),
        summary=written.get("summary", ""),
        issues=review_result["issues"],
    )
    repaired = dict(written)
    repaired["title"] = fixed["title"]
    repaired["body"] = fixed["body"]
    repaired["summary"] = fixed["summary"]
    if source_materials:
        repaired_text = "\n".join([repaired.get("title", ""), repaired.get("body", ""), repaired.get("summary", "") or ""])
        remaining_unsupported = (
            _find_unsupported_precise_claims(repaired_text, source_materials)
            + _find_unsupported_core_claims(repaired_text, source_materials)
            + _find_unsupported_relative_claims(repaired_text, source_materials)
        )
        fallback_fixed = _apply_source_boundary_fallback({**fixed, **repaired}, remaining_unsupported)
        repaired["title"] = fallback_fixed["title"]
        repaired["body"] = fallback_fixed["body"]
        repaired["summary"] = fallback_fixed["summary"]
        fixed = fallback_fixed
    review_trace["fixed"] = fixed

    second_review = await review_agent.check(
        title=repaired.get("title", ""),
        body=repaired.get("body", ""),
        summary=repaired.get("summary", ""),
    )
    second_review = _append_source_boundary_issues(second_review, repaired, source_materials)
    review_trace["second_review"] = second_review
    return repaired, review_trace, second_review["passed"]


def _has_repairable_review_issues(review_result: dict) -> bool:
    """Repair health/factual warnings once so drafts do not silently keep risky claims."""
    repairable_types = {"factual_error", "medical_safety", "compliance"}
    for issue in review_result.get("issues", []):
        if issue.get("type") in repairable_types and issue.get("severity") in {"warning", "blocker"}:
            return True
    return False


from pydantic import BaseModel

class GenerateParams(BaseModel):
    domain: str = "tech"
    item_ids: list[str] | None = None
    focus: str | None = None


class IllustrationUploadParams(BaseModel):
    type: str  # "cover" 或者索引数字如 "0", "1"
    image_url: str


class ArticleBatchDeleteRequest(BaseModel):
    ids: list[str]


def _normalize_batch_delete_ids(ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in ids:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    if not normalized:
        raise ValueError("ids 不能为空")
    return normalized


@router.post("/generate")
async def generate_article(
    params: GenerateParams,
    db: AsyncSession = Depends(get_db),
):
    """根据自定义素材或全自动选题生成一篇文章：总编 -> 正文 -> 审核 -> 发布"""
    try:
        ensure_llm_configured()
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    domain = params.domain
    item_ids = params.item_ids
    focus = params.focus

    # Step 1: 总编选题
    pool_summary, pool_items = await _summarize_content_pool(db, domain=domain, item_ids=item_ids)
    if not pool_items:
        return {"error": "暂无可用素材，请重新选择或先采集内容", "id": None}

    # 强力注入用户的自定义侧重点到总编提示词
    if focus:
        pool_summary += f"\n\n## 用户指定的文章选题侧重点/自定义要求（你必须严格遵守此限制，围绕此侧重点来决策和构思 angle）：\n{focus}\n"

    # 附上已有文章标题，避免重复选题
    recent_titles = await _list_recent_article_titles(db)
    if recent_titles:
        pool_summary += f"\n\n## 已发表过的文章标题（请避免重复选题）\n" + "\n".join(f"- \"{t}\"" for t in recent_titles)

    # 数据驱动：注入历史表现参考
    perf_rows = (await db.execute(
        text("""
            SELECT a.status, a.read_count, a.share_count, a.created_at
            FROM articles a
            WHERE a.status = :published_status
            ORDER BY a.created_at DESC
            LIMIT 50
        """),
        {"published_status": article_status_db_label(ArticleStatus.PUBLISHED)},
    )).all()
    if perf_rows:
        total = len(perf_rows)
        avg_reads = sum(r[1] or 0 for r in perf_rows) / total if total > 0 else 0
        # 计算每篇文章的领域（从 agent_trace 提取）
        pool_summary += f"\n\n## 历史发布表现参考（最近 {total} 篇已发布文章）\n"
        pool_summary += f"- 整体平均阅读：{avg_reads:.0f} 次\n"
        # 如果有高表现文章，给出提示
        best_rows = sorted(perf_rows, key=lambda r: r[1] or 0, reverse=True)[:3]
        pool_summary += "- 近期高表现文章特征：阅读量靠前的文章题材——标题含具体数字或反常识表述的健康/生活类内容表现更好\n"
        for br in best_rows:
            if br[1] and br[1] > 0:
                pool_summary += f"  · {br[1]:.0f} 阅读（已发布）\n"

    asset_summary = await _summarize_assets(db)
    decision = await editor_in_chief.decide(pool_summary, asset_summary, domain=domain)

    # Step 2: 正文写作
    topic = decision.get("selected_topic", "今日热点")
    angle = decision.get("angle", "深度分析")
    title_candidates = decision.get("suggested_title_candidates", [topic])
    source_refs = decision.get("source_references", [])
    source_materials = _build_source_materials(pool_items)
    claim_plan = _normalize_claim_plan(decision, source_materials)
    decision["claim_plan"] = claim_plan
    written = await writer.write(
        topic,
        angle,
        title_candidates,
        asset_summary,
        source_materials,
        domain=domain,
        claim_plan=claim_plan,
    )
    written["title"] = _normalize_generated_title(written, decision)

    # Step 3: 文稿安全与事实边界审核。先审 Markdown，修稿后必须复审通过。
    written, review_trace, review_passed = await _review_and_repair_written(written, reviewer, source_materials=source_materials)
    if not review_passed:
        prepared_failed = publisher_agent.prepare(
            title=written.get("title", topic),
            body=written.get("body", ""),
            summary=written.get("summary", ""),
        )
        failed_article = Article(
            id=str(uuid.uuid4()),
            title=prepared_failed["title"],
            body=prepared_failed["body"],
            summary=prepared_failed["summary"],
            status=ArticleStatus.FAILED,
            source_content_ids=[item.id for item in pool_items],
            agent_trace=[decision, written, {}, review_trace],
        )
        db.add(failed_article)
        await db.commit()
        second_review = review_trace.get("second_review") or review_trace.get("review") or {}
        return {
            "error": "文稿审核未通过，已保存为失败记录，未生成插图或草稿",
            "id": failed_article.id,
            "title": failed_article.title,
            "summary": failed_article.summary,
            "status": article_status_public_value(failed_article.status),
            "issues": second_review.get("issues", []),
            "decision": decision,
        }

    # Step 4: 发布准备
    prepared = publisher_agent.prepare(
        title=written.get("title", topic),
        body=written.get("body", ""),
        summary=written.get("summary", ""),
    )

    # Step 5: 生成插图 prompt（封面 + 内文，AI 绘图提示词）
    illus_prompts = await illustration_editor.edit(
        title=prepared["title"],
        body=written.get("body", ""),
        summary=prepared["summary"],
    )

    # 插图 prompt 存入 trace[2]
    illus_trace = illus_prompts

    # 既然插画已成功生成，清洗 review_trace 里的“缺少插画 prompt”过期警告
    if review_trace and isinstance(review_trace, dict):
        for k in ["review", "second_review"]:
            if k in review_trace and isinstance(review_trace[k], dict):
                issues = review_trace[k].get("issues", [])
                if isinstance(issues, list):
                    # 过滤掉类型为 "illustration" 的警告条目
                    cleaned_issues = [iss for iss in issues if iss.get("type") != "illustration"]
                    review_trace[k]["issues"] = cleaned_issues

    # Step 6: 保存文章到数据库
    article = Article(
        id=str(uuid.uuid4()),
        title=prepared["title"],
        body=prepared["body"],
        summary=prepared["summary"],
        status=ArticleStatus.DRAFT,
        source_content_ids=[item.id for item in pool_items],
        agent_trace=[decision, written, illus_trace, review_trace],
    )
    db.add(article)

    # Step 7: 标记本次参与生成的素材为「已用」；避免依赖模型返回的引用标题做脆弱匹配。
    now = datetime.utcnow()
    for item in pool_items:
        item.used_at = now
    await db.commit()

    return {
        "id": article.id,
        "title": article.title,
        "summary": article.summary,
        "word_count": prepared["word_count"],
        "status": article.status,
        "decision": decision,
    }


@router.post("/{article_id}/regenerate")
async def regenerate_failed_article(article_id: str, db: AsyncSession = Depends(get_db)):
    """基于失败记录重新生成一篇新草稿/失败记录，不覆盖原失败记录。"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    if article_status_public_value(article.status) != ArticleStatus.FAILED.value:
        raise HTTPException(400, "只有失败文章可以重新生成")

    item_ids = await _infer_retry_content_ids(article, db)
    if not item_ids:
        raise HTTPException(400, "无法从失败记录中恢复原始素材，请从内容池重新选择素材生成")

    first_item = await db.get(ContentItem, item_ids[0])
    domain = first_item.domain if first_item else "tech"
    params = GenerateParams(domain=domain, item_ids=item_ids, focus=_article_retry_focus(article))
    result = await generate_article(params, db)
    if isinstance(result, dict):
        result["retried_from_id"] = article.id
        result["retry_item_ids"] = item_ids
    return result


@router.post("/{article_id}/publish")
async def publish_article(article_id: str, db: AsyncSession = Depends(get_db)):
    """发布文章到公众号"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    result = await wechat.publish_article(
        title=article.title,
        body=article.body,
        summary=article.summary,
    )

    if result.get("success"):
        article.status = ArticleStatus.PUBLISHED
        article.publish_platform_id = result.get("media_id", "")
        await db.commit()

    return {"article_id": article_id, "publish_result": result}


@router.post("/{article_id}/illustrations")
async def generate_illustrations(article_id: str, db: AsyncSession = Depends(get_db)):
    """为文章生成封面图 + 内文插图 prompt，手动触发"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    prompts = await illustration_editor.edit(
        title=article.title,
        body=article.body,
        summary=article.summary,
    )

    # 保存到 agent_trace[2]
    trace = list(article.agent_trace or [])
    while len(trace) < 3:
        trace.append({})
    trace[2] = prompts
    article.agent_trace = trace
    await db.commit()

    return prompts


@router.post("/{article_id}/review")
async def review_article(article_id: str, db: AsyncSession = Depends(get_db)):
    """文稿校验：敏感词/事实/合规检查 + 自动修正 + 重新生成插图"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    # Step 1: 校验
    illus_trace = (article.agent_trace or [])[2] if len((article.agent_trace or [])) > 2 else {}
    result = await reviewer.check(
        title=article.title,
        body=article.body,
        summary=article.summary,
        cover_prompt=illus_trace.get("cover", {}).get("prompt"),
        illustrations=illus_trace.get("illustrations", []),
    )

    response = {
        "passed": result["passed"],
        "issues": result["issues"],
        "overall_comment": result["overall_comment"],
        "keyword_hits": result["keyword_hits"],
    }

    # Step 2: 如果有 blocker 问题，自动修正
    if not result["passed"]:
        fixed = await reviewer.fix(
            title=article.title,
            body=article.body,
            summary=article.summary,
            issues=result["issues"],
        )

        # 更新文章
        article.title = fixed["title"]
        article.body = fixed["body"]
        article.summary = fixed["summary"]

        # 保存校验记录到 agent_trace[3]
        trace = list(article.agent_trace or [])
        while len(trace) < 4:
            trace.append({})
        trace[3] = {
            "review": result,
            "fixed": fixed,
        }
        article.agent_trace = trace
        await db.commit()

        # Step 3: 重新生成插图 prompt（如果已有）
        if trace[2] and trace[2].get("cover"):
            try:
                new_prompts = await illustration_editor.edit(
                    title=fixed["title"],
                    body=fixed["body"],
                    summary=fixed["summary"],
                )
                trace[2] = new_prompts
                article.agent_trace = trace
                await db.commit()
                response["illustrations_regen"] = True
            except Exception:
                response["illustrations_regen"] = False
        else:
            response["illustrations_regen"] = None

        response["fixed"] = {
            "title": fixed["title"],
            "summary": fixed["summary"],
            "changes": fixed.get("changes", ""),
        }
    else:
        # 仅保存校验记录
        trace = list(article.agent_trace or [])
        while len(trace) < 4:
            trace.append({})
        trace[3] = {"review": result}
        article.agent_trace = trace
        await db.commit()

    return response


@router.post("/{article_id}/submit-review")
async def submit_article_review(article_id: str, db: AsyncSession = Depends(get_db)):
    """将草稿送入人工审核队列。"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    if article_status_public_value(article.status) == ArticleStatus.FAILED.value:
        raise HTTPException(400, "失败文章不能送审")
    article.status = ArticleStatus.REVIEWING
    await db.commit()
    return {"article_id": article_id, "status": ArticleStatus.REVIEWING.value}


@router.post("/{article_id}/approve")
async def approve_article(article_id: str, db: AsyncSession = Depends(get_db)):
    """人工审核通过，进入待发布状态。"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    if article_status_public_value(article.status) == ArticleStatus.FAILED.value:
        raise HTTPException(400, "失败文章不能审核通过")
    article.status = ArticleStatus.APPROVED
    await db.commit()
    return {"article_id": article_id, "status": ArticleStatus.APPROVED.value}


@router.post("/{article_id}/return-to-draft")
async def return_article_to_draft(article_id: str, db: AsyncSession = Depends(get_db)):
    """人工退回修改。"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    if article_status_public_value(article.status) == ArticleStatus.PUBLISHED.value:
        raise HTTPException(400, "已发布文章不能退回草稿")
    article.status = ArticleStatus.DRAFT
    await db.commit()
    return {"article_id": article_id, "status": ArticleStatus.DRAFT.value}


@router.get("")
async def list_articles(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Article).order_by(Article.created_at.desc())
    if status:
        try:
            query = query.where(Article.status == article_status_from_public_value(status))
        except ValueError:
            raise HTTPException(400, f"未知文章状态：{status}")

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # 物理分页
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    return {
        "items": [{
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "status": article_status_public_value(r.status),
            "word_count": len(r.body) if r.body else 0,
            "read_count": r.read_count,
            "like_count": r.like_count,
            "created_at": r.created_at.isoformat(),
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "scheduled_publish_at": r.scheduled_publish_at.isoformat() if r.scheduled_publish_at else None,
            "has_illustrations": bool(r.agent_trace and len(r.agent_trace) > 2 and r.agent_trace[2] and r.agent_trace[2].get("cover")),
            "has_review": bool(r.agent_trace and len(r.agent_trace) > 3 and r.agent_trace[3] and r.agent_trace[3].get("review")),
        } for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
async def get_article_stats(db: AsyncSession = Depends(get_db)):
    """文章数据聚合统计（用于前端数据看板）"""
    # 1. 获取所有文章
    all_articles = (await db.execute(
        select(Article).order_by(Article.created_at.desc())
    )).scalars().all()

    if not all_articles:
        return {
            "overview": {"total_articles": 0, "total_reads": 0, "total_shares": 0, "total_favorites": 0},
            "by_domain": [],
            "by_source": [],
            "by_day": [],
            "top_articles": [],
        }

    total_reads = sum(a.read_count or 0 for a in all_articles)
    total_shares = sum(a.share_count or 0 for a in all_articles)
    total_favorites = sum(a.favorite_count or 0 for a in all_articles)
    total_articles = len([a for a in all_articles if article_status_public_value(a.status) == ArticleStatus.PUBLISHED.value])

    # 最佳文章
    best = max(all_articles, key=lambda a: a.read_count or 0)

    # 2. 按领域聚合（从 agent_trace 中提取 domain 信息）
    domain_stats: dict[str, dict] = {}
    for a in all_articles:
        trace = a.agent_trace or []
        domain = ""
        if trace and isinstance(trace[0], dict):
            domain = trace[0].get("domain", "") or ""
        if not domain:
            domain = "未分类"
        if domain not in domain_stats:
            domain_stats[domain] = {"count": 0, "reads": 0, "shares": 0}
        if article_status_public_value(a.status) == ArticleStatus.PUBLISHED.value:
            domain_stats[domain]["count"] += 1
        domain_stats[domain]["reads"] += a.read_count or 0
        domain_stats[domain]["shares"] += a.share_count or 0

    by_domain = [
        {
            "domain": d,
            "article_count": s["count"],
            "total_reads": s["reads"],
            "total_shares": s["shares"],
            "avg_reads": round(s["reads"] / s["count"], 1) if s["count"] > 0 else 0,
        }
        for d, s in sorted(domain_stats.items(), key=lambda x: x[1]["reads"], reverse=True)
    ]

    # 2b. 按素材来源复盘：一篇文章可能引用多个来源，各来源各记一次贡献。
    source_stats: dict[str, dict] = {}
    published_for_source = [
        a for a in all_articles
        if article_status_public_value(a.status) == ArticleStatus.PUBLISHED.value and a.source_content_ids
    ]
    for article in published_for_source:
        source_ids = article.source_content_ids if isinstance(article.source_content_ids, list) else []
        for item_id in source_ids:
            item = await db.get(ContentItem, item_id)
            if not item:
                continue
            source = item.source or "unknown"
            if source not in source_stats:
                source_stats[source] = {"articles": set(), "materials": 0, "reads": 0, "shares": 0, "favorites": 0}
            source_stats[source]["articles"].add(article.id)
            source_stats[source]["materials"] += 1
            source_stats[source]["reads"] += article.read_count or 0
            source_stats[source]["shares"] += article.share_count or 0
            source_stats[source]["favorites"] += article.favorite_count or 0

    by_source = [
        {
            "source": source,
            "article_count": len(data["articles"]),
            "material_refs": data["materials"],
            "total_reads": data["reads"],
            "total_shares": data["shares"],
            "total_favorites": data["favorites"],
            "avg_reads": round(data["reads"] / len(data["articles"]), 1) if data["articles"] else 0,
        }
        for source, data in sorted(source_stats.items(), key=lambda x: x[1]["reads"], reverse=True)
    ]

    # 3. 按日阅读趋势（从数据库统计）
    by_day_raw = (await db.execute(
        text("""
            SELECT DATE(created_at) as day, SUM(read_count) as reads
            FROM articles
            WHERE status::text = :published_status
            GROUP BY day
            ORDER BY day ASC
        """),
        {"published_status": article_status_db_label(ArticleStatus.PUBLISHED)},
    )).all()
    by_day = [{"date": str(r[0]), "reads": r[1] or 0} for r in by_day_raw]

    # 4. 文章排行
    published = [a for a in all_articles if article_status_public_value(a.status) == ArticleStatus.PUBLISHED.value]
    published.sort(key=lambda a: a.read_count or 0, reverse=True)
    top_articles = [
        {
            "id": a.id,
            "title": a.title,
            "reads": a.read_count or 0,
            "shares": a.share_count or 0,
            "favorites": a.favorite_count or 0,
            "word_count": len(a.body) if a.body else 0,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "published_at": a.published_at.isoformat() if a.published_at else None,
        }
        for a in published[:20]
    ]

    return {
        "overview": {
            "total_articles": total_articles,
            "total_reads": total_reads,
            "total_shares": total_shares,
            "total_favorites": total_favorites,
            "avg_reads": round(total_reads / total_articles, 1) if total_articles > 0 else 0,
            "best_article": {
                "title": best.title,
                "reads": best.read_count or 0,
            } if best else None,
        },
        "by_domain": by_domain,
        "by_source": by_source,
        "by_day": by_day,
        "top_articles": top_articles,
    }


@router.post("/import-stats")
async def import_stats_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传微信后台导出的 .xls 文件，导入文章阅读数据"""
    if not file.filename.endswith('.xls'):
        raise HTTPException(400, "仅支持 .xls 文件格式")

    content = await file.read()
    wb = xlrd.open_workbook(file_contents=content)
    sheet = wb.sheet_by_index(0)

    # 寻找右半部分「数据来源概况」的标题行（col 11 含 '传播渠道' 或 '阅读人数'）
    start_row = None
    for row_idx in range(sheet.nrows):
        for col in range(sheet.ncols):
            val = str(sheet.cell_value(row_idx, col)).strip()
            if '传播渠道' in val:
                start_row = row_idx + 1
                break
        if start_row:
            break

    if start_row is None:
        raise HTTPException(400, "无法识别 Excel 格式，未找到「数据来源概况」区域")

    # 数据来源概况列索引（0-based）：11=传播渠道, 13=内容标题, 14=阅读人数
    CHANNEL_COL = 11
    TITLE_COL = 13
    READS_COL = 14

    updated = 0
    unmatched = []

    for row_idx in range(start_row, sheet.nrows):
        channel = str(sheet.cell_value(row_idx, CHANNEL_COL)).strip()
        title = str(sheet.cell_value(row_idx, TITLE_COL)).strip()
        reads_raw = sheet.cell_value(row_idx, READS_COL)

        if channel != '全部' or not title or not reads_raw:
            continue

        try:
            reads = int(float(reads_raw))
        except (ValueError, TypeError):
            continue

        # 按标题模糊匹配：微信导出的标题是截断的，用 startswith 匹配
        clean_title = title.strip().strip('"').strip('\'')
        result = await db.execute(
            select(Article).where(Article.title.startswith(clean_title))
        )
        article = result.scalar_one_or_none()

        if article:
            article.read_count = reads
            updated += 1
        else:
            unmatched.append(title[:30])

    await db.commit()

    return {
        "success": True,
        "message": f"导入完成，更新 {updated} 篇文章",
        "updated": updated,
        "unmatched": unmatched,
    }


@router.post("/sync-stats")
async def trigger_sync_stats(
    days: int = Query(7, ge=1, le=30, description="回溯天数"),
):
    """手动触发微信数据同步"""
    from app.tasks import sync_wechat_stats
    task = sync_wechat_stats.delay(days=days)
    return {"message": f"数据同步任务已提交，回溯 {days} 天", "task_id": task.id}


@router.get("/{article_id}")
async def get_article(article_id: str, db: AsyncSession = Depends(get_db)):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    return article


@router.post("/batch-delete")
async def batch_delete_articles(body: ArticleBatchDeleteRequest, db: AsyncSession = Depends(get_db)):
    """批量删除文章。"""
    try:
        ids = _normalize_batch_delete_ids(body.ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    result = await db.execute(select(Article).where(Article.id.in_(ids)))
    articles = result.scalars().all()
    deleted_ids = []
    for article in articles:
        await db.delete(article)
        deleted_ids.append(article.id)
    await db.commit()
    return {
        "success": True,
        "deleted_ids": deleted_ids,
        "deleted": len(deleted_ids),
        "total_requested": len(ids),
    }


@router.delete("/{article_id}")
async def delete_article(article_id: str, db: AsyncSession = Depends(get_db)):
    """删除文章"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")
    await db.delete(article)
    await db.commit()
    return {"success": True}


def _build_markdown_export(article: Article) -> str:
    """生成包含文章、插图 prompt、审核建议的完整 Markdown"""
    lines = []

    # ── 标题 ──
    lines.append(f"# {article.title}")
    lines.append("")

    # ── 元信息 ──
    status_map = {"draft": "草稿", "reviewing": "审核中", "approved": "已通过", "published": "已发布", "failed": "失败"}
    public_status = article_status_public_value(article.status)
    lines.append(f"> 状态：{status_map.get(public_status, public_status)}")
    lines.append(f"> 创建时间：{article.created_at.strftime('%Y-%m-%d %H:%M') if article.created_at else '-'}")
    if article.published_at:
        lines.append(f"> 发布时间：{article.published_at.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 字数：{len(article.body)}")
    lines.append("")

    # ── 摘要 ──
    if article.summary:
        lines.append("## 摘要")
        lines.append("")
        lines.append(article.summary)
        lines.append("")

    # ── 正文 ──
    lines.append("## 正文")
    lines.append("")
    lines.append(article.body)
    lines.append("")

    # ── 插图 prompt 与配图 ──
    trace = article.agent_trace or []
    if len(trace) > 2 and trace[2] and trace[2].get("cover"):
        illus = trace[2]
        lines.append("---")
        lines.append("## 🎨 插图 Prompt 与实际配图")
        lines.append("")

        lines.append("### 封面图")
        lines.append("")
        if illus["cover"].get("image_url"):
            cover_filename = os.path.basename(illus["cover"]["image_url"])
            lines.append(f"![封面配图](images/{cover_filename})")
            lines.append("")
        lines.append(f"**提示词**：{illus['cover'].get('copy_prompt') or illus['cover'].get('prompt', '')}")
        lines.append("")

        for i, ill in enumerate(illus.get("illustrations", []), 1):
            lines.append(f"### 内文插图 {i}：{ill.get('section_title', '')}")
            lines.append("")
            if ill.get("image_url"):
                ill_filename = os.path.basename(ill["image_url"])
                lines.append(f"![内文配图 {i}](images/{ill_filename})")
                lines.append("")
            lines.append(f"**提示词**：{ill.get('copy_prompt') or ill.get('prompt', '')}")
            lines.append("")

    # ── 审核建议 ──
    if len(trace) > 3 and trace[3] and trace[3].get("review"):
        review = trace[3]["review"]
        lines.append("---")
        lines.append("## 🔍 文稿校验")
        lines.append("")

        passed = review.get("passed", False)
        lines.append(f"> **结论**：{'✅ 通过' if passed else '❌ 存在问题'}")
        lines.append("")

        if review.get("overall_comment"):
            lines.append("### 总体评价")
            lines.append("")
            lines.append(review["overall_comment"])
            lines.append("")

        issues = review.get("issues", [])
        if issues:
            lines.append("### 问题详情")
            lines.append("")
            severity_map = {"blocker": "🔴 阻塞", "warning": "🟡 警告", "suggestion": "🔵 建议"}
            for i, issue in enumerate(issues, 1):
                sev = severity_map.get(issue.get("severity", ""), issue.get("severity", ""))
                lines.append(f"{i}. **[{sev}] {issue.get('type', '未知')}**")
                lines.append(f"   - 位置：{issue.get('location', '未知')}")
                lines.append(f"   - 说明：{issue.get('detail', '')}")
                if issue.get("suggestion"):
                    lines.append(f"   - 建议：{issue['suggestion']}")
                lines.append("")

        keyword_hits = review.get("keyword_hits", [])
        # keyword_hits 可能是 int（数量）或 list，统一从 issues 中提取敏感词详情
        if isinstance(keyword_hits, int) and keyword_hits > 0:
            sensitive_issues = [i for i in issues if i.get("type") == "sensitive_content"]
            if sensitive_issues:
                lines.append("### 敏感词命中")
                lines.append("")
                for hit in sensitive_issues:
                    word = hit.get("location", "")
                    ctx = hit.get("detail", "")
                    lines.append(f"- 「{word}」— {ctx}")
                lines.append("")

        # 自动修正记录
        fixed = trace[3].get("fixed")
        if fixed:
            lines.append("### 自动修正")
            lines.append("")
            if fixed.get("changes"):
                lines.append(fixed["changes"])
                lines.append("")

    return "\n".join(lines)


@router.post("/{article_id}/illustrations/upload")
async def upload_article_illustration_association(
    article_id: str,
    params: IllustrationUploadParams,
    db: AsyncSession = Depends(get_db),
):
    """保存用户上传的 Midjourney 配图关联关系到文章的 agent_trace 中"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    trace = list(article.agent_trace or [])
    while len(trace) < 3:
        trace.append({})

    if not isinstance(trace[2], dict):
        trace[2] = {}

    illus = dict(trace[2])

    if params.type == "cover":
        if "cover" not in illus or not isinstance(illus["cover"], dict):
            illus["cover"] = {}
        illus["cover"] = dict(illus["cover"])
        illus["cover"]["image_url"] = params.image_url
    else:
        try:
            idx = int(params.type)
            if "illustrations" in illus and isinstance(illus["illustrations"], list):
                if 0 <= idx < len(illus["illustrations"]):
                    # 深度复制更新字典
                    illus["illustrations"] = list(illus["illustrations"])
                    target = dict(illus["illustrations"][idx])
                    target["image_url"] = params.image_url
                    illus["illustrations"][idx] = target
        except (ValueError, IndexError):
            raise HTTPException(400, f"无效的插图标识或索引：{params.type}")

    trace[2] = illus
    article.agent_trace = trace

    # 强行标记变更以确保 SQLAlchemy 能够识别变更
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(article, "agent_trace")

    await db.commit()
    return {"success": True, "image_url": params.image_url}





@router.get("/{article_id}/export")
async def export_article_markdown(article_id: str, db: AsyncSession = Depends(get_db)):
    """导出文章为 Markdown（若存在已上传插图配图，则自动打包为 ZIP 压缩包下载）"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    md_content = _build_markdown_export(article)

    import re
    import io
    import os
    from urllib.parse import quote
    import zipfile
    from fastapi.responses import StreamingResponse

    # 1. 扫描文章正文中的本地相对路径图片
    image_names = set(re.findall(r'/static/images/([a-zA-Z0-9\.-]+\.(?:png|jpg|jpeg|gif|webp))', md_content, re.IGNORECASE))

    # 2. 扫描 agent_trace 中显式挂载的配图
    trace = article.agent_trace or []
    if len(trace) > 2 and trace[2] and isinstance(trace[2], dict):
        illus = trace[2]
        if illus.get("cover") and illus["cover"].get("image_url"):
            image_names.add(os.path.basename(illus["cover"]["image_url"]))
        for ill in illus.get("illustrations", []):
            if ill.get("image_url"):
                image_names.add(os.path.basename(ill["image_url"]))

    # 如果没有任何关联图片，直接返回纯 Markdown 以保持向下兼容
    if not image_names:
        filename = f"{article.title.replace('/', '_').replace(' ', '_')[:50]}.md"
        return Response(
            content=md_content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}",
            },
        )

    # 包含图片，开始打包 ZIP 内存字节流
    static_images_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        "static", 
        "images"
    )

    # 替换 Markdown 正文里图片引用为解压后的本地相对路径目录 images/
    md_content_fixed = re.sub(r'/static/images/', 'images/', md_content)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # 写入 README.md
        article_filename = f"{article.title.replace('/', '_').replace(' ', '_')[:50]}.md"
        zip_file.writestr(article_filename, md_content_fixed)

        # 写入图片文件
        for img_name in image_names:
            local_path = os.path.join(static_images_dir, img_name)
            if os.path.exists(local_path):
                zip_file.write(local_path, f"images/{img_name}")

    zip_buffer.seek(0)
    zip_filename = f"{article.title.replace('/', '_').replace(' ', '_')[:50]}.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(zip_filename)}",
        }
    )


class ArticleUpdateParams(BaseModel):
    title: str | None = None
    body: str | None = None
    summary: str | None = None
    status: str | None = None


def _strip_workflow_artifacts_from_body(body: str) -> str:
    """Remove image-generation workflow prompt blocks from editable article body."""
    if not body:
        return body
    patterns = [
        r"\n?\s*>\s*\*\*\[待生成封面图\s*Prompt\]\*\*\s*[：:].*?(?=\n\s*\n|\Z)",
        r"\n?\s*>\s*\*\*\[待生成插图\s*\d+\s*Prompt\]\*\*\s*[：:].*?(?=\n\s*\n|\Z)",
        r"\n?\s*>\s*\*\*\[[^\]]*(?:封面图|插图|配图|图片)[^\]]*Prompt[^\]]*\]\*\*\s*[：:].*?(?=\n\s*\n|\Z)",
    ]
    cleaned = body
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


@router.put("/{article_id}")
async def update_article(
    article_id: str,
    params: ArticleUpdateParams,
    db: AsyncSession = Depends(get_db),
):
    """人工微调修改已生成的文章标题和内容（智能支持 Markdown 转换为微信 HTML 排版）"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    if params.title is not None:
        article.title = params.title
    if params.summary is not None:
        article.summary = params.summary
    if params.body is not None:
        clean_body = _strip_workflow_artifacts_from_body(params.body)
        # 智能兼容：如果是 Markdown 文本，自动在后端转换为微信 HTML 格式并持久化
        if "<p" not in clean_body and "<div" not in clean_body:
            prepared = publisher_agent.prepare(
                title=params.title or article.title,
                body=clean_body,
                summary=params.summary or article.summary,
            )
            article.body = prepared["body"]
            
            # 同时将最新的干净 Markdown 同步维护进 trace
            trace = list(article.agent_trace or [])
            while len(trace) < 2:
                trace.append({})
            
            new_trace = []
            for item in trace:
                if isinstance(item, dict):
                    new_trace.append(dict(item))
                else:
                    new_trace.append(item)
            
            new_trace[1]["body"] = clean_body
            article.agent_trace = new_trace
            
            # 强行标记变更以确保 SQLAlchemy 必将 json 字段打包进 UPDATE 执行
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(article, "agent_trace")
        else:
            article.body = clean_body

    if params.status is not None:
        try:
            article.status = article_status_from_public_value(params.status)
        except ValueError:
            raise HTTPException(400, f"未知文章状态：{params.status}")

    await db.commit()
    return {"article_id": article_id, "success": True}


@router.get("/{article_id}/suggestions")
async def get_article_suggestions(
    article_id: str,
    user_instruction: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """调取大模型智能输出 3 条一键采纳的个性化文稿润色与修改建议"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    # 提取最新的二审校验异常问题（如有）
    issues = []
    trace = article.agent_trace or []
    if len(trace) > 3 and isinstance(trace[3], dict):
        review_data = trace[3].get("second_review") or trace[3].get("review") or {}
        if isinstance(review_data, dict):
            issues = review_data.get("issues", [])

    issues_text = ""
    if issues:
        issues_text = "\n".join([f"- [{iss.get('severity', '警告')}] {iss.get('detail', '')}" for iss in issues if iss.get('detail')])

    if issues_text:
        instruction = f"""你必须【首要且针对性地】围绕以下这篇文稿在校验中被检出的几项具体问题，给出 3 条可一键采纳的精准修复与润色建议，指导或帮助用户快速修正它们：
        
        {issues_text}
        
        建议生成具体要求：
        1. 如果检出了敏感违规词（例如「特效药」），你必须在 suggestions 列表中给出一个替换建议（type 为 "body_replace"），original_text 设为正文里对应的那个敏感词（请确保字面完全一致，区分大小写），suggested_text 设为更稳妥、安全且克制的替换表述。
        2. 如果检出了正文截断、缺少内文插图 prompt、开头场景不规范等，请给出补齐、插入或重写的建议。
        3. 每个建议依然必须严格符合 type、target_label、description、original_text、suggested_text 结构，以支持前端一键采纳应用。
        """
    else:
        instruction = """你必须提供 3 条具体的、可「一键采纳」的高质量局部优化与润色建议，分别覆盖以下 3 个核心模块：
        1. 标题润色（类型 type 为 "title"）：
           针对文章标题给出优化选项。建议被修改的原文 original_text 为当前文章的旧标题，suggested_text 为新标题。
        2. 摘要润色（类型 type 为 "summary"）：
           针对文章的简短摘要给出更具吸引力的改写。建议被修改的原文 original_text 为当前文章的旧摘要，suggested_text 为新摘要。
        3. 正文细节/金句优化（类型 type 为 "body_replace"）：
           针对正文开头场景、局部段落或者结尾温和金句进行改写。请完全从下方给出的正文中精准截取一段原文 original_text，suggested_text 为优化后的那段文字。
        """

    extra_instruction = ""
    if user_instruction:
        extra_instruction = f"""
        
        ⚠️⚠️⚠️【极其重要：用户提出了最新的润色重写指令，你必须 100% 严格遵从执行】：
        "{user_instruction}"
        你必须完全基于用户这个重写指令调整你的润色输出（例如：如果用户要求不要出现某些词、换某些词，或者文风要求等，你必须在生成的 suggestions 的 suggested_text 里落实！）
        """

    prompt = f"""你是一个顶级自媒体主笔。请针对以下文章内容，给出 3 条非常具体的、可「一键采纳」的高质量局部优化与润色建议。
    
    {instruction}
    {extra_instruction}
    
    请严格以 JSON 格式输出建议列表，每一条建议格式如下：
    {{
      "type": "title"、"summary" 或 "body_replace",
      "target_label": "优化的位置说明，例如：‘清理违规敏感词’、‘补齐中途截断正文’ 或 ‘文章标题润色优化’",
      "description": "为什么要提出这个修改（简洁的修改原因，一两句话）",
      "original_text": "建议被替换的原文内容（请严格与下方正文中的文字完全一致）",
      "suggested_text": "建议替换成的优化后新内容（新文本）"
    }}
    
    输出格式为 JSON：
    {{
      "suggestions": [
        {{ ... }},
        {{ ... }},
        {{ ... }}
      ]
    }}
    """

    body_md = ""
    if len(trace) > 1 and isinstance(trace[1], dict):
        body_md = trace[1].get("body", "")
    if not body_md:
        body_md = article.body # 兜底

    user_content = f"文章标题：{article.title}\n文章摘要：{article.summary}\n文章正文：\n{body_md[:3000]}"

    try:
        raw = await llm_chat(prompt, user_content, temperature=0.6)
        res = parse_llm_json(raw)
        return res
    except Exception as e:
        # 将异常堆栈打印在后台终端，极度方便开发调试
        import logging
        logging.exception(f"AI suggestions generation encountered an error: {e}")
        
        # 智能自适应动态兜底：基于文稿当前的实际标题进行提取
        raw_title = article.title or ""
        clean_title = raw_title if raw_title != "未解析" else "日常健康习惯"
        
        # 截取正文前部作为替换原文示例
        snippet_len = min(len(body_md), 120)
        snippet_body = body_md[:snippet_len] if body_md else "正文内容..."
        
        return {
            "suggestions": [
                {
                    "type": "title",
                    "target_label": "文章标题润色优化",
                    "description": "优化当前的标题内容。",
                    "original_text": article.title,
                    "suggested_text": clean_title
                },
                {
                    "type": "summary",
                    "target_label": "文章摘要吸引力升级",
                    "description": "优化摘要描述。",
                    "original_text": article.summary,
                    "suggested_text": article.summary if article.summary else "请微调输入您的文章摘要..."
                },
                {
                    "type": "body_replace",
                    "target_label": "正文开头场景优化",
                    "description": "优化正文开头文字。",
                    "original_text": snippet_body,
                    "suggested_text": snippet_body
                }
            ],
            "debug_error": str(e)
        }


@router.post("/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """人工/AI生图一键剪贴板上传图片，保存在本地静态目录中并返回相对路径"""
    if not file.content_type.startswith("image/"):
        raise HTTPException(400, "只允许上传图片文件")
        
    import os
    import uuid
    
    # 静态目录：G:\AI\AIViralContentMatrixSystem\backend\app\static\images
    static_images_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
        "static", 
        "images"
    )
    os.makedirs(static_images_dir, exist_ok=True)
    
    # 随机生成独一无二的文件名
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    target_path = os.path.join(static_images_dir, unique_filename)
    
    # 保存文件
    try:
        content = await file.read()
        with open(target_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, f"图片保存失败: {str(e)}")
        
    return {
        "url": f"/static/images/{unique_filename}",
        "success": True
    }
