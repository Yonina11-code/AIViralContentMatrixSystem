import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

function latestReviewTrace(article) {
  const trace = article?.agent_trace?.[3]
  if (!trace) return null
  return trace.second_review || trace.review || null
}

export default function Articles() {
  const [articles, setArticles] = useState([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedArticle, setSelectedArticle] = useState(null)
  const [fullArticle, setFullArticle] = useState(null)
  const [loadingFull, setLoadingFull] = useState(false)
  const [viewingFull, setViewingFull] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [reviewResult, setReviewResult] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 5
  const totalPages = Math.ceil(total / pageSize)

  const fetchArticles = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await api.getArticles({
        status: statusFilter || undefined,
        page,
        page_size: pageSize
      })
      setArticles(data.items)
      setTotal(data.total || 0)
    } catch (e) {
      console.error(e)
      setLoadError(e.message)
    } finally {
      setLoading(false)
    }
  }, [statusFilter, page])

  useEffect(() => { fetchArticles() }, [fetchArticles])

  useEffect(() => {
    setPage(1)
  }, [statusFilter])

  useEffect(() => {
    setReviewResult(null)
    setFullArticle(null)
    setViewingFull(false)
  }, [selectedArticle?.id])

  const handleReview = async () => {
    if (!selectedArticle) return
    setReviewing(true)
    setReviewResult(null)
    try {
      const result = await api.reviewArticle(selectedArticle.id)
      setReviewResult(result)
      // 刷新文章列表并同步选中文章的状态
      const data = await api.getArticles({ status: statusFilter || undefined })
      setArticles(data.items)
      const updated = data.items.find(a => a.id === selectedArticle.id)
      if (updated) setSelectedArticle(updated)
    } catch (e) {
      console.error(e)
    } finally {
      setReviewing(false)
    }
  }

  const handleDelete = async () => {
    if (!selectedArticle) return
    if (!window.confirm(`确定删除文章「${selectedArticle.title}」？此操作不可撤销。`)) return
    setDeleting(true)
    try {
      await api.deleteArticle(selectedArticle.id)
      setSelectedArticle(null)
      fetchArticles()
    } catch (e) {
      console.error(e)
    } finally {
      setDeleting(false)
    }
  }

  const handleExport = async () => {
    if (!selectedArticle) return
    setExporting(true)
    try {
      await api.exportArticle(selectedArticle.id)
    } catch (e) {
      alert('导出失败: ' + e.message)
    } finally {
      setExporting(false)
    }
  }

  const statusColor = (status) => {
    const map = {
      draft: 'text-zinc-400 bg-zinc-50',
      reviewing: 'text-amber-600 bg-amber-50',
      approved: 'text-blue-600 bg-blue-50',
      published: 'text-emerald-600 bg-emerald-50',
      failed: 'text-red-600 bg-red-50',
    }
    return map[status] || 'text-zinc-400 bg-zinc-50'
  }

  const statusLabel = (status) => {
    const map = {
      draft: '草稿',
      reviewing: '审核中',
      approved: '已通过',
      published: '已发布',
      failed: '失败',
    }
    return map[status] || status
  }

  const handleShowFullArticle = async (e) => {
    e.stopPropagation()
    if (!selectedArticle) return
    setLoadingFull(true)
    try {
      const data = await api.getArticle(selectedArticle.id)
      setFullArticle(data.article || data)
      setViewingFull(true)
    } catch (err) {
      console.error(err)
    } finally {
      setLoadingFull(false)
    }
  }

  const handleBack = () => {
    setSelectedArticle(null)
    setFullArticle(null)
    setViewingFull(false)
  }

  const copyPrompt = (prompt) => {
    if (prompt) navigator.clipboard?.writeText(prompt)
  }

  const promptText = (item) => item?.copy_prompt || item?.prompt || ''
  const selectedReview = reviewResult || latestReviewTrace(selectedArticle)

  // 全文阅读视图
  if (viewingFull && fullArticle) {
    return (
      <div>
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-600 mb-6 transition-colors group"
        >
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          返回列表
        </button>

        <article className="surface mx-auto max-w-3xl rounded-[1.5rem] p-6 sm:p-8">
          <h1 className="text-2xl font-bold text-zinc-900 mb-3 leading-snug">{fullArticle.title}</h1>

          {fullArticle.summary && (
            <p className="text-sm text-zinc-500 mb-5 leading-relaxed">{fullArticle.summary}</p>
          )}

          <div className="flex items-center gap-4 mb-8 text-xs text-zinc-400 flex-wrap">
            <span className={`font-medium px-2 py-0.5 rounded-full ${statusColor(fullArticle.status)}`}>
              {statusLabel(fullArticle.status)}
            </span>
            <span>{fullArticle.body?.length || 0} 字</span>
            {fullArticle.platform && (
              <span>目标平台：{fullArticle.platform}</span>
            )}
            {fullArticle.created_at && (
              <span>{new Date(fullArticle.created_at).toLocaleString('zh-CN')}</span>
            )}
          </div>

          {/* 文章正文 — 渲染 HTML 标签 */}
          <div
            className="article-body text-[15px] text-zinc-800 leading-[1.85] space-y-4"
            dangerouslySetInnerHTML={{ __html: fullArticle.body }}
          />

          {/* 插图 Prompts */}
          {(() => {
            const imgs = fullArticle.agent_trace?.[2]
            if (!imgs || !imgs.cover) return null
            return (
              <div className="mt-10 border-t border-zinc-100 pt-6">
                <h3 className="text-sm font-semibold text-zinc-900 mb-4">插图 Prompts</h3>
                <p className="text-xs text-zinc-400 mb-4">复制以下 prompt 到 Midjourney / DALL·E / Stable Diffusion 生成配图</p>
                <div className="mb-4 rounded-2xl border border-blue-100 bg-blue-50/60 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="text-xs font-semibold text-blue-800">封面图 Prompt</span>
                    <button
                      onClick={() => copyPrompt(promptText(imgs.cover))}
                      className="btn-secondary h-8 px-3 text-[11px]"
                    >
                      复制
                    </button>
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-700">{promptText(imgs.cover)}</p>
                </div>
                {imgs.illustrations?.map((ill, i) => (
                  <div key={i} className="mb-3 rounded-2xl border border-zinc-100 bg-zinc-50 p-4">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <span className="text-xs font-semibold text-zinc-700">插图 {i+1}{ill.section_title ? `：${ill.section_title}` : ''}</span>
                      <button
                        onClick={() => copyPrompt(promptText(ill))}
                        className="btn-secondary h-8 px-3 text-[11px]"
                      >
                        复制
                      </button>
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-700">{promptText(ill)}</p>
                  </div>
                ))}
              </div>
            )
          })()}

          {/* 文稿校验结果 */}
          {(() => {
            const review = fullArticle.agent_trace?.[3]
            const r = review?.second_review || review?.review
            if (!r) return null
            return (
              <div className="mt-10 border-t border-zinc-100 pt-6">
                <h3 className="text-sm font-semibold text-zinc-900 mb-4">文稿校验</h3>
                <div className={`p-4 rounded-lg border text-sm ${
                  r.passed
                    ? 'bg-emerald-50 border-emerald-100 text-emerald-700'
                    : 'bg-red-50 border-red-100 text-red-700'
                }`}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="font-semibold">{r.passed ? '校验通过' : '发现问题'}</span>
                    {r.overall_comment && <span className="text-zinc-500">— {r.overall_comment}</span>}
                  </div>
                  {review.fixed && (
                    <div className="text-zinc-600 mb-2">
                      <span className="font-medium">已自动修正：</span>
                      {review.fixed.changes || '内容已优化'}
                    </div>
                  )}
                  {r.issues?.length > 0 && (
                    <details>
                      <summary className="cursor-pointer hover:opacity-70 text-xs">
                        {r.issues.length} 个问题详情
                      </summary>
                      <div className="mt-2 space-y-1.5">
                        {r.issues.map((iss, i) => (
                          <div key={i} className={`p-2 rounded text-xs ${
                            iss.severity === 'blocker' ? 'bg-red-50/50' :
                            iss.severity === 'warning' ? 'bg-amber-50/50' : 'bg-zinc-50'
                          }`}>
                            <div className="flex items-center gap-1 mb-0.5">
                              <span className={`text-[10px] font-medium px-1 rounded ${
                                iss.severity === 'blocker' ? 'bg-red-200 text-red-800' :
                                iss.severity === 'warning' ? 'bg-amber-200 text-amber-800' : 'bg-zinc-200 text-zinc-600'
                              }`}>
                                {iss.severity === 'blocker' ? '违规' : iss.severity === 'warning' ? '警告' : '建议'}
                              </span>
                              <span>{iss.detail}</span>
                            </div>
                            {iss.location && (
                              <p className="text-zinc-400 mt-0.5 truncate">{iss.location}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              </div>
            )
          })()}

          {/* Agent 生成记录（可折叠） */}
          {fullArticle.agent_trace && fullArticle.agent_trace.length > 0 && (
            <details className="mt-10 border-t border-zinc-100 pt-6">
              <summary className="text-xs text-zinc-400 cursor-pointer hover:text-zinc-600 select-none">
                Agent 生成记录
              </summary>
              <pre className="mt-3 p-4 bg-zinc-50 rounded-lg text-xs text-zinc-500 overflow-auto max-h-96 leading-relaxed">
                {JSON.stringify(fullArticle.agent_trace, null, 2)}
              </pre>
            </details>
          )}
        </article>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.8fr)_minmax(320px,0.9fr)]">
      {/* List */}
      <div>
        <div className="surface mb-4 rounded-[1.5rem] p-4">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-blue-600">Publishing Desk</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-950">文章列表</h2>
            <p className="mt-1 text-sm text-zinc-500">挑选草稿、校验风险、生成插图并发布。</p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setSelectedArticle(null) }}
              className="control px-3 text-sm"
            >
              <option value="">全部状态</option>
              <option value="draft">草稿</option>
              <option value="reviewing">审核中</option>
              <option value="approved">已通过</option>
              <option value="published">已发布</option>
              <option value="failed">失败</option>
            </select>
            <button onClick={fetchArticles} disabled={loading} className="btn-secondary h-10 px-4 text-sm disabled:opacity-40">
              {loading ? '刷新中...' : '刷新'}
            </button>
          </div>
        </div>
        </div>

        {loadError ? (
          <div className="rounded-[1.5rem] border border-red-100 bg-red-50 px-5 py-4">
            <p className="text-sm font-semibold text-red-700">文章列表加载失败</p>
            <p className="mt-1 break-words text-xs text-red-600">{loadError}</p>
            <button onClick={fetchArticles} className="btn-secondary mt-4 h-9 px-4 text-xs">重试</button>
          </div>
        ) : loading ? (
          <div className="space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 rounded-2xl border border-zinc-100 bg-white skeleton" />
            ))}
          </div>
        ) : articles.length === 0 ? (
          <div className="surface rounded-[1.75rem] px-6 py-16 text-center">
            <p className="text-base font-semibold text-zinc-900">暂无文章</p>
            <p className="mt-2 text-sm text-zinc-500">前往“一键生成”创建第一篇文章。</p>
          </div>
        ) : (
          <div className="space-y-2">
            {articles.map((a) => (
              <div
                key={a.id}
                onClick={() => setSelectedArticle(a)}
                className={`rounded-2xl border p-4 cursor-pointer transition-all ${
                  selectedArticle?.id === a.id
                    ? 'border-blue-300 bg-white shadow-[0_18px_40px_-30px_rgba(37,99,235,0.55)]'
                    : 'surface hover:-translate-y-0.5 hover:border-zinc-300'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-sm font-medium text-zinc-900 line-clamp-2">{a.title}</h3>
                    <div className="flex items-center gap-3 mt-2">
                      <span className={`text-[11px] font-medium px-2 py-0.5 rounded-full ${statusColor(a.status)}`}>
                        {statusLabel(a.status)}
                      </span>
                      <span className="text-[11px] text-zinc-300 font-mono">{a.word_count} 字</span>
                      {a.read_count > 0 && (
                        <span className="text-[11px] text-zinc-300 font-mono">{a.read_count} 阅读</span>
                      )}
                    </div>
                  </div>
                  <span className="hidden text-[11px] text-zinc-300 font-mono shrink-0 sm:block">
                    {new Date(a.created_at).toLocaleDateString('zh-CN')}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 分页 */}
        {total > 0 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}
              className="btn-secondary h-9 px-3 text-xs disabled:opacity-30">
              上一页
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
              let p
              if (totalPages <= 7) p = i + 1
              else if (page <= 4) p = i + 1
              else if (page >= totalPages - 3) p = totalPages - 6 + i
              else p = page - 3 + i
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`h-9 w-9 rounded-xl font-mono text-xs transition-colors ${page === p ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-100'}`}>
                  {p}
                </button>
              )
            })}
            <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages}
              className="btn-secondary h-9 px-3 text-xs disabled:opacity-30">
              下一页
            </button>
          </div>
        )}
      </div>

      {/* Detail Panel */}
      <div className="lg:col-span-1">
        <div className="sticky top-8">
          {selectedArticle ? (
            <div className="surface overflow-hidden rounded-[1.5rem]">
              <div className="border-b border-zinc-100 px-5 py-5">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <p className="text-xs font-semibold text-zinc-400">Article Info</p>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${statusColor(selectedArticle.status)}`}>
                    {statusLabel(selectedArticle.status)}
                  </span>
                </div>
                <h3 className="text-lg font-semibold leading-snug tracking-tight text-zinc-950">{selectedArticle.title}</h3>
                {selectedArticle.summary && (
                  <p className="mt-3 text-sm leading-6 text-zinc-500">{selectedArticle.summary}</p>
                )}
              </div>

              <div className="grid grid-cols-2 divide-x divide-y divide-zinc-100 border-b border-zinc-100">
                <div className="p-4">
                  <p className="text-[11px] font-medium text-zinc-400">字数</p>
                  <p className="mt-1 font-mono text-lg font-semibold text-zinc-800">{selectedArticle.word_count || 0}</p>
                </div>
                <div className="p-4">
                  <p className="text-[11px] font-medium text-zinc-400">阅读量</p>
                  <p className="mt-1 font-mono text-lg font-semibold text-zinc-800">{selectedArticle.read_count || 0}</p>
                </div>
                <div className="col-span-2 p-4">
                  <p className="text-[11px] font-medium text-zinc-400">创建时间</p>
                  <p className="mt-1 font-mono text-xs text-zinc-600">
                    {selectedArticle.created_at ? new Date(selectedArticle.created_at).toLocaleString('zh-CN') : '-'}
                  </p>
                </div>
              </div>

              <div className="space-y-2 p-5">
                {selectedArticle.status === 'failed' && (
                  <div className="mb-4 rounded-2xl border border-red-100 bg-red-50 p-4">
                    <p className="text-sm font-semibold text-red-700">这篇文章未通过生成审核</p>
                    <p className="mt-1 text-xs leading-5 text-red-600">失败记录用于排查选题、正文或审核问题，不建议直接下载发布。</p>
                    {selectedReview?.issues?.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {selectedReview.issues.slice(0, 3).map((issue, index) => (
                          <p key={index} className="rounded-xl bg-white/70 p-2 text-xs leading-5 text-red-700">
                            {issue.detail || issue.suggestion || '审核未通过'}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <button
                  onClick={handleShowFullArticle}
                  disabled={loadingFull}
                  className="btn-primary h-11 w-full text-sm disabled:opacity-50"
                >
                  {loadingFull ? '加载中...' : '文稿详情'}
                </button>

                <button
                  onClick={handleReview}
                  disabled={reviewing}
                  className="btn-secondary h-11 w-full text-sm disabled:opacity-50"
                >
                  {reviewing ? '校验中...' : '文稿校验'}
                </button>

              <button
                onClick={handleExport}
                disabled={exporting || selectedArticle.status === 'failed'}
                className="btn-secondary h-11 w-full text-sm disabled:opacity-50"
              >
                {exporting ? '导出中...' : '文稿下载'}
              </button>

              <button
                onClick={handleDelete}
                disabled={deleting}
                className="btn-danger mt-4 h-11 w-full text-sm disabled:opacity-50"
              >
                {deleting ? '删除中...' : '文稿删除'}
              </button>

              {selectedReview && selectedArticle.status !== 'failed' && (
                <div className={`mt-4 rounded-2xl border p-3 text-xs ${
                  selectedReview.passed
                    ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
                    : 'border-red-100 bg-red-50 text-red-700'
                }`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold">{selectedReview.passed ? '校验通过' : '发现问题'}</span>
                    {selectedReview.issues?.length > 0 && <span>{selectedReview.issues.length} 项</span>}
                  </div>
                  {reviewResult?.fixed && (
                    <p className="mt-2 leading-5 text-zinc-600">已自动修正：{reviewResult.fixed.changes || '内容已优化'}</p>
                  )}
                  {reviewResult?.illustrations_regen === true && (
                    <p className="mt-2 leading-5 text-amber-600">插图已同步重新生成</p>
                  )}
                  {selectedReview.issues?.length > 0 && (
                    <details className="mt-2">
                      <summary className="cursor-pointer hover:opacity-70">查看问题详情</summary>
                      <div className="mt-2 max-h-40 space-y-1.5 overflow-auto">
                        {selectedReview.issues.map((iss, i) => (
                          <div key={i} className="rounded-xl bg-white/65 p-2 leading-5 text-zinc-600">
                            <span className="font-semibold">{iss.severity === 'blocker' ? '阻断' : iss.severity === 'warning' ? '警告' : '建议'}：</span>
                            {iss.detail}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
                </div>
              )}
              </div>
            </div>
          ) : (
            <div className="surface rounded-[1.5rem] px-6 py-12 text-center text-zinc-400">
              <p className="text-sm">选择一篇文章查看详情</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
