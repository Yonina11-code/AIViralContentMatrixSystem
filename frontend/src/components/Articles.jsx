import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api/client'

function latestReviewTrace(article) {
  const trace = article?.agent_trace?.[3]
  if (!trace) return null
  return trace.second_review || trace.review || null
}

// 自动将封面图插入到 Markdown 最顶部
function insertCoverToMarkdown(markdownText, imageUrl) {
  if (!markdownText || !imageUrl) return markdownText
  if (markdownText.includes(imageUrl)) return markdownText
  
  return `![封面配图](${imageUrl})\n\n` + markdownText
}

// 自动寻找小标题并在其下方插入插图配图
function insertImageToMarkdown(markdownText, sectionTitle, imageUrl) {
  if (!markdownText || !sectionTitle || !imageUrl) return markdownText
  if (markdownText.includes(imageUrl)) return markdownText

  const imgMarkdown = `\n\n![插图](${imageUrl})\n\n`
  const escapedTitle = sectionTitle.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')
  const regex = new RegExp(`(#{1,6}\\s*\\*\\*?|\\*\\*?|##?\\s+)?${escapedTitle}(\\*\\*?)?`, 'i')

  const match = markdownText.match(regex)
  if (match) {
    const matchIndex = match.index + match[0].length
    const before = markdownText.substring(0, matchIndex)
    const after = markdownText.substring(matchIndex)
    return before + imgMarkdown + after
  }

  return markdownText + `\n\n${imgMarkdown}`
}

// 自动寻找小标题并在其下方插入插图占位符
function insertPromptPlaceholderToMarkdown(markdownText, sectionTitle, placeholder) {
  if (!markdownText || !sectionTitle || !placeholder) return markdownText
  if (markdownText.includes(placeholder)) return markdownText

  const escapedTitle = sectionTitle.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')
  const regex = new RegExp(`(#{1,6}\\s*\\*\\*?|\\*\\*?|##?\\s+)?${escapedTitle}(\\*\\*?)?`, 'i')

  const match = markdownText.match(regex)
  if (match) {
    const matchIndex = match.index + match[0].length
    const before = markdownText.substring(0, matchIndex)
    const after = markdownText.substring(matchIndex)
    return before + `\n\n${placeholder}\n\n` + after
  }

  return markdownText + `\n\n${placeholder}\n\n`
}

// 自动将封面图占位符插入到 Markdown 最顶端
function insertCoverPlaceholderToMarkdown(markdownText, placeholder) {
  if (!markdownText || !placeholder) return markdownText
  if (markdownText.includes(placeholder)) return markdownText
  return `${placeholder}\n\n` + markdownText
}

// 精准正则替换正文里的封面图占位符
function replaceCoverPlaceholder(markdownText, imageUrl) {
  const regex = /> \*\*\[待生成封面图 Prompt\]\*\*：[\s\S]*?(?=\n\n|$)/
  if (regex.test(markdownText)) {
    return markdownText.replace(regex, `![封面配图](${imageUrl})`)
  }
  return insertCoverToMarkdown(markdownText, imageUrl)
}

// 精准正则替换正文中第 index + 1 张插图占位符
function replaceIllustrationPlaceholder(markdownText, index, imageUrl, sectionTitle) {
  const regex = new RegExp(`> \\*\\*\\[待生成插图 ${index + 1} Prompt\\]\\*\\*：[\\s\\S]*?(?=\\n\\n|$)`)
  if (regex.test(markdownText)) {
    return markdownText.replace(regex, `![插图](${imageUrl})`)
  }
  return insertImageToMarkdown(markdownText, sectionTitle, imageUrl)
}

