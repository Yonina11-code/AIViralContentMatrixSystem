const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.text()
    throw new Error(`API Error: ${res.status} ${err}`)
  }
  return res.json()
}

export const api = {
  // Content Pool
  getContent: (params) => {
    const q = new URLSearchParams()
    if (params?.source) q.set('source', params.source)
    if (params?.domain) q.set('domain', params.domain)
    if (params?.keyword) q.set('keyword', params.keyword)
    if (params?.page) q.set('page', params.page)
    if (params?.page_size) q.set('page_size', params.page_size)
    return request(`/content?${q}`)
  },
  getContentItem: (id) => request(`/content/${id}`),
  getDomains: () => request('/content/domains'),
  triggerCollection: (source = 'all', domain = 'tech', limit = 20, keyword = '') => {
    const q = new URLSearchParams({ source, domain, limit })
    if (keyword) q.set('keyword', keyword)
    return request(`/content/collect?${q}`, { method: 'POST' })
  },
  getFoloStatus: () => request('/content/folo/status'),
  triggerFoloLogin: () => request('/content/folo/login', { method: 'POST' }),
  getCollectionStatus: (taskId) => request(`/content/collect/status/${taskId}`),

  deleteContent: (id) => request(`/content/${id}`, { method: 'DELETE' }),
  batchDeleteContent: (ids) => request('/content/batch-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  batchSaveContent: (items) => request('/content/batch-save', { method: 'POST', body: JSON.stringify({ items }) }),

  // Articles
  getArticles: (params) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.page) q.set('page', params.page)
    if (params?.page_size) q.set('page_size', params.page_size)
    return request(`/articles?${q}`)
  },
  getArticle: (id) => request(`/articles/${id}`),
  generateArticle: (params) =>
    request('/articles/generate', {
      method: 'POST',
      body: JSON.stringify({
        domain: params?.domain || 'tech',
        item_ids: params?.item_ids || null,
        focus: params?.focus || null,
      }),
    }),
  publishArticle: (id) => request(`/articles/${id}/publish`, { method: 'POST' }),
  generateIllustrations: (id) => request(`/articles/${id}/illustrations`, { method: 'POST' }),
  reviewArticle: (id) => request(`/articles/${id}/review`, { method: 'POST' }),
  deleteArticle: (id) => request(`/articles/${id}`, { method: 'DELETE' }),
  updateArticle: (id, data) => request(`/articles/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  getArticleSuggestions: (id, userInstruction = '') => {
    const q = new URLSearchParams()
    if (userInstruction) q.set('user_instruction', userInstruction)
    return request(`/articles/${id}/suggestions?${q}`)
  },
  uploadImage: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/articles/upload-image`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(`图片上传失败: ${res.status} ${err}`)
    }
    return res.json()
  },
  saveIllustrationImage: (id, type, imageUrl) =>
    request(`/articles/${id}/illustrations/upload`, {
      method: 'POST',
      body: JSON.stringify({ type, image_url: imageUrl }),
    }),

  // Stats & Dashboard
  getArticleStats: () => request('/articles/stats'),
  syncStats: (days = 7) => request(`/articles/sync-stats?days=${days}`, { method: 'POST' }),
  importStats: async (file) => {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${BASE}/articles/import-stats`, {
      method: 'POST',
      body: formData,
    })
    if (!res.ok) {
      const err = await res.text()
      throw new Error(`导入失败: ${res.status} ${err}`)
    }
    return res.json()
  },

  // 导出 Markdown（直接触发浏览器下载）
  exportArticle: async (id) => {
    const res = await fetch(`${BASE}/articles/${id}/export`, {
      headers: { 'Accept': 'text/markdown' },
    })
    if (!res.ok) throw new Error(`导出失败: ${res.status}`)
    const blob = await res.blob()
    const disposition = res.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename\*?=([^;]+)/)
    let fileName = `article-${id}.md`
    if (match) {
      // filename*=utf-8''xxx → 提取 xxx 并 URL 解码
      const raw = match[1].trim()
      if (raw.startsWith("utf-8''")) {
        fileName = decodeURIComponent(raw.slice(6))
      } else {
        fileName = raw.replace(/^"|"$/g, '')
      }
    }
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = fileName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  },

  // Assets
  getAssets: (params) => {
    const q = new URLSearchParams()
    if (params?.category) q.set('category', params.category)
    return request(`/assets/cards?${q}`)
  },
  getAsset: (id) => request(`/assets/cards/${id}`),
  createAsset: (data) => request('/assets/cards', { method: 'POST', body: JSON.stringify(data) }),
  updateAsset: (id, data) => request(`/assets/cards/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  getCombos: () => request('/assets/combos'),
  createCombo: (data) => request('/assets/combos', { method: 'POST', body: JSON.stringify(data) }),

  // Domain CRUD
  listDomainDetails: () => request('/domains'),
  getDomainDetail: (id) => request(`/domains/${id}`),
  createDomain: (data) => request('/domains', { method: 'POST', body: JSON.stringify(data) }),
  updateDomain: (id, data) => request(`/domains/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteDomain: (id) => request(`/domains/${id}`, { method: 'DELETE' }),

  // Health
  health: () => request('/health'),
}
