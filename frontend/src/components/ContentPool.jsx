import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

export default function ContentPool() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [source, setSource] = useState('')
  const [domain, setDomain] = useState('')
  const [domains, setDomains] = useState([])
  const [loading, setLoading] = useState(false)
  const [deleting, setDeleting] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [detailItem, setDetailItem] = useState(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  // 采集弹窗
  const [showModal, setShowModal] = useState(false)
  const [collectSource, setCollectSource] = useState('folo')
  const [collectDomain, setCollectDomain] = useState('tech')
  const [collectLimit, setCollectLimit] = useState(20)
  const [collecting, setCollecting] = useState(false)
  const [collectMsg, setCollectMsg] = useState(null)
  const [activeTasks, setActiveTasks] = useState([])
  const [foloStatus, setFoloStatus] = useState({ status: 'checking', user: null })
  const [wechatUrls, setWechatUrls] = useState('')

  const pageSize = 8

  const checkFoloStatus = useCallback(() => {
    api.getFoloStatus().then(data => setFoloStatus(data)).catch(() => {})
  }, [])

  useEffect(() => {
    api.getDomains().then(data => {
      setDomains(data.domains)
      if (data.domains.length > 0) setCollectDomain(data.domains[0].id)
    }).catch(() => {})
    checkFoloStatus()
  }, [checkFoloStatus])

  const handleFoloLogin = async () => {
    try {
      const res = await api.triggerFoloLogin()
      alert('已成功拉起浏览器登录窗口，请在浏览器中完成 Folo 登录。完成后本页面将自动刷新状态。')
      let count = 0
      const interval = setInterval(async () => {
        count++
        try {
          const statusRes = await api.getFoloStatus()
          if (statusRes.status === 'authenticated') {
            setFoloStatus(statusRes)
            clearInterval(interval)
          }
        } catch (e) {}
        if (count >= 30) clearInterval(interval)
      }, 2000)
    } catch (e) {
      alert('唤起登录失败：' + e.message)
    }
  }

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getContent({ page, page_size: pageSize, keyword, source, domain: domain || undefined })
      setItems(data.items)
      setTotal(data.total)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [page, keyword, source, domain])

  useEffect(() => { fetchData() }, [fetchData])

  // ── 采集 ────────────────────────────────────────────
  const handleCollect = async () => {
    setCollecting(true)
    setCollectMsg('正在提交采集任务，请稍候...')
    try {
      let res
      if (collectSource === 'wechat' && wechatUrls.trim()) {
        const urls = wechatUrls.split(/\s+/).map(x => x.trim()).filter(Boolean)
        res = await api.importWeChatArticles(urls, collectDomain)
      } else {
        res = await api.triggerCollection(collectSource, collectDomain, collectLimit)
      }
      const tasks = res.tasks || []
      if (tasks.length === 0) {
        setCollectMsg('未提交任何采集任务。')
        setCollecting(false)
        return
      }
      setShowModal(false)
      setCollectMsg('采集任务已提交，后台正在处理中，请稍候...')
      
      const tasksToPoll = tasks.map(t => ({ ...t, status: 'PENDING', result: null }))
      setActiveTasks(tasksToPoll)
    } catch (e) {
      setCollectMsg(`采集失败：${e.message}`)
      setCollecting(false)
    }
  }

  // 轮询采集任务的真实状态与结果
  useEffect(() => {
    if (activeTasks.length === 0) return undefined

    const timer = setInterval(async () => {
      let allDone = true
      const updatedTasks = []

      for (const t of activeTasks) {
        if (t.status === 'SUCCESS' || t.status === 'FAILURE') {
          updatedTasks.push(t)
          continue
        }

        try {
          const statusRes = await api.getCollectionStatus(t.task_id)
          const newStatus = statusRes.status
          const newResult = statusRes.result

          updatedTasks.push({
            ...t,
            status: newStatus,
            result: newResult
          })

          if (newStatus !== 'SUCCESS' && newStatus !== 'FAILURE') {
            allDone = false
          }
        } catch (err) {
          updatedTasks.push({
            ...t,
            status: 'FAILURE',
            result: err.message
          })
        }
      }

      setActiveTasks(updatedTasks)

      if (allDone) {
        clearInterval(timer)

        // 任务全部结束，汇总输出结果
        const details = []
        updatedTasks.forEach(x => {
          const srcLabel = x.source === 'folo' ? 'Folo智能' : x.source === 'rss' ? 'RSS' : x.source === 'wechat' ? '微信' : x.source === 'zhihu' ? '知乎' : '搜索引擎'
          if (x.status === 'SUCCESS') {
            const col = x.result?.collected ?? 0
            const sav = x.result?.saved ?? 0
            details.push(`${srcLabel}抓回 ${col} 条，入库 ${sav} 条`)
          } else if (x.status === 'FAILURE') {
            details.push(`${srcLabel}失败(${x.result || '网络异常'})`)
          }
        })

        let msg = '数据采集完成。'
        if (details.length > 0) {
          msg = `采集结束：${details.join('；')}`
        }

        setCollectMsg(msg)
        setCollecting(false)
        setActiveTasks([])
        fetchData() // 自动刷新列表数据

        // 6 秒后自动收起结果气泡
        setTimeout(() => {
          setCollectMsg(null)
        }, 6000)
      }
    }, 3000)

    return () => clearInterval(timer)
  }, [activeTasks, fetchData])

  // ── 删除 ────────────────────────────────────────────
  const handleDelete = async (id) => {
    if (!confirm('确定删除该内容？')) return
    setDeleting(id)
    try {
      await api.deleteContent(id)
      setItems(prev => prev.filter(i => i.id !== id))
      setTotal(prev => prev - 1)
    } catch (e) {
      alert('删除失败: ' + e.message)
    } finally {
      setDeleting(null)
    }
  }

  // ── 多选 ────────────────────────────────────────────
  const allSelected = items.length > 0 && selectedIds.size === items.length
  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const toggleSelectAll = () => {
    if (allSelected) setSelectedIds(new Set())
    else setSelectedIds(new Set(items.map(i => i.id)))
  }
  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return
    if (!confirm(`确定删除选中的 ${selectedIds.size} 条内容？`)) return
    setDeleting('batch')
    try {
      await api.batchDeleteContent([...selectedIds])
      setSelectedIds(new Set())
      fetchData()
    } catch (e) {
      alert('批量删除失败: ' + e.message)
    } finally {
      setDeleting(null)
    }
  }

  const handleGenerateFromSelected = () => {
    const selectedItems = items.filter(i => selectedIds.has(i.id))
    localStorage.setItem('selected_content_items', JSON.stringify(selectedItems))
    setSelectedIds(new Set())
    window.location.hash = '#generate'
  }

  const totalPages = Math.ceil(total / pageSize)

  // ── 查看详情 ──────────────────────────────────────
  const handleViewDetail = async (item) => {
    setLoadingDetail(true)
    try {
      const data = await api.getContentItem(item.id)
      setDetailItem(data)
    } catch (e) {
      alert('加载失败: ' + e.message)
    } finally {
      setLoadingDetail(false)
    }
  }

  // ── 格式化时间 ──────────────────────────────────────
  const fmtTime = (iso) => {
    if (!iso) return null
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now - d
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin} 分钟前`
    const diffH = Math.floor(diffMin / 60)
    if (diffH < 24) return `${diffH} 小时前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }

  return (
    <div className="space-y-6">
      {/* 顶部操作栏 */}
      <div className="surface rounded-[1.5rem] px-5 py-4">
        <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-semibold text-zinc-950">素材检索与采集</p>
            <p className="mt-1 text-xs text-zinc-500">按领域、来源和关键词快速收敛可用选题素材。</p>
          </div>
          <span className="hidden text-[11px] font-mono text-zinc-400 sm:block">{total} 条素材</span>
        </div>

        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <div className="grid min-w-0 flex-1 grid-cols-1 gap-3 md:grid-cols-[minmax(280px,1fr)_220px_180px]">
            <div className="relative">
              <input
                type="text"
                placeholder="搜索标题或摘要..."
                value={keyword}
                onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
                className="control w-full pl-4 pr-10 text-sm placeholder:text-zinc-300"
              />
              <svg className="absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            </div>

            <select value={domain} onChange={(e) => { setDomain(e.target.value); setPage(1) }}
              className="control w-full px-3 text-sm">
              <option value="">全部领域</option>
              {domains.map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
            </select>

            <select value={source} onChange={(e) => { setSource(e.target.value); setPage(1) }}
              className="control w-full px-3 text-sm">
              <option value="">全部来源</option>
              <option value="rss">RSS</option>
              <option value="folo">Folo</option>
              <option value="wechat">微信</option>
              <option value="zhihu">知乎</option>
              <option value="search_engine">搜索引擎</option>
            </select>
          </div>

          <div className="flex shrink-0 flex-nowrap items-center gap-2 overflow-x-auto pb-1 xl:justify-end xl:pb-0">
            <label className="flex h-10 items-center gap-2 rounded-xl border border-zinc-200/80 bg-white/70 px-3 text-xs text-zinc-500 cursor-pointer select-none">
              <input type="checkbox" checked={allSelected} onChange={toggleSelectAll}
                className="h-3.5 w-3.5 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900/20 accent-zinc-900" />
              <span className="font-mono sm:hidden">{total}</span>
              <span>全选</span>
            </label>

            {selectedIds.size > 0 && (
              <>
                <button onClick={handleGenerateFromSelected}
                  className="btn-primary h-10 shrink-0 px-4 text-xs bg-blue-600 text-white shadow-sm hover:bg-blue-700 active:scale-[0.98]">
                  生成文章 ({selectedIds.size})
                </button>
                <button onClick={handleBatchDelete} disabled={deleting === 'batch'}
                  className="btn-danger h-10 shrink-0 px-4 text-xs disabled:opacity-40">
                  {deleting === 'batch' ? '删除中...' : `删除 ${selectedIds.size} 条`}
                </button>
              </>
            )}

            <button onClick={() => setShowModal(true)}
              className="btn-primary h-10 shrink-0 px-4 text-xs">
              新建采集
            </button>
          </div>
        </div>
      </div>

      {/* 采集状态 */}
      {collectMsg && (
        <div className={`rounded-2xl border px-4 py-3 text-xs ${collectMsg.startsWith('采集失败') ? 'border-red-100 bg-red-50 text-red-600' : 'border-emerald-100 bg-emerald-50 text-emerald-700'}`}>
          {collectMsg}
        </div>
      )}

      {/* 内容列表 */}
      {loading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => <div key={i} className="h-24 rounded-2xl border border-zinc-100 bg-white skeleton" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="surface rounded-[1.75rem] px-6 py-16 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-blue-50">
            <svg className="w-6 h-6 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </div>
          <p className="text-base font-semibold text-zinc-900">内容池为空</p>
          <p className="mt-2 text-sm text-zinc-500">点击“开始采集”从 RSS、Folo、微信、知乎或搜索引擎获取内容。</p>
          <button onClick={() => setShowModal(true)}
            className="btn-primary mt-6 h-10 px-5 text-sm">
            开始采集
          </button>
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map(item => (
            <div key={item.id} className={`surface rounded-2xl px-4 py-3 transition-all hover:-translate-y-0.5 hover:border-zinc-300 ${item.used_at ? 'bg-zinc-50/70' : ''}`}>
              <div className="flex items-start gap-3">
                {/* 多选框 */}
                <label className="pt-0.5 cursor-pointer" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selectedIds.has(item.id)} onChange={() => toggleSelect(item.id)}
                    className="w-3.5 h-3.5 rounded border-zinc-300 text-zinc-900 focus:ring-zinc-900/20 accent-zinc-900" />
                </label>
                {/* 左侧：主要信息 */}
                <div className="flex-1 min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <h3 className={`min-w-0 truncate text-sm font-medium cursor-pointer hover:text-zinc-600 ${item.used_at ? 'text-zinc-500' : 'text-zinc-900'}`}
                      onClick={() => handleViewDetail(item)}>
                      {item.title}
                    </h3>
                    {item.used_at && (
                      <span className="shrink-0 rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                        已生成文章
                      </span>
                    )}
                  </div>
                  {item.summary && (
                    <p className="text-xs text-zinc-400 mt-1 line-clamp-1">{item.summary}</p>
                  )}
                  {item.body && (
                    <p className="text-xs text-zinc-300 mt-1 line-clamp-1 italic">
                      {item.body.replace(/<[^>]*>/g, '').slice(0, 200)}…
                    </p>
                  )}
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <span className="text-[11px] font-mono text-zinc-400 bg-zinc-50 px-1.5 py-0.5 rounded">{item.source}</span>
                    <span className="text-[11px] font-mono text-zinc-400 bg-zinc-50 px-1.5 py-0.5 rounded">{item.domain}</span>
                    {item.source_name && <span className="text-[11px] text-zinc-300">{item.source_name}</span>}
                    {item.author && <span className="text-[11px] text-zinc-300">{item.author}</span>}
                  </div>
                </div>

                {/* 右侧：元数据 */}
                <div className="flex flex-col items-end gap-1 shrink-0 min-w-[100px]">
                  {item.used_at && (
                    <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-500" title={item.used_at}>
                      已用 {fmtTime(item.used_at)}
                    </span>
                  )}
                  {item.quality && (
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      item.quality.score >= 75 ? 'bg-emerald-50 text-emerald-700' :
                      item.quality.score >= 55 ? 'bg-amber-50 text-amber-700' :
                      'bg-red-50 text-red-600'
                    }`}>
                      质量 {item.quality.score}
                    </span>
                  )}
                  {/* 删除按钮 */}
                  <button onClick={() => handleDelete(item.id)} disabled={deleting === item.id}
                    className="btn-ghost h-7 w-7 text-[11px] disabled:opacity-30"
                    aria-label="删除内容">
                    {deleting === item.id ? '...' : '×'}
                  </button>
                  {/* 发布时间 */}
                  <div className="flex items-center gap-1 text-[11px] text-zinc-400">
                    {item.published_at && <span title={item.published_at}>{fmtTime(item.published_at)}</span>}
                    {!item.published_at && <span className="text-zinc-200">时间未知</span>}
                  </div>
                  {/* 互动数据 */}
                  <div className="flex items-center gap-2 text-[11px] text-zinc-400">
                    <span className={item.read_count > 0 ? '' : 'text-zinc-200'}>
                      查看 {item.read_count}
                    </span>
                    {item.like_count > 0 && <span>点赞 {item.like_count}</span>}
                    {item.comment_count > 0 && <span>评论 {item.comment_count}</span>}
                  </div>
                </div>
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

      {/* ===== 采集弹窗 ===== */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/35 p-4 backdrop-blur-sm" onClick={() => setShowModal(false)}>
          <div className="surface w-full max-w-xl rounded-[1.5rem] p-6 sm:p-7" onClick={(e) => e.stopPropagation()}>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-base font-semibold text-zinc-900">采集设置</h3>
                <p className="mt-1 text-xs text-zinc-500">选择来源、领域和采集条数，任务会在后台执行。</p>
              </div>
              <button onClick={() => setShowModal(false)}
                className="btn-ghost -mr-1 -mt-1 h-8 w-8 text-base"
                aria-label="关闭采集设置">
                ×
              </button>
            </div>

            <div className="space-y-5">
              {/* 选择数据源 */}
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">数据源</label>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
                  {[
                    { value: 'folo', label: 'Folo' },
                    { value: 'wechat', label: '微信' },
                    { value: 'zhihu', label: '知乎' },
                    { value: 'rss', label: 'RSS' },
                    { value: 'search', label: '搜索引擎' },
                    { value: 'all', label: '全部' },
                  ].map(s => (
                    <button key={s.value}
                      onClick={() => setCollectSource(s.value)}
                      className={`h-10 min-w-0 whitespace-nowrap rounded-xl px-2 text-xs font-medium transition-all active:scale-[0.97] ${
                        collectSource === s.value
                          ? 'bg-zinc-900 text-white'
                          : 'border border-zinc-100 bg-zinc-50 text-zinc-500 hover:bg-zinc-100'
                      }`}>
                      {s.label}
                    </button>
                  ))}
                </div>

                {collectSource === 'folo' && (
                  <div className="mt-2.5 rounded-2xl border border-zinc-200/80 bg-zinc-50/50 px-3.5 py-2.5 text-xs flex items-center justify-between">
                    <div className="flex items-center gap-2 text-zinc-600">
                      <span className={`h-2 w-2 rounded-full ${foloStatus.status === 'authenticated' ? 'bg-emerald-500' : 'bg-amber-500'}`} />
                      <span className="font-medium">
                        {foloStatus.status === 'authenticated' 
                          ? `Folo 已激活 (${foloStatus.user})` 
                          : 'Folo 尚未登录授权'}
                      </span>
                    </div>
                    {foloStatus.status !== 'authenticated' && (
                      <button onClick={handleFoloLogin} className="whitespace-nowrap text-xs text-blue-600 font-semibold hover:underline bg-transparent border-0 cursor-pointer p-0">
                        立即登录授权 ↗
                      </button>
                    )}
                  </div>
                )}

                {collectSource === 'wechat' && (
                  <div className="mt-3">
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <label className="block text-xs font-medium text-zinc-500">微信文章链接</label>
                      <span className="text-[11px] text-zinc-300">留空则按领域关键词搜索</span>
                    </div>
                    <textarea
                      value={wechatUrls}
                      onChange={e => setWechatUrls(e.target.value)}
                      placeholder="粘贴 mp.weixin.qq.com 文章链接，多个链接用换行或空格分隔"
                      className="control min-h-[104px] w-full resize-none px-3 py-2.5 text-sm leading-relaxed placeholder:text-zinc-300"
                    />
                  </div>
                )}
              </div>

              {/* 选择领域 */}
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">领域</label>
                <select value={collectDomain} onChange={e => setCollectDomain(e.target.value)}
                  className="control w-full px-3 text-sm">
                  {domains.map(d => <option key={d.id} value={d.id}>{d.label} ({d.id})</option>)}
                </select>
              </div>

              {/* 采集条数 */}
              <div>
                <label className="block text-xs font-medium text-zinc-500 mb-1.5">
                  采集条数 <span className="text-zinc-300">（多个关键词将均衡分布）</span>
                </label>
                <input type="number" min={5} max={100} value={collectLimit}
                  onChange={e => setCollectLimit(Number(e.target.value))}
                  className="control w-full px-3 text-sm" />
              </div>
            </div>

            <div className="mt-7 grid grid-cols-2 gap-3">
              <button onClick={handleCollect} disabled={collecting}
                className="btn-primary h-11 text-sm disabled:opacity-40">
                {collecting ? '提交中...' : '开始采集'}
              </button>
              <button onClick={() => setShowModal(false)}
                className="btn-secondary h-11 text-sm">
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== 内容详情弹窗 ===== */}
      {detailItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/35 p-4 backdrop-blur-sm" onClick={() => setDetailItem(null)}>
          <div className="surface max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-[1.5rem] p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between mb-4">
              <div className="flex-1 min-w-0 mr-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-zinc-900">{detailItem.title}</h3>
                  {detailItem.used_at && (
                    <span className="rounded-full border border-blue-100 bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700">
                      已用于生成文章
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <span className="text-[11px] font-mono text-zinc-400 bg-zinc-50 px-1.5 py-0.5 rounded">{detailItem.source}</span>
                  <span className="text-[11px] text-zinc-300">{detailItem.source_name}</span>
                  {detailItem.author && <span className="text-[11px] text-zinc-300">{detailItem.author}</span>}
                  {detailItem.used_at && <span className="text-[11px] text-zinc-400">生成时间 {fmtTime(detailItem.used_at)}</span>}
                </div>
              </div>
              <button onClick={() => setDetailItem(null)}
                className="btn-ghost flex h-8 w-8 items-center justify-center"
                aria-label="关闭详情">
                ×
              </button>
            </div>

            {/* 标签 */}
            {detailItem.tags && detailItem.tags.length > 0 && (
              <div className="flex items-center gap-1.5 mb-4 flex-wrap">
                {detailItem.tags.map((t, i) => (
                  <span key={i} className="text-[11px] text-zinc-400 bg-zinc-50 px-2 py-0.5 rounded-full">{t}</span>
                ))}
              </div>
            )}

            {/* 正文 */}
            <div className="text-sm text-zinc-700 leading-relaxed whitespace-pre-wrap">
              {detailItem.body || '(无正文内容)'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
