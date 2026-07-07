"""文章生成 + 发布 API"""

import io
import json
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
from app.llm import llm_chat, parse_llm_json

router = APIRouter(prefix="/api/articles", tags=["articles"])
editor_in_chief = EditorInChiefAgent()
writer = WriterAgent()
publisher_agent = PublisherAgent()
illustration_editor = IllustrationEditorAgent()
reviewer = ReviewerAgent()
wechat = WeChatPublisher()


async def _summarize_content_pool(
    db: AsyncSession,
    domain: str | None = None,
    item_ids: list[str] | None = None
) -> tuple[str, list[ContentItem]]:
    """从 Content Pool 中生成摘要用于总编决策，排除已使用过的内容（若指定了特定的 item_ids 则直接使用它们作为数据源）"""
    if item_ids:
        query = select(ContentItem).where(ContentItem.id.in_(item_ids))
    else:
        query = select(ContentItem).where(ContentItem.used_at.is_(None)).order_by(ContentItem.collected_at.desc())
        if domain:
            query = query.where(ContentItem.domain == domain)
        query = query.limit(30)
        
    rows = (await db.execute(query)).scalars().all()
    if not rows:
        return "暂无采集数据", []
    summaries = []
    for r in rows:
        summaries.append(f"- [{r.source}] {r.title} (ID: {r.id}, 来源: {r.source_name}, 领域: {r.domain})")
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
        summaries.append(f"- [{r.category.value}] {r.name} (评分: {r.score})")
    return "\n".join(summaries)


async def _list_recent_article_titles(db: AsyncSession, limit: int = 20) -> list[str]:
    """获取近期文章标题，供总编去重参考"""
    query = select(Article.title).order_by(Article.created_at.desc()).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    return rows


async def _review_and_repair_written(written: dict, review_agent: ReviewerAgent) -> tuple[dict, dict, bool]:
    """Review raw Markdown, repair blockers once, then recheck before article creation."""
    review_result = await review_agent.check(
        title=written.get("title", ""),
        body=written.get("body", ""),
        summary=written.get("summary", ""),
    )
    review_trace = {"review": review_result}
    if review_result["passed"]:
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
    review_trace["fixed"] = fixed

    second_review = await review_agent.check(
        title=repaired.get("title", ""),
        body=repaired.get("body", ""),
        summary=repaired.get("summary", ""),
    )
    review_trace["second_review"] = second_review
    return repaired, review_trace, second_review["passed"]


from pydantic import BaseModel

class GenerateParams(BaseModel):
    domain: str = "tech"
    item_ids: list[str] | None = None
    focus: str | None = None


@router.post("/generate")
async def generate_article(
    params: GenerateParams,
    db: AsyncSession = Depends(get_db),
):
    """根据自定义素材或全自动选题生成一篇文章：总编 -> 正文 -> 审核 -> 发布"""
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
    written = await writer.write(topic, angle, title_candidates, asset_summary, "\n".join(source_refs), domain=domain)

    # Step 3: 文稿安全与事实边界审核。先审 Markdown，修稿后必须复审通过。
    written, review_trace, review_passed = await _review_and_repair_written(written, reviewer)
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

    # Step 6: 保存文章到数据库
    article = Article(
        id=str(uuid.uuid4()),
        title=prepared["title"],
        body=prepared["body"],
        summary=prepared["summary"],
        status=ArticleStatus.DRAFT,
        agent_trace=[decision, written, illus_trace, review_trace],
    )
    db.add(article)

    # Step 7: 标记被引用的素材为「已用」，通过标题匹配 source_references
    if source_refs:
        refs_text = " ".join(source_refs).lower()
        now = datetime.utcnow()
        for item in pool_items:
            if item.title.lower() in refs_text:
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

    # ── 插图 prompt ──
    trace = article.agent_trace or []
    if len(trace) > 2 and trace[2] and trace[2].get("cover"):
        illus = trace[2]
        lines.append("---")
        lines.append("## 🎨 插图 Prompt")
        lines.append("")

        lines.append("### 封面图")
        lines.append("")
        lines.append(illus["cover"].get("copy_prompt") or illus["cover"].get("prompt", ""))
        lines.append("")

        for i, ill in enumerate(illus.get("illustrations", []), 1):
            lines.append(f"### 内文插图 {i}：{ill.get('section_title', '')}")
            lines.append("")
            lines.append(ill.get("copy_prompt") or ill.get("prompt", ""))
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


@router.get("/{article_id}/export")
async def export_article_markdown(article_id: str, db: AsyncSession = Depends(get_db)):
    """导出文章为 Markdown 文件下载"""
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(404, "文章不存在")

    md_content = _build_markdown_export(article)
    filename = f"{article.title.replace('/', '_').replace(' ', '_')[:50]}.md"

    return Response(
        content=md_content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}",
        },
    )


class ArticleUpdateParams(BaseModel):
    title: str | None = None
    body: str | None = None
    summary: str | None = None
    status: str | None = None


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
        # 智能兼容：如果是 Markdown 文本，自动在后端转换为微信 HTML 格式并持久化
        if "<p" not in params.body and "<div" not in params.body:
            prepared = publisher_agent.prepare(
                title=params.title or article.title,
                body=params.body,
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
            
            new_trace[1]["body"] = params.body
            article.agent_trace = new_trace
            
            # 强行标记变更以确保 SQLAlchemy 必将 json 字段打包进 UPDATE 执行
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(article, "agent_trace")
        else:
            article.body = params.body

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
