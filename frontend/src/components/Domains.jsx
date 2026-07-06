import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

const EMPTY = { id: '', label: '', description: '', folo_keywords: [], search_keywords: [], rss_feed_urls: [] }

export default function Domains() {
  const [domains, setDomains] = useState([])
  const [editing, setEditing] = useState(null)    // null | 'new' | domain object
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.listDomainDetails()
      setDomains(data.domains)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSave = async (form) => {
    setSaving(true)
    try {
      if (editing === 'new') {
        await api.createDomain(form)
      } else {
        await api.updateDomain(editing.id, form)
      }
      setEditing(null)
      await load()
    } catch (e) { alert('保存失败: ' + e.message) }
    finally { setSaving(false) }
  }

  const handleDelete = async (id) => {
    if (!confirm(`确定删除领域「${id}」？关联的文章不会自动删除。`)) return
    try {
      await api.deleteDomain(id)
      await load()
    } catch (e) { alert('删除失败: ' + e.message) }
  }

  if (editing) {
    return <DomainForm initial={editing === 'new' ? EMPTY : editing} onSave={handleSave} onCancel={() => setEditing(null)} saving={saving} />
  }

  return (
    <div className="space-y-6">
      <div className="surface rounded-[1.5rem] p-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Domains</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-950">领域管理</h2>
          <p className="mt-1 text-sm text-zinc-500">管理采集领域、关键词和 RSS 来源。</p>
        </div>
        <button onClick={() => setEditing('new')}
          className="btn-primary h-10 px-4 text-sm">
          新建领域
        </button>
      </div>
      </div>

      <div className="space-y-3">
        {domains.length === 0 && (
          <div className="surface rounded-[1.75rem] px-6 py-14 text-center text-sm text-zinc-500">暂无领域，点击上方按钮创建。</div>
        )}
        {domains.map(d => (
          <div key={d.id} className="surface rounded-2xl p-4 transition-all hover:-translate-y-0.5 hover:border-zinc-300">
            <div className="flex items-start justify-between mb-3">
              <div>
                <h3 className="text-sm font-medium text-zinc-900">{d.label}</h3>
                <span className="text-[11px] font-mono text-zinc-400">id: {d.id}</span>
                {d.description && <p className="text-xs text-zinc-400 mt-0.5">{d.description}</p>}
              </div>
              <div className="flex gap-2 shrink-0">
                <button onClick={() => setEditing(d)}
                  className="btn-secondary h-8 px-3 text-[11px]">编辑</button>
                <button onClick={() => handleDelete(d.id)}
                  className="btn-danger h-8 px-3 text-[11px]">删除</button>
              </div>
            </div>
            <div className="flex flex-wrap gap-4 text-[11px]">
              {d.folo_keywords?.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-zinc-300">Folo:</span>
                  <div className="flex flex-wrap gap-1">
                    {d.folo_keywords.map(k => <span key={k} className="px-1.5 py-0.5 bg-zinc-50 rounded text-zinc-500">{k}</span>)}
                  </div>
                </div>
              )}
              {d.search_keywords?.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-zinc-300">搜索:</span>
                  <div className="flex flex-wrap gap-1">
                    {d.search_keywords.map(k => <span key={k} className="px-1.5 py-0.5 bg-zinc-50 rounded text-zinc-500">{k}</span>)}
                  </div>
                </div>
              )}
              {d.rss_feed_urls?.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-zinc-300">RSS:</span>
                  <span className="text-zinc-400">{d.rss_feed_urls.length} 个源</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function DomainForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    ...initial,
    folo_keywords: initial.folo_keywords?.join('\n') || '',
    search_keywords: initial.search_keywords?.join('\n') || '',
    rss_feed_urls: initial.rss_feed_urls?.join('\n') || '',
  })

  const handleSubmit = (e) => {
    e.preventDefault()
    onSave({
      ...form,
      folo_keywords: form.folo_keywords.split('\n').filter(Boolean),
      search_keywords: form.search_keywords.split('\n').filter(Boolean),
      rss_feed_urls: form.rss_feed_urls.split('\n').filter(Boolean),
    })
  }

  const set = (k, v) => setForm(p => ({ ...p, [k]: v }))

  return (
    <form onSubmit={handleSubmit} className="surface max-w-3xl rounded-[1.5rem] p-5">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Domain Config</p>
          <h2 className="mt-2 text-xl font-semibold text-zinc-900">
            {initial.id ? `编辑领域「${initial.id}」` : '新建领域'}
          </h2>
        </div>
        <button type="button" onClick={onCancel}
          className="btn-secondary h-10 px-4 text-sm">
          返回列表
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">领域标识 *</label>
          <input required value={form.id} onChange={e => set('id', e.target.value)}
            disabled={!!initial.id}
            className="control w-full px-3 text-sm disabled:opacity-40" />
          <p className="text-[11px] text-zinc-300 mt-0.5">英文标识，如 "tech"</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">名称 *</label>
          <input required value={form.label} onChange={e => set('label', e.target.value)}
            className="control w-full px-3 text-sm" />
        </div>

        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">描述</label>
          <input value={form.description} onChange={e => set('description', e.target.value)}
            className="control w-full px-3 text-sm" />
        </div>

        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">Folo 搜索关键词（每行一个）</label>
          <textarea rows={4} value={form.folo_keywords} onChange={e => set('folo_keywords', e.target.value)}
            className="control min-h-[110px] w-full resize-none px-3 py-2 text-sm" />
        </div>

        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">搜索引擎关键词（每行一个）</label>
          <textarea rows={4} value={form.search_keywords} onChange={e => set('search_keywords', e.target.value)}
            className="control min-h-[110px] w-full resize-none px-3 py-2 text-sm" />
        </div>

        <div>
          <label className="block text-xs font-medium text-zinc-500 mb-1">RSS 订阅源 URL（每行一个）</label>
          <textarea rows={3} value={form.rss_feed_urls} onChange={e => set('rss_feed_urls', e.target.value)}
            placeholder="https://example.com/feed"
            className="control min-h-[96px] w-full resize-none px-3 py-2 text-sm" />
        </div>
      </div>

      <div className="flex items-center gap-3 mt-6">
        <button type="submit" disabled={saving}
          className="btn-primary h-10 px-6 text-sm disabled:opacity-40">
          {saving ? '保存中...' : '保存'}
        </button>
        <button type="button" onClick={onCancel}
          className="btn-secondary h-10 px-6 text-sm">
          取消
        </button>
      </div>
    </form>
  )
}
