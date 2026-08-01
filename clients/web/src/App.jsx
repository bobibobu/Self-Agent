import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  streamChat, listTools, health,
  listSessions, createSession, deleteSession, renameSession, cancelChat,
} from './api.js'
import './App.css'

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState('')
  const [userId, setUserId] = useState('web-user')
  const [streaming, setStreaming] = useState(false)
  const [tools, setTools] = useState([])
  const [connected, setConnected] = useState(false)
  const [sessions, setSessions] = useState([])  // 会话列表
  const messagesEndRef = useRef(null)

  // 启动时：健康检查 + 加载工具 + 加载会话列表
  useEffect(() => {
    health().then((h) => setConnected(h.status === 'ok'))
    listTools().then((data) => setTools(data.tools || [])).catch(() => {})
    refreshSessions()
  }, [])

  // 切换用户时刷新会话列表
  useEffect(() => {
    refreshSessions()
  }, [userId])

  // 自动滚动
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function refreshSessions() {
    try {
      const data = await listSessions(userId)
      setSessions(data.sessions || [])
    } catch { /* 忽略 */ }
  }

  async function handleNewSession() {
    const session = await createSession(userId)
    setThreadId(session.thread_id)
    setMessages([])
    await refreshSessions()
  }

  async function handleSelectSession(tid) {
    setThreadId(tid)
    setMessages([])  // 切换会话（历史由后端 checkpointer 维持，前端只显示新一轮起）
    // 可选：从 /history/{tid} 加载历史消息显示（留给后续增强）
  }

  async function handleDeleteSession(tid, e) {
    e.stopPropagation()
    await deleteSession(tid)
    if (tid === threadId) {
      setThreadId('')
      setMessages([])
    }
    await refreshSessions()
  }

  async function handleRenameSession(tid) {
    const title = window.prompt('新会话名称：')
    if (title) {
      await renameSession(tid, title)
      await refreshSessions()
    }
  }

  async function handleCancel() {
    if (threadId) {
      await cancelChat(threadId)
      setStreaming(false)
    }
  }

  async function send() {
    if (!input.trim() || streaming) return
    let currentThread = threadId
    if (!currentThread) {
      // 没有会话则自动新建
      const session = await createSession(userId)
      currentThread = session.thread_id
      setThreadId(currentThread)
    }

    const userMsg = input.trim()
    setInput('')
    const assistantIdx = messages.length + 1
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: userMsg },
      { role: 'assistant', content: '', toolSteps: [], streaming: true },
    ])
    setStreaming(true)

    try {
      await streamChat(
        { message: userMsg, thread_id: currentThread, user_id: userId },
        (event) => {
          setMessages((prev) => {
            const next = [...prev]
            const msg = next[assistantIdx]
            if (!msg) return prev
            if (event.type === 'token') {
              msg.content += event.text || ''
            } else if (event.type === 'tool_start') {
              msg.toolSteps = [...(msg.toolSteps || []), { name: event.name, args: event.args, status: 'running' }]
            } else if (event.type === 'tool_result') {
              msg.toolSteps = (msg.toolSteps || []).map((s, i) =>
                i === msg.toolSteps.length - 1 ? { ...s, status: 'done', result: event.content } : s
              )
            } else if (event.type === 'done') {
              msg.streaming = false
              if (event.reply && !msg.content) msg.content = event.reply
            } else if (event.type === 'cancelled') {
              msg.streaming = false
              msg.content += '\n\n_(已中断)_'
            } else if (event.type === 'error') {
              msg.content += `\n\n⚠️ 错误：${event.message}`
              msg.streaming = false
            }
            return next
          })
        },
      )
      await refreshSessions()
    } catch (e) {
      setMessages((prev) => {
        const next = [...prev]
        if (next[assistantIdx]) {
          next[assistantIdx].content = `⚠️ 连接失败：${e.message}`
          next[assistantIdx].streaming = false
        }
        return next
      })
    } finally {
      setStreaming(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="logo"><span className="logo-icon">🤖</span> Self-Agent</div>
        <div className={`status ${connected ? 'online' : 'offline'}`}>
          <span className="dot"></span>{connected ? '已连接' : '未连接'}
        </div>

        <div className="field">
          <label>用户 ID</label>
          <input value={userId} onChange={(e) => setUserId(e.target.value)} />
        </div>

        <button className="btn-new" onClick={handleNewSession}>+ 新对话</button>

        {/* 会话列表 */}
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
                  <button className="icon-btn" onClick={(e) => { e.stopPropagation(); handleRenameSession(s.thread_id) }} title="重命名">✏️</button>
                  <button className="icon-btn" onClick={(e) => handleDeleteSession(s.thread_id, e)} title="删除">🗑️</button>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="tools-panel">
          <h3>工具 ({tools.length})</h3>
          <ul>
            {tools.map((t) => (
              <li key={t.name} title={t.description}>🔧 {t.name}</li>
            ))}
          </ul>
        </div>
      </aside>

      <main className="chat-area">
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <div className="empty-icon">💬</div>
              <p>{threadId ? '开始对话' : '点击「新对话」开始'}</p>
              <p className="hint">支持流式输出、工具调用、记忆增强、上下文续接</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              <div className="avatar">{msg.role === 'user' ? '👤' : '🤖'}</div>
              <div className="bubble">
                {msg.toolSteps && msg.toolSteps.length > 0 && (
                  <div className="tool-steps">
                    {msg.toolSteps.map((step, j) => (
                      <div key={j} className={`tool-step ${step.status}`}>
                        <span className="tool-icon">{step.status === 'running' ? '⏳' : '✓'}</span>
                        <span className="tool-name">{step.name}</span>
                        {step.result && <span className="tool-result">{step.result.slice(0, 60)}...</span>}
                      </div>
                    ))}
                  </div>
                )}
                {msg.content ? (
                  <div className="content"><ReactMarkdown>{msg.content}</ReactMarkdown></div>
                ) : msg.streaming ? (
                  <div className="content typing">思考中<span className="dots">...</span></div>
                ) : null}
                {msg.streaming && msg.content && <span className="cursor">▋</span>}
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
            placeholder={threadId ? '输入消息... (Enter 发送)' : '先点击新对话，或选择左侧会话'}
            rows="1"
            disabled={streaming}
          />
          {streaming ? (
            <button className="btn-stop" onClick={handleCancel} disabled={!threadId}>⏹ 停止</button>
          ) : (
            <button onClick={send} disabled={!input.trim()}>发送</button>
          )}
        </div>
      </main>
    </div>
  )
}
