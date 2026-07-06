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

router = APIRouter(prefix="/api/articles", tags=["articles"])
editor_in_chief = EditorInChiefAgent()
writer = WriterAgent()
publisher_agent = PublisherAgent()
illustration_editor = IllustrationEditorAgent()
reviewer = ReviewerAgent()
wechat = WeChatPublisher()


async def _summarize_content_pool(db: AsyncSession, domain: str | None = None) -> tuple[str, list[ContentItem]]:
    """从 Content Pool 中生成摘要用于总编决策，排除已使用过的内容"""
    query = select(ContentItem).where(ContentItem.used_at.is_(None)).order_by(ContentItem.collected_at.desc())
    if domain:
        query = query.where(ContentItem.domain == domain)
    query = query.limit(30)
    rows = (await db.execute(query)).scalars().all()
    if not rows:
        return "暂无采集数据", []
    summaries = []
    for r in rows:
        summaries.append(f"- [{r.source}] {r.title} (来源: {r.source_name}, 领域: {r.domain})")
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


@router.post("/generate")
async def generate_article(
    domain: str = "tech",
    db: AsyncSession = Depends(get_db),
):
    """全自动生成一篇文章：总编 -> 正文 -> 发布"""
    # Step 1: 总编选题
    pool_summary, pool_items = await _summarize_content_pool(db, domain=domain)
    if not pool_items:
        return {"error": "内容池暂无可用素材，请先采集内容", "id": None}

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
    db: AsyncSession = Depends(get_db),
):
    query = select(Article).order_by(Article.created_at.desc())
    if status:
        try:
            query = query.where(Article.status == article_status_from_public_value(status))
        except ValueError:
            raise HTTPException(400, f"未知文章状态：{status}")
    rows = (await db.execute(query)).scalars().all()
    return {
        "items": [{
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "status": article_status_public_value(r.status),
            "word_count": len(r.body),
            "read_count": r.read_count,
            "like_count": r.like_count,
            "created_at": r.created_at.isoformat(),
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "has_illustrations": bool(r.agent_trace and len(r.agent_trace) > 2 and r.agent_trace[2] and r.agent_trace[2].get("cover")),
            "has_review": bool(r.agent_trace and len(r.agent_trace) > 3 and r.agent_trace[3] and r.agent_trace[3].get("review")),
        } for r in rows],
        "total": len(rows),
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
