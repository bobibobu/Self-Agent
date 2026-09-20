// Self-Agent 后端 API 客户端
// 后端地址：开发时通过 vite proxy (/api → localhost:8000)，生产可配
const API_BASE = import.meta.env.VITE_API_BASE || '/api'

// ===== Token 管理 =====

const TOKEN_KEY = 'selfagent_token'
const USER_KEY = 'selfagent_user'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export function isLoggedIn() {
  return !!getToken()
}

/** 构造带认证的 headers（有 token 就带 Authorization） */
function authHeaders(extra = {}) {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json', ...extra }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

// ===== 认证 =====

/** 从后端错误响应里取一条可读的提示。
 *  业务异常是 {error, message}，FastAPI 校验失败是 {detail: [...]}，两种都兜住。 */
function errorMessage(data, fallback) {
  if (typeof data?.message === 'string') return data.message
  if (typeof data?.detail === 'string') return data.detail
  if (Array.isArray(data?.detail) && data.detail.length) {
    return data.detail[0].msg || fallback
  }
  return fallback
}

/** 凭据必须走请求体：query string 会被 nginx / uvicorn 的访问日志原样记下来。 */
async function authRequest(path, body, fallbackError) {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(errorMessage(data, fallbackError))
  if (data.access_token) setAuth(data.access_token, data.user)
  return data
}

export async function register(username, password) {
  return authRequest('/auth/register', { username, password }, '注册失败')
}

export async function login(username, password) {
  return authRequest('/auth/login', { username, password }, '登录失败')
}

// ===== 对话 =====

/**
 * 流式对话（SSE 传输）。
 * 浏览器原生 EventSource 只支持 GET，但 /chat/stream 是 POST（带 body），
 * 所以用 fetch + ReadableStream 手动解析 SSE 文本流。
 */
export async function streamChat({ message, thread_id, kb_ids }, onEvent) {
  const resp = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message, thread_id, kb_ids }),
  })

  if (resp.status === 401) {
    clearAuth()
    throw new Error('登录已过期，请重新登录')
  }
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    // 关键：先把 CRLF / CR 归一成 LF 再切分。
    // SSE 规范允许 CRLF、CR、LF 三种行结束符，服务端（sse-starlette）用的是
    // CRLF——直接 split('\n\n') 对 '\r\n\r\n' 永远不匹配，
    // 结果是整个流被当成一块，所有 data 拼在一起 JSON.parse 失败，
    // 前端只收到一个空的 done 事件，页面上就是个空气泡。
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n|\r/g, '\n')

    const blocks = buffer.split('\n\n')
    buffer = blocks.pop()   // 最后一段可能不完整，留到下一轮

    for (const block of blocks) {
      const event = parseSSEBlock(block)
      if (event) onEvent(event)
    }
  }
  // 冲掉解码器与缓冲区里的残留
  buffer += decoder.decode().replace(/\r\n|\r/g, '\n')
  for (const block of buffer.split('\n\n')) {
    const event = parseSSEBlock(block)
    if (event) onEvent(event)
  }
}

/** 解析一个 SSE 事件块（已归一为 LF）。返回 null 表示该块无数据（如心跳注释）。 */
function parseSSEBlock(block) {
  if (!block.trim()) return null

  let eventType = 'message'
  const dataLines = []

  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue   // 空行与注释（sse-starlette 的 ping）
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    // 规范：冒号后若有一个空格则去掉，且**只去一个**——
    // 不能用 trim()，否则 JSON 里的前后空白语义会被改掉
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') eventType = value
    else if (field === 'data') dataLines.push(value)
  }

  if (!dataLines.length) return null
  const dataStr = dataLines.join('\n')   // 规范：多条 data 用换行拼接
  try {
    // payload 里自带 type 字段，让它覆盖 event: 行（两者本来就一致）
    return { type: eventType, ...JSON.parse(dataStr) }
  } catch {
    return { type: eventType, raw: dataStr }
  }
}

