import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  streamChat, listTools, health, getHistory,
  listSessions, createSession, deleteSession, renameSession, cancelChat, resumeChat,
  getLlmConfig, updateLlmConfig,
  isLoggedIn, getUser, clearAuth,
} from './api.js'
import Login from './Login.jsx'
import './App.css'

const SUGGESTIONS = [
  { icon: '🧠', title: '解释这个项目的架构', desc: '梳理模块划分与数据流', prompt: '帮我梳理当前工作区这个项目的整体架构：入口在哪、核心模块有哪些、数据怎么流动。用简洁的结构化方式回答。' },
  { icon: '🛠️', title: '写一个实用脚本', desc: '创建文件并演示工具调用', prompt: '在当前工作区创建 scripts/health_check.py，实现一个检查本服务 /health 端点的脚本，带超时与重试。写完简单说明用法。' },
  { icon: '📋', title: '制定重构计划', desc: '体验任务计划面板', prompt: '假设要把 tests 目录的测试按模块重新组织，先用 update_plan 制定一个分步计划，然后只执行第一步，其余留待确认。' },
  { icon: '🔍', title: '代码审查', desc: '读取文件并给出改进建议', prompt: '阅读 app/rag/service.py，从性能、错误处理、可维护性三个角度给出具体的改进建议，引用相关代码行。' },
]

const PLAN_ICON = { pending: '○', in_progress: '◐', completed: '●' }
const TOOL_ICON = { running: '⏳', done: '✓', denied: '✕' }

function briefArgs(args) {
  if (!args || typeof args !== 'object') return ''
  const vals = Object.values(args).map((v) => String(v))
  if (!vals.length) return ''
  return vals.join(' ').slice(0, 80)
}

