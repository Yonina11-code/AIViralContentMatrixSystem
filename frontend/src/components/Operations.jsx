import { useEffect, useState } from 'react'
import { api } from '../api/client'

const TYPE_LABELS = {
  published_article: '已发布',
  scheduled_article: '预约发布',
  collection_job: '定时采集',
  background_job: '后台任务',
}

export default function Operations() {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.getOperationsCalendar()
      setEvents(data.events || [])
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const dated = events.filter(e => e.time)
  const jobs = events.filter(e => !e.time)

  return (
    <div className="space-y-6">
      <div className="surface rounded-[1.5rem] p-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Operations</p>
        <h2 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-950">运营日历</h2>
        <p className="mt-1 text-sm text-zinc-500">查看预约发布、已发布文章和后台定时采集任务。</p>
      </div>

      {loading ? (
        <div className="h-40 rounded-2xl border border-zinc-100 bg-white skeleton" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_0.75fr]">
          <section className="surface rounded-[1.5rem] p-5">
            <h3 className="mb-4 text-sm font-semibold text-zinc-900">发布时间线</h3>
            {dated.length === 0 ? (
              <p className="text-xs text-zinc-400">暂无发布或预约记录。</p>
            ) : (
              <div className="space-y-2">
                {dated.map(event => (
                  <div key={`${event.type}-${event.id}-${event.time}`} className="rounded-2xl border border-zinc-100 bg-zinc-50/60 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-zinc-900">{event.title}</p>
                        <p className="mt-1 text-xs text-zinc-400">{new Date(event.time).toLocaleString('zh-CN')}</p>
                      </div>
                      <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        event.type === 'scheduled_article' ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'
                      }`}>
                        {TYPE_LABELS[event.type] || event.type}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="surface rounded-[1.5rem] p-5">
            <h3 className="mb-4 text-sm font-semibold text-zinc-900">后台任务</h3>
            <div className="space-y-2">
              {jobs.map(job => (
                <div key={job.id} className="rounded-2xl border border-zinc-100 bg-zinc-50/60 p-4">
                  <p className="text-sm font-medium text-zinc-900">{job.title}</p>
                  <p className="mt-1 text-xs text-zinc-400">
                    {job.interval_seconds ? `每 ${Math.round(job.interval_seconds / 60)} 分钟` : '手动触发'}
                  </p>
                  <p className="mt-2 truncate font-mono text-[10px] text-zinc-300">{job.task}</p>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