export async function chat({ message, thread_id, kb_ids }) {
  const resp = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message, thread_id, kb_ids }),
  })
  if (resp.status === 401) { clearAuth(); throw new Error('请重新登录') }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

export async function cancelChat(threadId) {
  const resp = await fetch(`${API_BASE}/chat/cancel/${encodeURIComponent(threadId)}`, {
    method: 'POST',
    headers: authHeaders(),
  })
  return resp.json()
}

/**
 * 审批决策回传：图从 approval_required 中断处续跑（SSE，事件格式同 streamChat）。
 * decision 支持 true/false、"approve"/"deny"、{"approved": bool, "reason": str}。
 */
export async function resumeChat({ thread_id, decision }, onEvent) {
  const resp = await fetch(`${API_BASE}/chat/resume`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ thread_id, decision }),
  })
  if (resp.status === 401) {
    clearAuth()
    throw new Error('登录已过期，请重新登录')
  }
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${await resp.text()}`)
  }
  // SSE 解析与 streamChat 相同
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const consume = (chunk) => {
    buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n|\r/g, '\n')
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop()
    for (const block of blocks) {
      const event = parseSSEBlock(block)
      if (event) onEvent(event)
    }
  }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    consume(value)
  }
  consume(decoder.decode())
}

// ===== 会话管理 =====

export async function listSessions() {
  const resp = await fetch(`${API_BASE}/sessions`, { headers: authHeaders() })
  if (resp.status === 401) { clearAuth(); throw new Error('请重新登录') }
  return resp.json()
}

export async function createSession(title = '新对话') {
  const resp = await fetch(`${API_BASE}/sessions?title=${encodeURIComponent(title)}`, {
    method: 'POST',
    headers: authHeaders(),
  })
  return resp.json()
}

export async function renameSession(threadId, title) {
  const resp = await fetch(
    `${API_BASE}/sessions/${encodeURIComponent(threadId)}?title=${encodeURIComponent(title)}`,
    { method: 'PATCH', headers: authHeaders() },
  )
  return resp.json()
}

export async function deleteSession(threadId) {
  const resp = await fetch(`${API_BASE}/sessions/${encodeURIComponent(threadId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  })
  return resp.json()
}

/**
 * 取某个会话的历史消息。
 *
 * 数据来自 MongoDB 的对话日志（每条记录 = 一轮问答），不是 checkpointer——
 * checkpointer 存的是给模型看的完整状态（含工具消息、系统提示），
 * 不适合直接渲染给用户。
 * 返回按时间正序的 {role, content} 列表，可直接塞进消息区。
 */
export async function getHistory(threadId, limit = 50) {
  const resp = await fetch(
    `${API_BASE}/history/${encodeURIComponent(threadId)}?limit=${limit}`,
    { headers: authHeaders() },
  )
  if (resp.status === 401) { clearAuth(); throw new Error('登录已过期，请重新登录') }
  if (!resp.ok) throw new Error(`加载历史失败：HTTP ${resp.status}`)
  const data = await resp.json()

  const messages = []
  for (const ev of data.events || []) {
    if (ev.user_message) messages.push({ role: 'user', content: ev.user_message })
    if (ev.agent_reply) messages.push({ role: 'assistant', content: ev.agent_reply })
  }
  return messages
}

// ===== 工具/健康 =====

export async function listTools() {
  const resp = await fetch(`${API_BASE}/tools`, { headers: authHeaders() })
  return resp.json()
}

export async function health() {
  try {
    const resp = await fetch(`${API_BASE}/health`)
    return resp.json()
  } catch {
    return { status: 'error' }
  }
}

// ===== 运行时配置（设置中心）=====

export async function getLlmConfig() {
  const resp = await fetch(`${API_BASE}/admin/llm-config`, { headers: authHeaders() })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json()
}

/** 在线替换 LLM 配置（不重启生效）。fields 只传要改的，key 传空串表示清除。 */
export async function updateLlmConfig(fields) {
  const resp = await fetch(`${API_BASE}/admin/llm-config`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(fields),
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(errorMessage(data, '保存失败'))
  return data
}