// 简易 Markdown 解析器，用于右侧微信排版所见即所得实时效果渲染
function renderMarkdownToHtml(markdownText) {
  if (!markdownText) return '';
  let html = markdownText;
  
  // 1. 转义 HTML 字符防注入
  html = html
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
    
  // 2. 解析图片语法 ![alt](url) -> 插入精美的微信卡片图片
  html = html.replace(/!\[(.*?)\]\((.*?)\)/g, (match, alt, url) => {
    return `
      <div class="my-4 text-center group relative w-full block">
        <img src="${url}" alt="${alt}" class="max-h-72 rounded-xl object-contain border border-zinc-200 shadow-sm mx-auto transition-transform duration-200 hover:scale-[1.01]" />
        <p class="text-[10px] text-zinc-400 mt-1.5">${alt || '配图'}</p>
      </div>
    `;
  });
  
  // 3. 解析标题 ###, ##, # -> 转换为微信公众号级别的段落标题样式
  html = html.replace(/^(#{1,6})\s+(.+)$/gm, (match, hashes, text) => {
    const level = hashes.length;
    const size = level === 1 ? '19px' : level === 2 ? '17px' : '15px';
    return `<p style="margin:28px 0 12px;padding-top:4px;font-size:${size};font-weight:700;color:#18181b;line-height:1.55;border-left:4px solid #3b82f6;padding-left:8px;">${text}</p>`;
  });
  
  // 4. 解析粗体 **text**
  html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

  // 5. 处理待生成提示行以弱化展示
  html = html.replace(/&gt;\s*\*\*\[待生成(?:封面图|插图\s+\d+)\s+Prompt\]\*\*(.+)$/gm, (match, body) => {
    return `<div style="background:#f4f4f5;border-left:3px solid #a1a1aa;padding:8px 12px;font-size:11px;color:#71717a;border-radius:4px;margin:12px 0;">[待生成占位] ${body}</div>`;
  });
  
  // 6. 解析段落
  const blocks = html.split(/\n\n+/);
  const formattedBlocks = blocks.map(block => {
    const stripped = block.trim();
    if (!stripped) return '';
    // 如果已经是图片、标题、待生成占位的块，不做多余段落包裹
    if (stripped.startsWith('<div') || stripped.startsWith('<p style="margin:28px') || stripped.startsWith('<blockquote') || stripped.startsWith('<hr')) {
      return stripped;
    }
    const textHtml = stripped.replace(/\n/g, '<br/>');
    return `<p style="margin:12px 0;line-height:1.88;font-size:14px;color:#3f3f46;">${textHtml}</p>`;
  });
  
  return formattedBlocks.join('\n');
}



// 兼容非安全上下文（非 HTTPS / 局域网 IP）的剪贴板复制兜底方案
function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text)
  }
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.style.position = 'fixed'
  textArea.style.top = '0'
  textArea.style.left = '0'
  textArea.style.opacity = '0'
  document.body.appendChild(textArea)
  textArea.focus()
  textArea.select()
  try {
    const successful = document.execCommand('copy')
    document.body.removeChild(textArea)
    return successful ? Promise.resolve() : Promise.reject(new Error('Fallback copy failed'))
  } catch (err) {
    document.body.removeChild(textArea)
    return Promise.reject(err)
  }
}

