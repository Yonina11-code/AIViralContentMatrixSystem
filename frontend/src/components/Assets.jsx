import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

const CATEGORY_LABELS = {
  title_template: '标题模板',
  opening_template: '开头模板',
  transition_template: '转折模板',
  case_template: '案例模板',
  interaction_template: '互动模板',
  comment_template: '评论模板',
  image_style: '图片风格',
  prompt_template: 'Prompt 模板',
  writing_style: '写作风格',
  viral_case: '爆文案例',
  risk_rule: '风险规则',
  platform_rule: '平台规则',
}

export default function Assets() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(false)
  const [category, setCategory] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [newCard, setNewCard] = useState({ name: '', category: 'title_template', content: '' })
  const [scoring, setScoring] = useState(false)
  const [scoreMsg, setScoreMsg] = useState('')

  const fetchCards = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getAssets({ category: category || undefined })
      setCards(data.items)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [category])

  useEffect(() => { fetchCards() }, [fetchCards])

  const handleCreate = async () => {
    if (!newCard.name || !newCard.content) return
    try {
      await api.createAsset(newCard)
      setNewCard({ name: '', category: 'title_template', content: '' })
      setShowCreate(false)
      fetchCards()
    } catch (e) {
      console.error(e)
    }
  }

  const handleRecomputeScores = async () => {
    setScoring(true)
    setScoreMsg('')
    try {
      const res = await api.recomputeAssetScores()
      setScoreMsg(`已更新 ${res.updated} 张资产卡片评分`)
      fetchCards()
      setTimeout(() => setScoreMsg(''), 4000)
    } catch (e) {
      setScoreMsg('评分更新失败：' + e.message)
    } finally {
      setScoring(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="surface rounded-[1.5rem] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Asset Library</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-950">内容资产库</h2>
            <p className="mt-1 text-sm text-zinc-500">沉淀标题、开头、案例、规则和写作风格，供生成流程复用。</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
          {scoreMsg && <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-700">{scoreMsg}</span>}
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="control px-3 text-sm"
          >
            <option value="">全部分类</option>
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
          <button
            onClick={handleRecomputeScores}
            disabled={scoring}
            className="btn-secondary h-10 px-4 text-sm disabled:opacity-50"
          >
            {scoring ? '评分中...' : '重算评分'}
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="btn-primary h-10 px-4 text-sm"
          >
            {showCreate ? '收起表单' : '新建卡片'}
          </button>
          </div>
        </div>
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="surface rounded-[1.5rem] p-5">
          <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-500">卡片名称</label>
              <input
                type="text"
                placeholder="例如：深度拆解型标题"
                value={newCard.name}
                onChange={(e) => setNewCard({ ...newCard, name: e.target.value })}
                className="control w-full px-3 text-sm placeholder:text-zinc-300"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-500">分类</label>
              <select
                value={newCard.category}
                onChange={(e) => setNewCard({ ...newCard, category: e.target.value })}
                className="control w-full px-3 text-sm"
              >
                {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="mt-4">
            <label className="mb-1.5 block text-xs font-medium text-zinc-500">卡片内容</label>
            <textarea
              placeholder="支持 Markdown，可写标题模板、案例拆解或风险规则。"
              value={newCard.content}
              onChange={(e) => setNewCard({ ...newCard, content: e.target.value })}
              rows={5}
              className="control min-h-[140px] w-full resize-none px-3 py-2 text-sm placeholder:text-zinc-300"
            />
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button
              onClick={() => setShowCreate(false)}
              className="btn-secondary h-10 px-4 text-sm"
            >
              取消
            </button>
            <button
              onClick={handleCreate}
              className="btn-primary h-10 px-4 text-sm"
            >
              创建
            </button>
          </div>
        </div>
      )}

      {/* Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-36 rounded-2xl border border-zinc-100 bg-white skeleton" />
          ))}
        </div>
      ) : cards.length === 0 ? (
        <div className="surface rounded-[1.75rem] px-6 py-16 text-center">
          <p className="text-base font-semibold text-zinc-900">资产库为空</p>
          <p className="mt-2 text-sm text-zinc-500">创建第一个资产卡片，开始积累可复用的内容知识。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cards.map((card) => (
            <div key={card.id} className="surface rounded-2xl p-4 transition-all hover:-translate-y-0.5 hover:border-zinc-300">
              <div className="flex items-start justify-between mb-2">
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700">
                  {CATEGORY_LABELS[card.category] || card.category}
                </span>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-zinc-300 font-mono">v{card.version}</span>
                  {card.score > 0 && (
                    <span className="text-[11px] font-mono text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded">
                      {card.score.toFixed(1)}
                    </span>
                  )}
                </div>
              </div>
              <h3 className="text-sm font-medium text-zinc-900 mb-1">{card.name}</h3>
              <p className="text-xs text-zinc-400 line-clamp-2">{card.content}</p>
              {card.tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {card.tags.map((tag, i) => (
                    <span key={i} className="text-[10px] text-zinc-300 bg-zinc-50 px-1.5 py-0.5 rounded">
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {card.usage_count > 0 && (
                <p className="text-[10px] text-zinc-300 mt-2 font-mono">使用 {card.usage_count} 次</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
