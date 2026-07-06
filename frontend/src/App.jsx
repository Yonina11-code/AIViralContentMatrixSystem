import { useEffect, useMemo, useState } from 'react'
import ContentPool from './components/ContentPool'
import Articles from './components/Articles'
import Assets from './components/Assets'
import Generate from './components/Generate'
import Domains from './components/Domains'
import Dashboard from './components/Dashboard'

const TABS = [
  { key: 'dashboard', label: '数据看板', short: '看板', hint: '阅读与发布表现' },
  { key: 'pool', label: '内容池', short: '内容', hint: '采集、筛选、清洗素材' },
  { key: 'domains', label: '领域管理', short: '领域', hint: '配置关键词与来源' },
  { key: 'articles', label: '文章管理', short: '文章', hint: '审核、发布、导出' },
  { key: 'assets', label: '内容资产', short: '资产', hint: '模板、规则、案例' },
  { key: 'generate', label: '一键生成', short: '生成', hint: '从素材到成稿' },
]

const panels = {
  dashboard: <Dashboard />,
  pool: <ContentPool />,
  domains: <Domains />,
  articles: <Articles />,
  assets: <Assets />,
  generate: <Generate />,
}

function readHashTab() {
  const key = window.location.hash.replace('#', '')
  return TABS.some(tab => tab.key === key) ? key : 'pool'
}

export default function App() {
  const [activeTab, setActiveTab] = useState(readHashTab)
  const activeMeta = useMemo(() => TABS.find(tab => tab.key === activeTab) || TABS[1], [activeTab])

  useEffect(() => {
    const handleHashChange = () => setActiveTab(readHashTab())
    window.addEventListener('hashchange', handleHashChange)
    window.addEventListener('popstate', handleHashChange)
    return () => {
      window.removeEventListener('hashchange', handleHashChange)
      window.removeEventListener('popstate', handleHashChange)
    }
  }, [])

  const selectTab = (key) => {
    setActiveTab(key)
    if (window.location.hash !== `#${key}`) {
      window.history.pushState(null, '', `#${key}`)
    }
  }

  return (
    <div className="min-h-[100dvh] bg-[#f6f7f8] text-zinc-900">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_18%_12%,rgba(37,99,235,0.08),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.72),rgba(246,247,248,0))]" />
      <div className="relative mx-auto flex min-h-[100dvh] w-full max-w-[1500px] flex-col lg:flex-row">
        <aside className="hidden w-[260px] shrink-0 border-r border-zinc-200/80 px-5 py-6 lg:block">
          <div className="sticky top-6">
            <div className="mb-8 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-zinc-950 text-sm font-semibold text-white shadow-[0_18px_35px_-22px_rgba(24,24,27,0.75)]">
                AI
              </div>
              <div>
                <p className="text-sm font-semibold tracking-tight text-zinc-950">AIViralContent</p>
                <p className="text-[11px] font-medium text-zinc-400">Matrix System</p>
              </div>
            </div>

            <nav className="space-y-1.5">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => selectTab(tab.key)}
                  className={`group flex w-full items-center justify-between rounded-2xl px-3 py-3 text-left transition-all active:scale-[0.99] ${
                    activeTab === tab.key
                      ? 'bg-white text-zinc-950 shadow-[0_18px_40px_-28px_rgba(24,24,27,0.45)] ring-1 ring-zinc-200/80'
                      : 'text-zinc-500 hover:bg-white/70 hover:text-zinc-900'
                  }`}
                >
                  <span>
                    <span className="block text-sm font-semibold">{tab.label}</span>
                    <span className="mt-0.5 block text-[11px] text-zinc-400">{tab.hint}</span>
                  </span>
                  <span className={`h-1.5 w-1.5 rounded-full transition-all ${
                    activeTab === tab.key ? 'bg-blue-600' : 'bg-zinc-300 opacity-0 group-hover:opacity-100'
                  }`} />
                </button>
              ))}
            </nav>

          </div>
        </aside>

        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-20 border-b border-zinc-200/80 bg-[#f6f7f8]/85 px-4 py-3 backdrop-blur-xl sm:px-6 lg:px-8">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <div className="flex items-center gap-3 lg:hidden">
                  <div className="flex h-9 w-9 items-center justify-center rounded-2xl bg-zinc-950 text-xs font-semibold text-white">AI</div>
                  <span className="text-sm font-semibold tracking-tight">AIViralContent</span>
                </div>
                <p className="mt-3 text-[11px] font-semibold text-zinc-400 lg:mt-0">Content Matrix</p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-950 sm:text-3xl">{activeMeta.label}</h1>
              </div>

              <div className="flex items-center gap-3 overflow-x-auto pb-1 lg:hidden">
                {TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => selectTab(tab.key)}
                    className={`shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition-all active:scale-[0.98] ${
                      activeTab === tab.key
                        ? 'bg-zinc-950 text-white shadow-[0_14px_30px_-22px_rgba(24,24,27,0.8)]'
                        : 'bg-white text-zinc-500 ring-1 ring-zinc-200/80'
                    }`}
                  >
                    {tab.short}
                  </button>
                ))}
              </div>

              <div className="hidden items-center gap-3 rounded-2xl border border-zinc-200/80 bg-white/70 px-4 py-3 xl:flex">
                <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.1)]" />
                <div>
                  <p className="text-xs font-semibold text-zinc-700">本地工作台</p>
                  <p className="text-[11px] text-zinc-400">v0.1.0 · API /api</p>
                </div>
              </div>
            </div>
          </header>

          <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <div className="animate-page-in">
              {panels[activeTab]}
            </div>
          </main>
        </div>
      </div>
    </div>
  )
}
