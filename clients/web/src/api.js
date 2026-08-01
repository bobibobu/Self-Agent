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

export async function register(username, password) {
  const resp = await fetch(`${API_BASE}/auth/register?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.message || '注册失败')
  if (data.access_token) setAuth(data.access_token, data.user)
  return data
}

export async function login(username, password) {
  const resp = await fetch(`${API_BASE}/auth/login?username=${encodeURIComponent(username)}&password=${encodeURIComponent(password)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.message || '登录失败')
  if (data.access_token) setAuth(data.access_token, data.user)
  return data
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
    buffer += decoder.decode(value, { stream: true })

    const blocks = buffer.split('\n\n')
    buffer = blocks.pop()

    for (const block of blocks) {
      const event = parseSSEBlock(block)
      if (event) onEvent(event)
    }
  }
  if (buffer.trim()) {
    const event = parseSSEBlock(buffer)
    if (event) onEvent(event)
  }
}

function parseSSEBlock(block) {
  let eventType = 'message'
  let dataStr = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) eventType = line.slice(6).trim()
    else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
  }
  if (!dataStr) return null
  try {
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
