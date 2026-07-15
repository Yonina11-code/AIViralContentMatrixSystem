import { useState, useEffect } from 'react'
import { api } from '../api/client'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const [dragOver, setDragOver] = useState(false)

  const loadStats = async () => {
    setLoading(true)
    try {
      const data = await api.getArticleStats()
      setStats(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadStats() }, [])

  const handleFileImport = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    setImporting(true)
    setImportMsg('')
    try {
      const res = await api.importStats(file)
      setImportMsg(`已导入：${res.message}`)
      if (res.unmatched?.length > 0) {
        setImportMsg(`已导入：${res.message}（${res.unmatched.length} 篇未匹配）`)
      }
      setTimeout(() => { loadStats(); setImportMsg('') }, 3000)
    } catch (e) {
      setImportMsg('导入失败：' + e.message)
    } finally {
      setImporting(false)
      // 清空 input 以允许重复上传同一文件
      e.target.value = ''
    }
  }

  const handleSync = async () => {
    setSyncing(true)
    setSyncMsg('')
    try {
      const res = await api.syncStats(7)
      setSyncMsg('数据同步任务已提交，稍后刷新即可看到最新数据')
      // 3秒后自动刷新
      setTimeout(() => { loadStats(); setSyncMsg('') }, 3000)
    } catch (e) {
      setSyncMsg('同步失败：' + e.message)
    } finally {
      setSyncing(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-5">
        <div className="h-9 w-48 rounded-xl skeleton" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[...Array(4)].map((_, i) => <div key={i} className="h-28 rounded-2xl border border-zinc-100 bg-white skeleton" />)}
        </div>
      </div>
    )
  }

  if (!stats || stats.overview.total_articles === 0) {
    return (
      <div className="surface mx-auto max-w-2xl rounded-[1.75rem] px-6 py-16 text-center">
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50 text-blue-700">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 19V5m0 14h16M8 15l3-3 3 2 5-7" />
          </svg>
        </div>
        <p className="text-base font-semibold text-zinc-900">暂无已发布文章的数据</p>
        <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-zinc-500">发布文章后，导入微信导出的 .xls 文件，即可在这里查看阅读、分享和收藏表现。</p>
        <div className="mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
          {importMsg && <span className={`text-xs ${importMsg.startsWith('已导入') ? 'text-emerald-600' : 'text-red-500'}`}>{importMsg}</span>}
          <button
            onClick={() => document.getElementById('xls-upload-empty').click()}
            disabled={importing}
            className="btn-primary h-10 px-5 text-sm disabled:opacity-50"
          >
            {importing ? '导入中...' : '导入 Excel'}
          </button>
          <input
            id="xls-upload-empty"
            type="file"
            accept=".xls"
            className="hidden"
            onChange={handleFileImport}
          />
        </div>
      </div>
    )
  }

  const { overview, by_domain, by_source = [], by_day, top_articles } = stats

  return (
    <div className="space-y-8">

      {/* 标题 + 同步/导入按钮 */}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Performance</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-950">发布表现总览</h2>
          <p className="mt-1 text-sm text-zinc-500">用导入数据观察内容资产是否真正带来阅读、分享和收藏。</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {importMsg && <span className={`rounded-full px-3 py-1 text-xs ${importMsg.startsWith('已导入') ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{importMsg}</span>}
          {syncMsg && <span className={`rounded-full px-3 py-1 text-xs ${syncMsg.startsWith('同步失败') ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-700'}`}>{syncMsg}</span>}
          <button
            onClick={() => document.getElementById('xls-upload').click()}
            disabled={importing}
            className="btn-primary h-10 px-4 text-xs disabled:opacity-50"
          >
            {importing ? '导入中...' : '导入 Excel'}
          </button>
          <input
            id="xls-upload"
            type="file"
            accept=".xls"
            className="hidden"
            onChange={handleFileImport}
          />
          <button
            onClick={handleSync}
            disabled={syncing}
            className="btn-secondary h-10 px-4 text-xs disabled:opacity-50"
          >
            {syncing ? '同步中...' : '同步公众号数据'}
          </button>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-[1.2fr_1fr_1fr_1.5fr]">
        <div className="surface rounded-[1.5rem] p-5">
          <p className="text-xs font-medium text-zinc-400">总阅读</p>
          <p className="mt-3 font-mono text-4xl font-semibold tracking-tight text-zinc-950">{overview.total_reads}</p>
          <p className="mt-2 text-xs text-zinc-400">共 {overview.total_articles} 篇文章</p>
        </div>
        <div className="surface rounded-[1.5rem] p-5">
          <p className="text-xs font-medium text-zinc-400">总分享</p>
          <p className="mt-3 font-mono text-3xl font-semibold tracking-tight text-zinc-950">{overview.total_shares}</p>
          <p className="mt-2 text-xs text-zinc-400">分享率 {overview.total_reads > 0 ? (overview.total_shares / overview.total_reads * 100).toFixed(1) : 0}%</p>
        </div>
        <div className="surface rounded-[1.5rem] p-5">
          <p className="text-xs font-medium text-zinc-400">总收藏</p>
          <p className="mt-3 font-mono text-3xl font-semibold tracking-tight text-zinc-950">{overview.total_favorites}</p>
          <p className="mt-2 text-xs text-zinc-400">收藏率 {overview.total_reads > 0 ? (overview.total_favorites / overview.total_reads * 100).toFixed(1) : 0}%</p>
        </div>
        <div className="rounded-[1.5rem] border border-blue-100 bg-blue-50/70 p-5">
          <p className="text-xs font-semibold text-blue-700">最佳文章</p>
          <p className="mt-3 line-clamp-2 text-lg font-semibold leading-snug text-zinc-950">{overview.best_article?.title || '-'}</p>
          <p className="mt-2 font-mono text-xs text-blue-700">{overview.best_article?.reads || 0} 阅读</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 各领域表现 */}
        <div className="surface rounded-[1.5rem] p-5">
          <h3 className="mb-4 text-sm font-semibold text-zinc-900">各领域表现</h3>
          {by_domain.length === 0 ? (
            <p className="text-xs text-zinc-400">暂无数据</p>
          ) : (
            <div className="space-y-3">
              {by_domain.map((d) => {
                const maxReads = Math.max(...by_domain.map(x => x.total_reads))
                const pct = maxReads > 0 ? (d.total_reads / maxReads * 100) : 0
                return (
                  <div key={d.domain}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-zinc-700 font-medium">{d.domain}</span>
                      <span className="text-zinc-400">{d.total_reads} 阅读 · {d.article_count} 篇</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
                      <div
                        className="h-full rounded-full bg-blue-600 transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <p className="text-[10px] text-zinc-300 mt-0.5">平均 {d.avg_reads} 阅读/篇</p>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* 阅读趋势 */}
        <div className="surface rounded-[1.5rem] p-5">
          <h3 className="mb-4 text-sm font-semibold text-zinc-900">阅读趋势</h3>
          {by_day.length === 0 ? (
            <p className="text-xs text-zinc-400">暂无数据</p>
          ) : (
            <div className="space-y-2">
              {by_day.map((d) => {
                const maxReads = Math.max(...by_day.map(x => x.reads))
                const barH = maxReads > 0 ? (d.reads / maxReads * 100) : 0
                return (
                  <div key={d.date} className="flex items-center gap-3">
                    <span className="text-[11px] text-zinc-400 w-20 shrink-0">{d.date.slice(5)}</span>
                    <div className="relative h-5 flex-1 overflow-hidden rounded bg-zinc-100">
                      <div
                        className="h-full rounded bg-blue-500/75 transition-all"
                        style={{ width: `${barH}%` }}
                      />
                    </div>
                    <span className="text-xs text-zinc-600 font-mono w-8 text-right">{d.reads}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <div className="surface rounded-[1.5rem] p-5">
        <h3 className="mb-4 text-sm font-semibold text-zinc-900">素材来源复盘</h3>
        {by_source.length === 0 ? (
          <p className="text-xs text-zinc-400">暂无可归因的素材来源数据。生成文章时引用素材后，发布表现会在这里按来源归因。</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {by_source.map((s) => (
              <div key={s.source} className="rounded-2xl border border-zinc-100 bg-zinc-50/60 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-zinc-900">{s.source}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-mono text-zinc-400">{s.material_refs} 引用</span>
                </div>
                <p className="mt-3 font-mono text-2xl font-semibold text-zinc-950">{s.total_reads}</p>
                <p className="mt-1 text-xs text-zinc-400">{s.article_count} 篇文章 · 平均 {s.avg_reads} 阅读</p>
                <p className="mt-2 text-[11px] text-zinc-400">{s.total_shares} 分享 · {s.total_favorites} 收藏</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 文章排行 */}
      <div className="surface rounded-[1.5rem] p-5">
        <h3 className="mb-4 text-sm font-semibold text-zinc-900">文章阅读排行</h3>
        {top_articles.length === 0 ? (
          <p className="text-xs text-zinc-400">暂无已发布文章</p>
        ) : (
          <div className="space-y-1">
            {top_articles.map((a, i) => (
              <div key={a.id} className="flex items-center gap-3 rounded-xl p-2.5 transition-colors hover:bg-zinc-50">
                <span className={`text-xs font-bold w-5 text-center ${
                  i === 0 ? 'text-blue-600' : i === 1 ? 'text-zinc-500' : i === 2 ? 'text-zinc-400' : 'text-zinc-300'
                }`}>
                  #{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-900 truncate">{a.title}</p>
                  <p className="text-[11px] text-zinc-400">
                    {a.published_at ? new Date(a.published_at).toLocaleDateString('zh-CN') : '-'}
                    {' · '}{a.word_count} 字
                  </p>
                </div>
                <div className="flex items-center gap-4 text-xs text-zinc-500 shrink-0">
                  <span>{a.reads} 阅读</span>
                  <span>{a.shares} 分享</span>
                  <span>{a.favorites} 收藏</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 底部提示 */}
      <p className="text-[11px] text-zinc-300 text-center">
        数据来源：微信公众平台后台导出 .xls 文件
      </p>
    </div>
  )
}
