import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'

const STEPS = [
  { label: '选题', detail: '读取内容池与历史文章，确定今天要写什么' },
  { label: '写作', detail: '正文 Agent 生成 Markdown 文稿' },
  { label: '审核', detail: '检查夸张承诺、事实边界和工作流泄漏' },
  { label: '排版', detail: '转换为公众号可用的阅读版式' },
  { label: '配图', detail: '生成封面与内文插图 prompt' },
]

function elapsedLabel(seconds) {
  if (seconds < 60) return `${seconds}s`
  const min = Math.floor(seconds / 60)
  const sec = seconds % 60
  return `${min}m ${sec}s`
}

function getStepIndex(seconds) {
  if (seconds < 8) return 0
  if (seconds < 24) return 1
  if (seconds < 38) return 2
  if (seconds < 48) return 3
  return 4
}

function PromptBlock({ title, prompt, tone = 'zinc' }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    if (!prompt) return
    navigator.clipboard?.writeText(prompt)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <div className={`rounded-2xl border p-4 ${tone === 'blue' ? 'border-blue-100 bg-blue-50/60' : 'border-zinc-100 bg-zinc-50'}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className={`text-xs font-semibold ${tone === 'blue' ? 'text-blue-800' : 'text-zinc-700'}`}>{title}</span>
        <button onClick={handleCopy} className="btn-secondary h-8 px-3 text-[11px]">
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-zinc-700">{prompt}</p>
    </div>
  )
}

function ArticlePreview({ article, onBack }) {
  const imgs = article.agent_trace?.[2]
  const review = article.agent_trace?.[3]
  const r = review?.second_review || review?.review

  return (
    <div>
      <button
        onClick={onBack}
        className="btn-ghost mb-5 h-9 px-3 text-sm"
      >
        ← 返回生成结果
      </button>

      <article className="surface mx-auto max-w-3xl rounded-[1.5rem] p-6 sm:p-8">
        <h1 className="mb-3 text-2xl font-bold leading-snug text-zinc-900">{article.title}</h1>
        {article.summary && <p className="mb-5 text-sm leading-relaxed text-zinc-500">{article.summary}</p>}

        <div className="mb-8 flex flex-wrap items-center gap-3 text-xs text-zinc-400">
          <span>{article.body?.length || 0} 字</span>
          {article.platform && <span>目标平台：{article.platform}</span>}
          {article.created_at && <span>{new Date(article.created_at).toLocaleString('zh-CN')}</span>}
        </div>

        <div
          className="article-body text-[15px] leading-[1.85] text-zinc-800"
          dangerouslySetInnerHTML={{ __html: article.body }}
        />

        {imgs?.cover && (
          <div className="mt-10 border-t border-zinc-100 pt-6">
            <h3 className="mb-4 text-sm font-semibold text-zinc-900">插图 Prompts</h3>
            <div className="space-y-3">
              <PromptBlock title="封面图 Prompt" prompt={imgs.cover.copy_prompt || imgs.cover.prompt || ''} tone="blue" />
              {imgs.illustrations?.map((ill, i) => (
                <PromptBlock
                  key={i}
                  title={`插图 ${i + 1}${ill.section_title ? `：${ill.section_title}` : ''}`}
                  prompt={ill.copy_prompt || ill.prompt || ''}
                />
              ))}
            </div>
          </div>
        )}

        {r && (
          <div className="mt-10 border-t border-zinc-100 pt-6">
            <h3 className="mb-4 text-sm font-semibold text-zinc-900">文稿校验</h3>
            <div className={`rounded-2xl border p-4 text-sm ${r.passed ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-red-100 bg-red-50 text-red-700'}`}>
              <div className="font-semibold">{r.passed ? '校验通过' : '校验未通过'}</div>
              {review?.fixed?.changes && <p className="mt-2 text-zinc-600">已自动修正：{review.fixed.changes}</p>}
              {r.issues?.length > 0 && (
                <div className="mt-3 space-y-2">
                  {r.issues.map((iss, i) => (
                    <div key={i} className="rounded-xl bg-white/55 p-3 text-xs text-zinc-700">
                      <span className="font-semibold">{iss.severity === 'blocker' ? '阻断' : iss.severity === 'warning' ? '警告' : '建议'}：</span>
                      {iss.detail}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </article>
    </div>
  )
}

export default function Generate() {
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [domains, setDomains] = useState([])
  const [selectedDomain, setSelectedDomain] = useState('')
  const [fullArticle, setFullArticle] = useState(null)
  const [loadingFull, setLoadingFull] = useState(false)
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    api.getDomains().then(data => {
      setDomains(data.domains)
      if (data.domains.length > 0) setSelectedDomain(data.domains[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!generating) return undefined
    setElapsed(0)
    const timer = window.setInterval(() => setElapsed(prev => prev + 1), 1000)
    return () => window.clearInterval(timer)
  }, [generating])

  const selectedDomainLabel = useMemo(() => {
    const current = domains.find(d => d.id === selectedDomain)
    return current?.label || selectedDomain || '默认领域'
  }, [domains, selectedDomain])

  const failedResult = Boolean(result?.error || result?.status === 'failed')
  const activeStep = generating ? getStepIndex(elapsed) : -1

  const handleGenerate = async () => {
    setGenerating(true)
    setResult(null)
    setError(null)
    setFullArticle(null)
    try {
      const domain = selectedDomain || domains[0]?.id || 'tech'
      const data = await api.generateArticle(domain)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setGenerating(false)
    }
  }

  const handleViewFullArticle = async () => {
    if (!result?.id) return
    setLoadingFull(true)
    try {
      const data = await api.getArticle(result.id)
      setFullArticle(data.article || data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoadingFull(false)
    }
  }

  if (fullArticle) {
    return <ArticlePreview article={fullArticle} onBack={() => setFullArticle(null)} />
  }

  return (
    <div className="mx-auto max-w-6xl">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,0.92fr)_minmax(360px,0.72fr)]">
        <section className="surface rounded-[1.75rem] p-6 sm:p-8">
          <div className="flex flex-col gap-6">
            <div>
              <p className="text-sm font-semibold text-blue-600">Generation Console</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-950">一键生成文章</h2>
              <p className="mt-3 max-w-xl text-sm leading-6 text-zinc-500">
                从未使用素材中选题，生成正文，完成审核，再输出封面和插图 prompt。
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-zinc-500">生成领域</span>
                <select
                  value={selectedDomain}
                  onChange={(e) => setSelectedDomain(e.target.value)}
                  disabled={generating}
                  className="control w-full px-3 text-sm disabled:opacity-40"
                >
                  {domains.length === 0 && <option value="">默认领域</option>}
                  {domains.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
                </select>
              </label>

              <button
                onClick={handleGenerate}
                disabled={generating}
                className="btn-primary h-11 px-6 text-sm disabled:cursor-not-allowed disabled:opacity-40"
              >
                {generating ? '生成中...' : '开始生成'}
              </button>
            </div>

            <div className="rounded-2xl border border-zinc-100 bg-zinc-50/70 p-4">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold text-zinc-700">当前任务</p>
                  <p className="mt-1 text-xs text-zinc-400">领域：{selectedDomainLabel}</p>
                </div>
                <span className="rounded-full bg-white px-3 py-1 text-xs font-mono text-zinc-500 ring-1 ring-zinc-200">
                  {generating ? elapsedLabel(elapsed) : '待开始'}
                </span>
              </div>

              <div className="space-y-2">
                {STEPS.map((step, index) => {
                  const done = generating && index < activeStep
                  const active = generating && index === activeStep
                  return (
                    <div
                      key={step.label}
                      className={`flex items-start gap-3 rounded-xl border px-3 py-3 transition-all ${
                        active
                          ? 'border-blue-200 bg-white shadow-[0_16px_32px_-28px_rgba(37,99,235,0.7)]'
                          : done
                            ? 'border-emerald-100 bg-emerald-50/40'
                            : 'border-transparent bg-white/60'
                      }`}
                    >
                      <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                        active ? 'bg-blue-600 text-white' : done ? 'bg-emerald-600 text-white' : 'bg-zinc-100 text-zinc-400'
                      }`}>
                        {done ? '✓' : index + 1}
                      </span>
                      <div>
                        <p className={`text-sm font-semibold ${active ? 'text-zinc-950' : 'text-zinc-600'}`}>{step.label}</p>
                        <p className="mt-0.5 text-xs leading-5 text-zinc-400">{step.detail}</p>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </section>

        <aside className="lg:sticky lg:top-8 lg:self-start">
          {!result && !error && !generating && (
            <div className="surface rounded-[1.75rem] p-6">
              <p className="text-sm font-semibold text-zinc-950">生成后会在这里展示结果</p>
              <p className="mt-2 text-sm leading-6 text-zinc-500">
                通过审核的文章可直接查看详情、下载或进入文章管理；未通过审核的结果会显示阻断原因，方便继续调提示词和素材。
              </p>
            </div>
          )}

          {generating && (
            <div className="surface rounded-[1.75rem] p-6">
              <p className="text-sm font-semibold text-zinc-950">正在生成</p>
              <p className="mt-2 text-sm leading-6 text-zinc-500">当前停留在“{STEPS[activeStep]?.label || '准备'}”阶段。页面可以保持打开，完成后会自动显示结果。</p>
              <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-100">
                <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${Math.min(96, (activeStep + 1) * 20)}%` }} />
              </div>
            </div>
          )}

          {error && (
            <div className="rounded-[1.5rem] border border-red-100 bg-red-50 p-5">
              <p className="text-sm font-semibold text-red-700">生成请求失败</p>
              <p className="mt-2 break-words text-xs leading-5 text-red-600">{error}</p>
            </div>
          )}

          {result && (
            <div className={`rounded-[1.5rem] border p-5 ${failedResult ? 'border-red-100 bg-red-50' : 'surface'}`}>
              <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                  <p className={`text-sm font-semibold ${failedResult ? 'text-red-700' : 'text-zinc-950'}`}>
                    {failedResult ? '生成已拦截' : '生成完成'}
                  </p>
                  <p className={`mt-1 text-xs ${failedResult ? 'text-red-500' : 'text-zinc-400'}`}>
                    {failedResult ? '文稿没有进入正常草稿' : `${result.word_count || 0} 字 · 可继续处理`}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${failedResult ? 'bg-white text-red-600' : 'bg-emerald-50 text-emerald-700'}`}>
                  {failedResult ? '失败' : '草稿'}
                </span>
              </div>

              {result.error && <p className="mb-4 rounded-xl bg-white/70 p-3 text-xs leading-5 text-red-700">{result.error}</p>}

              <div className="space-y-3">
                <div className="rounded-2xl bg-white/70 p-4">
                  <p className="mb-1 text-xs font-semibold text-zinc-500">标题</p>
                  <p className="text-sm leading-6 text-zinc-900">{result.title || '未生成标题'}</p>
                </div>

                {result.summary && (
                  <div className="rounded-2xl bg-white/70 p-4">
                    <p className="mb-1 text-xs font-semibold text-zinc-500">摘要</p>
                    <p className="text-sm leading-6 text-zinc-600">{result.summary}</p>
                  </div>
                )}

                {failedResult && result.issues?.length > 0 && (
                  <div className="rounded-2xl bg-white/70 p-4">
                    <p className="mb-2 text-xs font-semibold text-red-700">阻断原因</p>
                    <div className="space-y-2">
                      {result.issues.map((issue, index) => (
                        <div key={index} className="rounded-xl border border-red-100 bg-red-50/70 p-3 text-xs leading-5 text-red-700">
                          {issue.detail || issue.suggestion || '审核未通过'}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {result.decision && (
                  <details className="rounded-2xl bg-white/70 p-4">
                    <summary className="cursor-pointer text-xs font-semibold text-zinc-500">总编决策</summary>
                    <div className="mt-3 space-y-2 text-sm leading-6 text-zinc-600">
                      <p><span className="text-zinc-400">选题：</span>{result.decision.selected_topic}</p>
                      {result.decision.reason && <p><span className="text-zinc-400">理由：</span>{result.decision.reason}</p>}
                      {result.decision.angle && <p><span className="text-zinc-400">角度：</span>{result.decision.angle}</p>}
                    </div>
                  </details>
                )}
              </div>

              <div className="mt-5 grid gap-2 sm:grid-cols-2">
                <button
                  onClick={handleViewFullArticle}
                  disabled={loadingFull || !result.id}
                  className="btn-secondary h-10 text-sm disabled:opacity-40"
                >
                  {loadingFull ? '加载中...' : '查看详情'}
                </button>
                <button
                  onClick={() => { window.location.hash = '#articles' }}
                  className="btn-primary h-10 text-sm"
                >
                  {failedResult ? '查看失败记录' : '去文章管理'}
                </button>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}
