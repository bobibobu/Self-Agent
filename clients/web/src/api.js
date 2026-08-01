// Self-Agent 后端 API 客户端
// 后端地址：开发时通过 vite proxy (/api → localhost:8000)，生产可配
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

/**
 * 流式对话（SSE 传输）。
 *
 * 浏览器原生 EventSource 只支持 GET，但 /chat/stream 是 POST（带 body），
 * 所以用 fetch + ReadableStream 手动解析 SSE 文本流。
 *
 * @param {Object} params - { message, thread_id, user_id }
 * @param {Function} onEvent - 收到事件时的回调 (event) => void
 *   event 形如 { type: 'token'|'tool_calls'|'tool_start'|'tool_result'|'done'|'error', ... }
 * @returns {Promise<void>}
 */
export async function streamChat({ message, thread_id, user_id }, onEvent) {
  const resp = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id, user_id }),
  })

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 以双换行分隔事件块
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() // 最后一块可能不完整，留到下次

    for (const block of blocks) {
      const event = parseSSEBlock(block)
      if (event) onEvent(event)
    }
  }
  // 处理尾部残留
  if (buffer.trim()) {
    const event = parseSSEBlock(buffer)
    if (event) onEvent(event)
  }
}

/** 解析单个 SSE 事件块为 { type, ...data } */
function parseSSEBlock(block) {
  let eventType = 'message'
  let dataStr = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataStr += line.slice(5).trim()
    }
  }
  if (!dataStr) return null
  try {
    const data = JSON.parse(dataStr)
    return { type: eventType, ...data }
  } catch {
    return { type: eventType, raw: dataStr }
  }
}

/** 普通对话（非流式） */
export async function chat({ message, thread_id, user_id }) {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id, user_id }),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

/** 列出可用工具 */
export async function listTools() {
  const resp = await fetch(`${API_BASE}/tools`)
  return resp.json()
}

/** 健康检查 */
export async function health() {
  try {
    const resp = await fetch(`${API_BASE}/health`)
    return resp.json()
  } catch {
    return { status: 'error' }
  }
}

// ===== 会话管理 =====

/** 列出会话（按 user_id 过滤） */
export async function listSessions(userId) {
  const url = userId ? `${API_BASE}/sessions?user_id=${encodeURIComponent(userId)}` : `${API_BASE}/sessions`
  const resp = await fetch(url)
  return resp.json()
}

/** 新建会话 */
export async function createSession(userId, title = '新对话') {
  const url = userId
    ? `${API_BASE}/sessions?user_id=${encodeURIComponent(userId)}&title=${encodeURIComponent(title)}`
    : `${API_BASE}/sessions?title=${encodeURIComponent(title)}`
  const resp = await fetch(url, { method: 'POST' })
  return resp.json()
}

/** 重命名会话 */
export async function renameSession(threadId, title) {
  const resp = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(threadId)}?title=${encodeURIComponent(title)}`,
    { method: 'PATCH' },
  )
  return resp.json()
}

/** 删除会话 */
export async function deleteSession(threadId) {
  const resp = await fetch(`${API_BASE}/sessions/${encodeURIComponent(threadId)}`, { method: 'DELETE' })
  return resp.json()
}

/** 取消正在进行的流式生成 */
export async function cancelChat(threadId) {
  const resp = await fetch(`${API_BASE}/chat/cancel/${encodeURIComponent(threadId)}`, { method: 'POST' })
  return resp.json()
}