function fmtDuration(ms) {
  if (ms == null) return ''
  return ms < 60_000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`
}

/** 桌面检测：pywebview 注入的 JS 桥是异步出现的，轮询到为止 */
function useDesktop() {
  const [desktop, setDesktop] = useState(!!window.pywebview)
  useEffect(() => {
    if (desktop) return
    const t = setInterval(() => {
      if (window.pywebview) { setDesktop(true); clearInterval(t) }
    }, 300)
    setTimeout(() => clearInterval(t), 10_000)
    return () => clearInterval(t)
  }, [])
  return desktop
}

function TitleBar({ title }) {
  const api = () => window.pywebview?.api
  return (
    <div className="titlebar">
      <div className="titlebar-brand">
        <span className="titlebar-logo">⚡</span>
        <span>{title}</span>
      </div>
      <div className="pywebview-drag-region titlebar-drag" />
      <div className="titlebar-controls">
        <button className="win-btn" title="最小化" onClick={() => api()?.minimize()}>─</button>
        <button className="win-btn" title="最大化/还原" onClick={() => api()?.maximizeToggle()}>☐</button>
        <button className="win-btn win-close" title="关闭" onClick={() => api()?.close()}>✕</button>
      </div>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(isLoggedIn())
  const desktop = useDesktop()

  // 免认证形态（桌面客户端 / AUTH_ENABLED=false）：后端经 /health 告知，
  // 直接放行——桌面模式不该让用户注册登录
  useEffect(() => {
    if (authed) return
    health().then((h) => {
      if (h.auth_enabled === false) setAuthed(true)
    }).catch(() => {})
  }, [])

  if (!authed) {
    return (
      <>
        {desktop && <TitleBar title="Self-Agent" />}
        <Login onAuthed={() => setAuthed(true)} />
      </>
    )
  }
  return <ChatApp onLogout={() => { clearAuth(); setAuthed(false) }} desktop={desktop} />
}

function ChatApp({ onLogout, desktop }) {
  const user = getUser()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [activeTool, setActiveTool] = useState('')
  const [tools, setTools] = useState([])
  const [connected, setConnected] = useState(false)
  const [serverInfo, setServerInfo] = useState({ storage: '', workspace: '', provider: '' })
  const [sessions, setSessions] = useState([])
  const [plan, setPlan] = useState(null)
  const [approval, setApproval] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [historyState, setHistoryState] = useState('idle')
  const [historyError, setHistoryError] = useState('')
  const messagesEndRef = useRef(null)

  // sqlite/memory 形态没有会话列表与历史日志（它们在 Postgres/Mongo 里）
  const localMode = ['sqlite', 'memory'].includes(serverInfo.storage)

  useEffect(() => {
    health().then((h) => {
      setConnected(h.status === 'ok')
      setServerInfo({
        storage: h.storage_backend || '',
        workspace: h.workspace_root || '',
        provider: h.default_provider || '',
      })
    })
    listTools().then((data) => setTools(data.tools || [])).catch(() => {})
    refreshSessions()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function refreshSessions() {
    try {
      const data = await listSessions()
      setSessions(data.sessions || [])
    } catch { /* 忽略（可能 401 / 本地无此 API） */ }
  }

  const localThreadId = () => `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`

  async function handleNewSession() {
    if (localMode) {
      setThreadId(localThreadId())
      setMessages([]); setPlan(null); setHistoryState('idle')
      return
    }
    const session = await createSession()
    setThreadId(session.thread_id)
    setMessages([]); setPlan(null); setHistoryState('idle')
    await refreshSessions()
  }

  async function handleSelectSession(tid) {
    if (tid === threadId || streaming) return
    setThreadId(tid)
    setMessages([]); setPlan(null)
    setHistoryState('loading')
    try {
      const past = await getHistory(tid)
      setMessages(past)
      setHistoryState(past.length ? 'ok' : 'empty')
    } catch (e) {
      setHistoryState('error')
      setHistoryError(e.message)
    }
  }

  async function handleDeleteSession(tid, e) {
    e.stopPropagation()
    await deleteSession(tid)
    if (tid === threadId) { setThreadId(''); setMessages([]) }
    await refreshSessions()
  }

  async function handleRenameSession(tid) {
    const title = window.prompt('新会话名称：')
    if (title) { await renameSession(tid, title); await refreshSessions() }
  }

  async function handleCancel() {
    if (threadId) { await cancelChat(threadId); setStreaming(false); setActiveTool('') }
  }

  const makeEventHandler = (updateLast) => (event) => {
    if (event.type === 'token') {
      updateLast((m) => ({ ...m, content: m.content + (event.text || '') }))
    } else if (event.type === 'tool_calls') {
      updateLast((m) => ({
        ...m,
        toolSteps: [
          ...(m.toolSteps || []),
          ...(event.calls || []).map((c) => ({ name: c.name, args: c.args || {}, status: 'running' })),
        ],
      }))
    } else if (event.type === 'tool_start') {
      setActiveTool(event.name || '')
      updateLast((m) => {
        const steps = m.toolSteps || []
        const idx = steps.findIndex((s) => s.name === event.name && s.status === 'running' && !s.started)
        if (idx >= 0) {
          return { ...m, toolSteps: steps.map((s, i) => (i === idx ? { ...s, started: true, args: event.args || s.args } : s)) }
        }
        if (steps.some((s) => s.name === event.name && s.status === 'running')) return m
        return { ...m, toolSteps: [...steps, { name: event.name, args: event.args, status: 'running', started: true }] }
      })
    } else if (event.type === 'tool_result') {
      setActiveTool('')
      updateLast((m) => {
        const steps = m.toolSteps || []
        const idx = steps.map((s) => s.status).lastIndexOf('running')
        if (idx < 0) return m
        return {
          ...m,
          toolSteps: steps.map((s, i) => (i === idx ? { ...s, status: 'done', result: event.content } : s)),
        }
      })
    } else if (event.type === 'tool_denied') {
      updateLast((m) => {
        const steps = m.toolSteps || []
        const idx = steps.map((s) => s.status).lastIndexOf('running')
        if (idx < 0) return m
        return {
          ...m,
          toolSteps: steps.map((s, i) => (i === idx ? { ...s, status: 'denied', result: event.reason } : s)),
        }
      })
    } else if (event.type === 'plan_updated') {
      setPlan(event.plan || null)
    } else if (event.type === 'approval_required') {
      setApproval({
        tool: event.tool,
        risk: event.risk,
        args: event.args,
        thread_id: event.thread_id || threadId,
      })
      setActiveTool('')
      updateLast((m) => ({ ...m, streaming: false }))
    } else if (event.type === 'done') {
      setActiveTool('')
      updateLast((m) => ({
        ...m,
        streaming: false,
        content: m.content || event.reply || '',
        elapsed: m.startedAt ? Date.now() - m.startedAt : null,
      }))
    } else if (event.type === 'cancelled') {
      setActiveTool('')
      updateLast((m) => ({ ...m, streaming: false, content: m.content + '\n\n_(已中断)_' }))
    } else if (event.type === 'error') {
      setActiveTool('')
      updateLast((m) => ({ ...m, streaming: false, content: m.content + `\n\n⚠️ ${event.message}` }))
    }
  }

  async function runTurn(streamFn) {
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', toolSteps: [], streaming: true, startedAt: Date.now() },
    ])
    setStreaming(true)
    const updateLast = (fn) => setMessages((prev) => {
      if (!prev.length) return prev
      const last = prev[prev.length - 1]
      if (last.role !== 'assistant') return prev
      return [...prev.slice(0, -1), fn(last)]
    })
    try {
      await streamFn(makeEventHandler(updateLast))
    } catch (e) {
      if (e.message.includes('登录')) { onLogout(); return }
      updateLast((m) => ({ ...m, streaming: false, content: `⚠️ ${e.message}` }))
    } finally {
      setStreaming(false)
      setActiveTool('')
    }
  }

  function send(promptText) {
    const userMsg = (promptText ?? input).trim()
    if (!userMsg || streaming) return
    let currentThread = threadId
    if (!currentThread) {
      currentThread = localMode ? localThreadId() : localThreadId()
      setThreadId(currentThread)
    }
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }])
    runTurn((onEvent) => streamChat({ message: userMsg, thread_id: currentThread }, onEvent))
      .then(() => { if (!localMode) refreshSessions() })
  }

  async function handleDecision(approved) {
    const current = approval
    setApproval(null)
    if (!current) return
    await runTurn((onEvent) =>
      resumeChat(
        { thread_id: current.thread_id, decision: { approved, reason: approved ? '' : '用户拒绝' } },
        onEvent,
      ),
    )
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  function copyMessage(i) {
    const m = messages[i]
    if (m?.content) navigator.clipboard?.writeText(m.content)
  }

  const planDone = plan?.filter((s) => s.status === 'completed').length ?? 0

  return (
    <div className="app">
      {desktop && <TitleBar title="Self-Agent" />}
      <div className="app-body">
        <aside className="sidebar">
          <div className="logo"><span className="logo-icon">⚡</span> Self-Agent</div>
          <div className={`status ${connected ? 'online' : 'offline'}`}>
            <span className="dot"></span>{connected ? '已连接' : '未连接'}
            {serverInfo.provider && <span style={{ marginLeft: 'auto', fontFamily: 'var(--mono)', fontSize: 11 }}>{serverInfo.provider}</span>}
          </div>

          {serverInfo.workspace && (
            <div className="workspace-box" title={serverInfo.workspace}>
              <span className="workspace-label">Workspace</span>
              <span className="workspace-path">{serverInfo.workspace.split(/[\\/]/).pop()}</span>
            </div>
          )}

          <button className="btn-new" onClick={handleNewSession}>＋ 新对话</button>

          {!localMode && (
            <div className="sessions-list">
              <h3>会话 ({sessions.length})</h3>
              <ul>
                {sessions.map((s) => (
                  <li
                    key={s.thread_id}
                    className={`session-item ${s.thread_id === threadId ? 'active' : ''}`}
                    onClick={() => handleSelectSession(s.thread_id)}
                  >
                    <span className="session-title">{s.title || s.thread_id.slice(0, 12)}</span>
                    <span className="session-actions">
                      <button className="icon-btn" onClick={(e) => { e.stopPropagation(); handleRenameSession(s.thread_id) }}>✏️</button>
                      <button className="icon-btn" onClick={(e) => handleDeleteSession(s.thread_id, e)}>🗑️</button>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {localMode && (
            <div className="local-hint">
              本地模式：对话状态存在本机 SQLite，无需登录。换工作区请重新启动客户端。
            </div>
          )}

          {plan && plan.length > 0 && (
            <div className="plan-panel">
              <h3>任务计划 · {planDone}/{plan.length}</h3>
              <ul>
                {plan.map((s) => (
                  <li key={s.id} className={`plan-item ${s.status}`}>
                    <span className="plan-icon">{PLAN_ICON[s.status] || '○'}</span>
                    <span className="plan-content">{s.content}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="sidebar-footer">
            <button className="side-btn" onClick={() => setShowSettings(true)}>
              ⚙️ <span>设置</span>
            </button>
            <button className="side-btn" onClick={() => setShowTools(true)}>
              🧰 <span>工具 ({tools.length})</span>
            </button>
            {user?.username ? (
              <button className="side-btn" onClick={onLogout}>
                👤 <span>{user.username} · 退出</span>
              </button>
            ) : (
              <div className="side-btn static">🏠 本地模式</div>
            )}
          </div>
        </aside>

        <main className="chat-area">
          <div className="messages">
            {historyState === 'loading' && (
              <div className="empty"><div className="empty-icon">⏳</div><p>正在加载历史消息…</p></div>
            )}
            {historyState === 'error' && (
              <div className="empty">
                <div className="empty-icon">⚠️</div>
                <p>历史消息加载失败</p>
                <p className="hint">{historyError}</p>
                <p className="hint">历史来自 MongoDB 对话日志，请确认它已启动</p>
              </div>
            )}
            {messages.length === 0 && historyState !== 'loading' && historyState !== 'error' && (
              <div className="empty">
                <div className="empty-icon">⚡</div>
                <h2>有什么可以帮你的？</h2>
                <p className="hint">
                  {serverInfo.workspace
                    ? <>工作区 <b style={{ color: 'var(--text-2)' }}>{serverInfo.workspace.split(/[\\/]/).pop()}</b> · 写文件/执行命令前会请求确认</>
                    : '流式输出 · 工具调用 · 记忆增强 · 上下文续接'}
                </p>
                <div className="suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button key={s.title} className="suggestion" onClick={() => send(s.prompt)}>
                      <div className="s-icon">{s.icon}</div>
                      <div className="s-title">{s.title}</div>
                      <div className="s-desc">{s.desc}</div>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((msg, i) => (
              <div key={i} className={`message ${msg.role}`}>
                <div className="avatar">{msg.role === 'user' ? '👤' : '⚡'}</div>
                <div className="bubble">
                  {msg.toolSteps && msg.toolSteps.length > 0 && (
                    <div className="tool-steps">
                      {msg.toolSteps.map((step, j) => (
                        <details key={j} className={`tool-step ${step.status}`} open={step.status === 'running'}>
                          <summary>
                            <span className="tool-icon">{step.status === 'running' ? '⏳' : TOOL_ICON[step.status] || '✓'}</span>
                            <span className="tool-name">{step.name}</span>
                            <span className="tool-brief">{step.status === 'denied' ? (step.result || '已拒绝') : briefArgs(step.args)}</span>
                          </summary>
                          {(step.args || step.result) && (
                            <div className="tool-detail">
                              {step.args && <pre>{JSON.stringify(step.args, null, 2)}</pre>}
                              {step.result && <pre>{step.result}</pre>}
                            </div>
                          )}
                        </details>
                      ))}
                    </div>
                  )}
                  {msg.content ? (
                    <div className="content"><ReactMarkdown>{msg.content}</ReactMarkdown></div>
                  ) : msg.streaming ? (
                    <div className="content typing">
                      {activeTool ? <>正在执行 <b style={{ fontFamily: 'var(--mono)' }}>{activeTool}</b></> : '思考中'}<span className="dots">...</span>
                    </div>
                  ) : null}
                  {msg.streaming && msg.content && <span className="cursor">▋</span>}
                  {!msg.streaming && msg.role === 'assistant' && msg.content && (
                    <div className="msg-meta">
                      {msg.elapsed != null && <span>{fmtDuration(msg.elapsed)}</span>}
                      <button onClick={() => copyMessage(i)}>复制</button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className="input-area">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={streaming ? 'Agent 工作中…' : '描述任务，Enter 发送，Shift+Enter 换行'}
              rows="1"
              disabled={streaming}
            />
            {streaming ? (
              <button className="btn-stop" onClick={handleCancel} disabled={!threadId}>■ 停止</button>
            ) : (
              <button onClick={() => send()} disabled={!input.trim()}>发送 ↵</button>
            )}
          </div>
        </main>
      </div>

      {approval && (
        <div className="modal-mask">
          <div className="approval-modal">
            <h3>⚠️ 需要你的确认</h3>
            <div className="approval-meta">
              <p><b>工具</b><span style={{ fontFamily: 'var(--mono)' }}>{approval.tool}</span></p>
              <p><b>风险</b><span className={`risk risk-${approval.risk}`}>{approval.risk}</span></p>
            </div>
            <pre className="approval-args">{JSON.stringify(approval.args, null, 2)}</pre>
            <p className="approval-hint">默认拒绝。允许前请确认你理解它将做什么。</p>
            <div className="approval-actions">
              <button className="btn-deny" onClick={() => handleDecision(false)}>拒绝</button>
              <button className="btn-approve" onClick={() => handleDecision(true)}>允许执行</button>
            </div>
          </div>
        </div>
      )}

      {showSettings && (
        <SettingsModal onClose={() => setShowSettings(false)} serverInfo={serverInfo} />
      )}
      {showTools && (
        <div className="modal-mask" onClick={() => setShowTools(false)}>
          <div className="modal tools-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>🧰 可用工具（{tools.length}）</h3>
              <button className="icon-btn" onClick={() => setShowTools(false)}>✕</button>
            </div>
            <div className="tools-grid">
              {tools.map((t) => (
                <div key={t.name} className="tool-card">
                  <div className="tool-card-head">
                    <span className="tool-card-name">{t.name}</span>
                    <span className={`risk risk-${t.risk}`}>{t.risk}</span>
                  </div>
                  <div className="tool-card-desc">{(t.description || '').slice(0, 120)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SettingsModal({ onClose, serverInfo }) {
  const [cfg, setCfg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)  // {ok, text}
  const [form, setForm] = useState({
    glm_api_key: '', openai_api_key: '', anthropic_api_key: '',
    llm_default_provider: null, glm_model: null, openai_model: null, anthropic_model: null,
  })

  useEffect(() => {
    getLlmConfig().then((d) => {
      setCfg(d)
      setForm((f) => ({ ...f, llm_default_provider: d.llm_default_provider }))
    }).catch((e) => setMessage({ ok: false, text: `加载失败：${e.message}` }))
  }, [])

  async function save() {
    setSaving(true); setMessage(null)
    const fields = { persist: true }
    // key 输入框留空 = 不改；填了才提交
    for (const k of ['glm_api_key', 'openai_api_key', 'anthropic_api_key']) {
      if (form[k]) fields[k] = form[k]
    }
    if (form.llm_default_provider) fields.llm_default_provider = form.llm_default_provider
    for (const k of ['glm_model', 'openai_model', 'anthropic_model']) {
      if (form[k] != null) fields[k] = form[k]
    }
    try {
      const d = await updateLlmConfig(fields)
      setMessage({
        ok: !d.config.embedding_reindex_required,
        text: d.config.embedding_reindex_required
          ? '已保存并立即生效。⚠️ embedding 维度已变化，已入库向量需重启重建并重新 ingest。'
          : '已保存并立即生效（无需重启）。',
      })
      // 清空 key 输入框，刷新打码状态
      setForm((f) => ({ ...f, glm_api_key: '', openai_api_key: '', anthropic_api_key: '' }))
      const fresh = await getLlmConfig()
      setCfg(fresh)
    } catch (e) {
      setMessage({ ok: false, text: e.message })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal settings-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>⚙️ 设置</h3>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        {!cfg ? (
          <p className="settings-loading">加载中…</p>
        ) : (
          <>
            <section className="settings-section">
              <h4>模型服务（改完点保存，立即生效，无需重启）</h4>
              <label className="field">
                <span>默认 Provider</span>
                <select
                  value={form.llm_default_provider || ''}
                  onChange={(e) => setForm({ ...form, llm_default_provider: e.target.value })}
                >
                  <option value="glm">GLM（智谱）</option>
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                </select>
              </label>

              {[
                { key: 'glm', label: 'GLM API Key', masked: cfg.glm_api_key_masked, modelKey: 'glm_model', model: cfg.glm_model },
                { key: 'openai', label: 'OpenAI API Key', masked: cfg.openai_api_key_masked, modelKey: 'openai_model', model: cfg.openai_model },
                { key: 'anthropic', label: 'Anthropic API Key', masked: cfg.anthropic_api_key_masked, modelKey: 'anthropic_model', model: cfg.anthropic_model },
              ].map((row) => (
                <div key={row.key} className="field-row">
                  <label className="field">
                    <span>{row.label} <em className="masked">{row.masked || '未配置'}</em></span>
                    <input
                      type="password"
                      placeholder="粘贴新 Key（留空 = 不修改）"
                      value={form[row.key]}
                      onChange={(e) => setForm({ ...form, [row.key]: e.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>模型</span>
                    <input
                      placeholder={row.model}
                      value={form[row.modelKey] ?? ''}
                      onChange={(e) => setForm({ ...form, [row.modelKey]: e.target.value })}
                    />
                  </label>
                </div>
              ))}
            </section>

            <section className="settings-section">
              <h4>关于</h4>
              <div className="about-grid">
                <div><em>工作区</em>{serverInfo.workspace || '—'}</div>
                <div><em>存储</em>{serverInfo.storage || '—'}</div>
                <div><em>embedding</em>{cfg.embedding_provider === 'none(哈希伪向量)' ? '未配置（降级）' : `${cfg.embedding_provider} / ${cfg.embedding_model}`}</div>
                <div><em>版本</em>Self-Agent</div>
              </div>
              <p className="settings-tip">
                embedding 未配置时语义检索为降级模式；在上方填入带 embedding 资源包的 key
                并保存即可开启（需重启重建向量索引）。
              </p>
            </section>

            {message && (
              <p className={`settings-msg ${message.ok ? 'ok' : 'err'}`}>{message.text}</p>
            )}
            <div className="approval-actions">
              <button className="btn-deny" onClick={onClose}>关闭</button>
              <button className="btn-approve" onClick={save} disabled={saving}>{saving ? '保存中…' : '保存并生效'}</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