function PromptBlock({ title, prompt, tone = 'zinc', imageUrl = '', onUpload, onRemove }) {
  const [copied, setCopied] = useState(false)
  const [uploading, setUploading] = useState(false)

  const handleCopy = () => {
    if (!prompt) return
    copyToClipboard(prompt)
      .then(() => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1400)
      })
      .catch((err) => {
        console.error('复制失败', err)
        alert('复制失败，请手动选择复制')
      })
  }

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!onUpload) return
    setUploading(true)
    try {
      const res = await api.uploadImage(file)
      if (res.success && res.url) {
        await onUpload(res.url)
      } else {
        alert('配图上传失败')
      }
    } catch (err) {
      alert('配图上传失败: ' + err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className={`rounded-2xl border p-4 ${tone === 'blue' ? 'border-blue-100 bg-blue-50/60' : 'border-zinc-100 bg-zinc-50'}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className={`text-xs font-semibold ${tone === 'blue' ? 'text-blue-800' : 'text-zinc-700'}`}>{title}</span>
        <div className="flex items-center gap-2">
          {onUpload && (
            <label className="btn-secondary h-8 px-3 text-[11px] flex items-center justify-center cursor-pointer select-none">
              {uploading ? '上传中...' : '上传配图'}
              <input type="file" accept="image/*" onChange={handleFileChange} className="hidden" disabled={uploading} />
            </label>
          )}
          <button onClick={handleCopy} className="btn-secondary h-8 px-3 text-[11px]">
            {copied ? '已复制' : '复制'}
          </button>
        </div>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-zinc-700">{prompt}</p>

      {imageUrl && (
        <div className="mt-4 border-t border-zinc-100/60 pt-4 flex flex-col items-center">
          <div className="w-full flex items-center justify-between mb-2">
            <span className="text-[10px] text-zinc-400">已关联的 MJ 配图：</span>
            {onRemove && (
              <button 
                type="button"
                onClick={onRemove} 
                className="text-[10px] font-semibold text-red-600 hover:text-red-800 bg-red-50 hover:bg-red-100 px-2 py-1 rounded transition-colors border border-red-200/50"
              >
                删除配图
              </button>
            )}
          </div>
          <img 
            src={imageUrl} 
            alt={`${title}配图`} 
            className="max-h-72 rounded-xl object-contain border border-zinc-200/50 shadow-sm"
          />
        </div>
      )}
    </div>
  )
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

  // 编辑微调与 AI 润色状态
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editBody, setEditBody] = useState('')
  const [editSummary, setEditSummary] = useState('')
  const [saving, setSaving] = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)
  const [debugError, setDebugError] = useState(null)
  const [customInstruction, setCustomInstruction] = useState('')

  // 文本框高度自适应 Refs 与逻辑
  const bodyRef = useRef(null)
  const summaryRef = useRef(null)

  const adjustHeight = (el) => {
    if (!el) return
    el.style.height = 'auto'
    el.style.height = (el.scrollHeight + 4) + 'px'
  }

  useEffect(() => {
    if (isEditing) {
      // 延迟微调，确保 DOM 节点已完全渲染且原内容已就绪
      const timer = setTimeout(() => {
        if (bodyRef.current) adjustHeight(bodyRef.current)
        if (summaryRef.current) adjustHeight(summaryRef.current)
      }, 60)
      return () => clearTimeout(timer)
    }
  }, [editBody, editSummary, isEditing])

  const loadSuggestions = async (id, instruction = '') => {
    setLoadingSuggestions(true)
    setDebugError(null)
    try {
      const data = await api.getArticleSuggestions(id, instruction)
      setSuggestions(data.suggestions || [])
      if (data.debug_error) {
        setDebugError(data.debug_error)
      }
    } catch (err) {
      console.error('拉取AI优化建议失败', err)
      setDebugError(err.message)
    } finally {
      setLoadingSuggestions(false)
    }
  }

  const handleApplySuggestion = (sug) => {
    if (sug.type === 'title') {
      setEditTitle(sug.suggested_text)
      alert(`已将标题优化采纳为：「${sug.suggested_text}」`)
    } else if (sug.type === 'summary') {
      setEditSummary(sug.suggested_text)
      alert(`已将摘要优化采纳！`)
    } else if (sug.type === 'body_replace') {
      const original = sug.original_text
      const replacement = sug.suggested_text
      
      if (original && editBody.includes(original)) {
        setEditBody(prev => prev.replace(original, replacement))
        alert(`已采纳该段落优化润色！`)
      } else {
        // 若由于原文被改动导致无法完全匹配，智能追加到末尾
        setEditBody(prev => `${prev}\n\n> 提醒（采纳AI建议）：${replacement}`)
        alert(`已采纳该优化建议，由于没有在正文中匹配到精准原文，已作为金句框追加在正文末尾！`)
      }
    }
    // 采纳后移除该条建议
    setSuggestions(prev => prev.filter(x => x !== sug))
  }

  const handleBodyPaste = async (e) => {
    const clipboardData = e.clipboardData
    if (!clipboardData) return

    const items = clipboardData.items
    let imageFile = null

    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image') !== -1) {
        imageFile = items[i].getAsFile()
        break
      }
    }

    if (imageFile) {
      e.preventDefault()
      
      const textarea = e.target
      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      const text = textarea.value
      
      const placeholder = `\n\n![🎨 正在上传剪贴板插图...](uploading)\n\n`
      const newText = text.substring(0, start) + placeholder + text.substring(end)
      setEditBody(newText)
      
      try {
        const res = await api.uploadImage(imageFile)
        if (res.success && res.url) {
          const imgMarkdown = `\n\n![插图](${res.url})\n\n`
          const finalPostPasteText = text.substring(0, start) + imgMarkdown + text.substring(end)
          setEditBody(finalPostPasteText)
          
          setTimeout(() => {
            adjustHeight(textarea)
          }, 50)
        }
      } catch (err) {
        alert('上传图片失败: ' + err.message)
        setEditBody(text)
      }
    }
  }

  const handleStartEdit = async () => {
    setLoadingFull(true)
    setSuggestions([])
    setLoadingSuggestions(false)
    setCustomInstruction('')
    try {
      const data = await api.getArticle(selectedArticle.id)
      const art = data.article || data
      setEditTitle(art.title || '')
      
      // 优先从总编写作 trace 提取干净的 Markdown 原文以摆脱 HTML style 的污染
      let cleanMarkdown = art.agent_trace?.[1]?.body || art.body || ''
      
      // 健壮性兼容：若 cleanMarkdown 是未被成功解析的原始 JSON 字符串，尝试从中抽取真实的正文
      if (typeof cleanMarkdown === 'string') {
        const trimmed = cleanMarkdown.trim()
        if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
          try {
            const parsed = JSON.parse(trimmed)
            if (parsed && parsed.body) {
              cleanMarkdown = parsed.body
            }
          } catch (e) {
            // 若 JSON.parse 因不规范字符报错，尝试用正则精准提取
            const bodyMatch = trimmed.match(/"body"\s*:\s*"([\s\S]+?)"\s*(,\s*"summary"|})/);
            if (bodyMatch && bodyMatch[1]) {
              cleanMarkdown = bodyMatch[1]
                .replace(/\\n/g, '\n')
                .replace(/\\"/g, '"')
                .replace(/\\t/g, '\t')
            }
          }
        }
      }
      
      // 智能占位符生成与图片嵌入
      const imgs = art.agent_trace?.[2]
      if (imgs) {
        if (Array.isArray(imgs.illustrations)) {
          imgs.illustrations.forEach((ill, idx) => {
            if (ill.section_title) {
              if (ill.image_url) {
                cleanMarkdown = insertImageToMarkdown(cleanMarkdown, ill.section_title, ill.image_url)
              } else {
                const promptPlaceholder = `> **[待生成插图 ${idx + 1} Prompt]**：${ill.prompt || ''}`
                cleanMarkdown = insertPromptPlaceholderToMarkdown(cleanMarkdown, ill.section_title, promptPlaceholder)
              }
            }
          })
        }
        if (imgs.cover) {
          if (imgs.cover.image_url) {
            cleanMarkdown = insertCoverToMarkdown(cleanMarkdown, imgs.cover.image_url)
          } else {
            const coverPlaceholder = `> **[待生成封面图 Prompt]**：${imgs.cover.prompt || ''}`
            cleanMarkdown = insertCoverPlaceholderToMarkdown(cleanMarkdown, coverPlaceholder)
          }
        }
      }

      setFullArticle(art)
      setEditBody(cleanMarkdown)
      setEditSummary(art.summary || '')
      setIsEditing(true)
      
      // 异步加载大模型的 AI 优化建议
      loadSuggestions(selectedArticle.id)
    } catch (err) {
      alert('加载文章全文失败: ' + err.message)
    } finally {
      setLoadingFull(false)
    }
  }

  const handleSaveEdit = async () => {
    setSaving(true)
    try {
      await api.updateArticle(selectedArticle.id, {
        title: editTitle,
        body: editBody,
        summary: editSummary
      })
      setIsEditing(false)
      fetchArticles()
      setSelectedArticle(prev => ({
        ...prev,
        title: editTitle,
        summary: editSummary
      }))
    } catch (err) {
      alert('保存修改失败: ' + err.message)
    } finally {
      setSaving(false)
    }
  }

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
    setIsEditing(false)
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

  const refreshFullArticle = async () => {
    if (!selectedArticle) return
    try {
      const data = await api.getArticle(selectedArticle.id)
      setFullArticle(data.article || data)
    } catch (err) {
      console.error(err)
    }
  }

  const handleUploadCover = async (url) => {
    await api.saveIllustrationImage(selectedArticle.id, 'cover', url)
    if (isEditing) {
      const newMarkdown = replaceCoverPlaceholder(editBody, url)
      setEditBody(newMarkdown)
    } else {
      const currentMarkdown = fullArticle?.agent_trace?.[1]?.body || ''
      if (currentMarkdown) {
        const newMarkdown = replaceCoverPlaceholder(currentMarkdown, url)
        await api.updateArticle(selectedArticle.id, {
          title: fullArticle.title,
          summary: fullArticle.summary,
          body: newMarkdown
        })
      }
    }
    await refreshFullArticle()
  }

  const handleUploadIllustration = async (index, url) => {
    await api.saveIllustrationImage(selectedArticle.id, String(index), url)
    const imgs = fullArticle?.agent_trace?.[2] || selectedArticle?.agent_trace?.[2]
    const ill = imgs?.illustrations?.[index]
    if (isEditing) {
      if (ill && ill.section_title) {
        const newMarkdown = replaceIllustrationPlaceholder(editBody, index, url, ill.section_title)
        setEditBody(newMarkdown)
      }
    } else {
      const currentMarkdown = fullArticle?.agent_trace?.[1]?.body || ''
      if (currentMarkdown && ill && ill.section_title) {
        const newMarkdown = replaceIllustrationPlaceholder(currentMarkdown, index, url, ill.section_title)
        await api.updateArticle(selectedArticle.id, {
          title: fullArticle.title,
          summary: fullArticle.summary,
          body: newMarkdown
        })
      }
    }
    await refreshFullArticle()
  }

  const handleRemoveCover = async () => {
    await api.saveIllustrationImage(selectedArticle.id, 'cover', '')
    const imgs = fullArticle?.agent_trace?.[2] || selectedArticle?.agent_trace?.[2]
    const coverPrompt = imgs?.cover?.prompt || ''
    const coverPlaceholder = `> **[待生成封面图 Prompt]**：${coverPrompt}`

    if (isEditing) {
      const targetTag = `![封面配图](${imgs?.cover?.image_url})`
      let newMarkdown = editBody
      if (imgs?.cover?.image_url && editBody.includes(targetTag)) {
        newMarkdown = editBody.replace(targetTag, coverPlaceholder)
      } else {
        newMarkdown = insertCoverPlaceholderToMarkdown(editBody, coverPlaceholder)
      }
      setEditBody(newMarkdown)
    } else {
      const currentMarkdown = fullArticle?.agent_trace?.[1]?.body || ''
      if (currentMarkdown) {
        const targetTag = `![封面配图](${imgs?.cover?.image_url})`
        let newMarkdown = currentMarkdown
        if (imgs?.cover?.image_url && currentMarkdown.includes(targetTag)) {
          newMarkdown = currentMarkdown.replace(targetTag, coverPlaceholder)
        } else {
          newMarkdown = insertCoverPlaceholderToMarkdown(currentMarkdown, coverPlaceholder)
        }
        await api.updateArticle(selectedArticle.id, {
          title: fullArticle.title,
          summary: fullArticle.summary,
          body: newMarkdown
        })
      }
    }
    await refreshFullArticle()
  }

  const handleRemoveIllustration = async (index) => {
    await api.saveIllustrationImage(selectedArticle.id, String(index), '')
    const imgs = fullArticle?.agent_trace?.[2] || selectedArticle?.agent_trace?.[2]
    const ill = imgs?.illustrations?.[index]
    const promptPlaceholder = `> **[待生成插图 ${index + 1} Prompt]**：${ill?.prompt || ''}`

    if (isEditing) {
      const targetTag = `![插图](${ill?.image_url})`
      let newMarkdown = editBody
      if (ill?.image_url && editBody.includes(targetTag)) {
        newMarkdown = editBody.replace(targetTag, promptPlaceholder)
      } else {
        newMarkdown = insertPromptPlaceholderToMarkdown(editBody, ill?.section_title || '', promptPlaceholder)
      }
      setEditBody(newMarkdown)
    } else {
      const currentMarkdown = fullArticle?.agent_trace?.[1]?.body || ''
      if (currentMarkdown) {
        const targetTag = `![插图](${ill?.image_url})`
        let newMarkdown = currentMarkdown
        if (ill?.image_url && currentMarkdown.includes(targetTag)) {
          newMarkdown = currentMarkdown.replace(targetTag, promptPlaceholder)
        } else {
          newMarkdown = insertPromptPlaceholderToMarkdown(currentMarkdown, ill?.section_title || '', promptPlaceholder)
        }
        await api.updateArticle(selectedArticle.id, {
          title: fullArticle.title,
          summary: fullArticle.summary,
          body: newMarkdown
        })
      }
    }
    await refreshFullArticle()
  }



  // 已使用 PromptBlock 统一处理复制，移除旧 copyPrompt

  const promptText = (item) => item?.copy_prompt || item?.prompt || ''
  const selectedReview = reviewResult || latestReviewTrace(selectedArticle)

  // 全文编辑视图（独立宽展页面，完美解决狭窄侧边栏排版太小的问题）
  if (isEditing && selectedArticle) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-6">
        <button
          onClick={() => setIsEditing(false)}
          className="flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-600 mb-6 transition-colors group cursor-pointer"
        >
          <svg className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          返回列表
        </button>

        {/* 双栏所见即所得大布局 */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          
          {/* 左栏：编辑与 Prompt 卡片（占 7/12 宽度） */}
          <div className="lg:col-span-7 bg-white rounded-[1.5rem] p-6 sm:p-8 space-y-6 border border-zinc-200/50 shadow-sm">
          <div className="flex items-center justify-between pb-4 border-b border-zinc-100">
            <div>
              <h2 className="text-xl font-bold text-zinc-900">微调修改文章</h2>
              <p className="text-xs text-zinc-400 mt-1">您可以自由修改标题、摘要及正文内容。编辑区已自动过滤复杂的微信 HTML 排版样式。</p>
            </div>
            <span className="text-xs font-mono bg-zinc-100 text-zinc-500 px-2.5 py-1 rounded-lg">ID: {selectedArticle.id.slice(0, 8)}</span>
          </div>

          {/* AI 润色建议区域 */}
          {(loadingSuggestions || suggestions.length > 0) && (
            <div className="rounded-2xl border border-blue-100 bg-blue-50/50 p-4 transition-all">
              <div className="flex items-center justify-between mb-3 select-none">
                <span className="text-xs font-semibold text-blue-800 flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-full bg-blue-600 animate-pulse" />
                  ✨ AI 写作润色建议
                </span>
                <span className="text-[10px] text-zinc-400 font-medium">采纳建议后，将自动应用替换至下方的文本表单</span>
              </div>
              
              {loadingSuggestions ? (
                <div className="flex items-center gap-2 text-xs text-zinc-400 italic py-2">
                  <svg className="animate-spin h-3.5 w-3.5 text-blue-600" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  正在针对此文深度构思优化切入点...
                </div>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  {suggestions.map((sug, i) => (
                    <div key={i} className="bg-white border border-zinc-200/60 p-3 rounded-xl flex flex-col justify-between space-y-3 shadow-sm hover:shadow-md transition-shadow">
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[9px] font-semibold bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">
                            {sug.target_label || '局部润色'}
                          </span>
                          <span className="text-[10px] text-zinc-400"># {i+1}</span>
                        </div>
                        <p className="text-xs font-semibold text-zinc-800 leading-relaxed">{sug.description}</p>
                        <div className="text-[10px] text-zinc-400 space-y-1 bg-zinc-50 p-2 rounded-lg border border-zinc-100/50">
                          {sug.original_text && (
                            <p className="line-through truncate">原文: {sug.original_text}</p>
                          )}
                          <p className="text-blue-700 font-medium whitespace-pre-wrap">建议: {sug.suggested_text}</p>
                        </div>
                      </div>
                      <button
                        onClick={() => handleApplySuggestion(sug)}
                        className="w-full py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[11px] font-semibold transition-all active:scale-[0.96] cursor-pointer"
                      >
                        ✓ 一键采纳建议
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {debugError && (
                <div className="mt-3.5 text-[11px] text-red-600 font-medium bg-red-50 border border-red-100 rounded-xl p-3 flex items-start gap-2 select-none shadow-sm leading-relaxed">
                  <span className="text-xs shrink-0 mt-0.5">⚠️</span>
                  <div>
                    <span className="font-bold">AI 智能润色接口调用失败：</span>
                    <code className="bg-red-100/50 px-1 py-0.5 rounded font-mono text-[10px] break-all">{debugError}</code>
                    <p className="mt-1 text-zinc-500 font-normal">当前已动态感知文稿主题，为您自动生成了“动态自适应兜底建议”，您依然可以直接点击采纳。</p>
                  </div>
                </div>
              )}

              {/* 对话重写润色反馈入口 */}
              <div className="mt-4 pt-3.5 border-t border-blue-100/60 flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
                <input
                  type="text"
                  value={customInstruction}
                  onChange={e => setCustomInstruction(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !loadingSuggestions) {
                      loadSuggestions(selectedArticle.id, customInstruction)
                    }
                  }}
                  placeholder="💬 觉得建议不够贴心？在这里输入您的调教要求，让AI重构卡片（例如：换掉特效药这三个字，幽默风趣些）"
                  className="control flex-1 text-xs px-3.5 h-10 border-blue-200 focus:ring-blue-500/20 focus:border-blue-400 bg-white"
                />
                <button
                  onClick={() => loadSuggestions(selectedArticle.id, customInstruction)}
                  disabled={loadingSuggestions}
                  className="btn-primary text-[11px] h-10 px-5 font-bold shrink-0 cursor-pointer flex items-center justify-center gap-1.5"
                >
                  {loadingSuggestions ? (
                    <>
                      <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                      </svg>
                      构思中...
                    </>
                  ) : (
                    '💬 让AI重构建议'
                  )}
                </button>
              </div>
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-zinc-500 mb-1.5">文章标题</label>
              <input
                type="text"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                className="control w-full px-4 py-2.5 text-sm font-medium focus:ring-blue-500/10 focus:border-blue-300"
                placeholder="请输入文章标题..."
              />
            </div>
            
            <div>
              <label className="block text-xs font-bold text-zinc-500 mb-1.5">文章摘要</label>
              <textarea
                ref={summaryRef}
                value={editSummary}
                onChange={e => {
                  setEditSummary(e.target.value)
                  adjustHeight(e.target)
                }}
                className="control w-full p-4 text-xs min-h-[5rem] overflow-hidden focus:ring-blue-500/10 focus:border-blue-300 leading-relaxed"
                placeholder="请输入文章摘要..."
              />
            </div>
            
            <div>
              <label className="block text-xs font-bold text-zinc-500 mb-1.5">文章正文</label>
              <textarea
                ref={bodyRef}
                value={editBody}
                onChange={e => {
                  setEditBody(e.target.value)
                  adjustHeight(e.target)
                }}
                onPaste={handleBodyPaste}
                className="control w-full p-4 text-xs min-h-[25rem] overflow-hidden font-mono leading-relaxed focus:ring-blue-500/10 focus:border-blue-300"
                placeholder="在此修改您的 Markdown 正文..."
              />
            </div>

            {/* 插图 Prompts (微调修改状态下的配图归档与自动插入) */}
            {(() => {
              const imgs = fullArticle?.agent_trace?.[2] || selectedArticle?.agent_trace?.[2]
              if (!imgs || !imgs.cover) return null
              return (
                <div className="mt-8 border-t border-zinc-100 pt-6">
                  <h3 className="text-sm font-semibold text-zinc-900 mb-3">插图 Prompts 及其配图</h3>
                  <p className="text-xs text-zinc-400 mb-4">您可以直接在下方选择 MJ 生成好的配图上传，配图将全自动定位并实时插入到上方的“文章正文”输入框中；点击删除配图可一键还原为占位符。</p>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <PromptBlock
                      title="封面图 Prompt"
                      prompt={promptText(imgs.cover)}
                      tone="blue"
                      imageUrl={imgs.cover.image_url}
                      onUpload={handleUploadCover}
                      onRemove={handleRemoveCover}
                    />
                    {imgs.illustrations?.map((ill, i) => (
                      <PromptBlock
                        key={i}
                        title={`插图 ${i + 1}${ill.section_title ? `：${ill.section_title}` : ''}`}
                        prompt={promptText(ill)}
                        imageUrl={ill.image_url}
                        onUpload={(url) => handleUploadIllustration(i, url)}
                        onRemove={() => handleRemoveIllustration(i)}
                      />
                    ))}
                  </div>
                </div>
              )
            })()}
          </div>
          
          <div className="flex items-center gap-3 pt-4 border-t border-zinc-100 justify-end">
            <button onClick={() => setIsEditing(false)} className="btn-secondary px-6 h-10 text-xs font-medium cursor-pointer">
              取消修改
            </button>
            <button onClick={handleSaveEdit} disabled={saving} className="btn-primary px-8 h-10 text-xs font-bold cursor-pointer">
              {saving ? '正在保存修改...' : '确认并保存文章'}
            </button>
          </div>
          </div>

          {/* 右栏：微信排版效果实时所见即所得预览（占 5/12 宽度，Sticky 滚动吸顶） */}
          <div className="lg:col-span-5 lg:sticky lg:top-8 bg-zinc-50 border border-zinc-200/60 rounded-[1.5rem] p-6 space-y-4 shadow-sm min-h-[40rem] max-h-[85vh] overflow-y-auto flex flex-col">
            <div className="border-b border-zinc-200/80 pb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
                  <span className="w-2.5 h-2.5 bg-blue-500 rounded-full animate-pulse" />
                  所见即所得效果实时预览
                </h3>
                <p className="text-[10px] text-zinc-400 mt-1">编辑时实时查看最终微信文章样式与图片呈现</p>
              </div>
            </div>
            
            <div 
              className="flex-1 wechat-preview whitespace-pre-wrap break-words text-sm text-zinc-800 leading-relaxed font-sans overflow-y-auto pr-1"
              dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(editBody) }}
            />
          </div>

        </div>
      </div>
    )
  }

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
                <p className="text-xs text-zinc-400 mb-4">复制以下 prompt 到 Midjourney / DALL·E / Stable Diffusion 生成配图，并可以上传归档配图</p>
                <div className="space-y-3">
                  <PromptBlock
                    title="封面图 Prompt"
                    prompt={promptText(imgs.cover)}
                    tone="blue"
                    imageUrl={imgs.cover.image_url}
                    onUpload={handleUploadCover}
                  />
                  {imgs.illustrations?.map((ill, i) => (
                    <PromptBlock
                      key={i}
                      title={`插图 ${i + 1}${ill.section_title ? `：${ill.section_title}` : ''}`}
                      prompt={promptText(ill)}
                      imageUrl={ill.image_url}
                      onUpload={(url) => handleUploadIllustration(i, url)}
                    />
                  ))}
                </div>
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
                  onClick={handleStartEdit}
                  disabled={loadingFull}
                  className="btn-secondary h-11 w-full text-sm font-medium flex items-center justify-center gap-1.5 border-blue-200 text-blue-600 hover:bg-blue-50/70 cursor-pointer"
                >
                  ✍️ 微调修改
                </button>

                <button
                  onClick={handleShowFullArticle}
                  disabled={loadingFull}
                  className="btn-primary h-11 w-full text-sm disabled:opacity-50 cursor-pointer"
                >
                  {loadingFull ? '加载中...' : '文稿详情'}
                </button>

                <button
                  onClick={handleReview}
                  disabled={reviewing}
                  className="btn-secondary h-11 w-full text-sm disabled:opacity-50 cursor-pointer"
                >
                  {reviewing ? '校验中...' : '文稿校验'}
                </button>

                <button
                  onClick={handleExport}
                  disabled={exporting || selectedArticle.status === 'failed'}
                  className="btn-secondary h-11 w-full text-sm disabled:opacity-50 cursor-pointer"
                >
                  {exporting ? '导出中...' : '文稿下载'}
                </button>

                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="btn-danger mt-4 h-11 w-full text-sm disabled:opacity-50 cursor-pointer"
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
