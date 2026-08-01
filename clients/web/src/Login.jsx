import { useState } from 'react'
import { login, register } from './api.js'

export default function Login({ onAuthed }) {
  const [mode, setMode] = useState('login')  // login | register
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setError('请填写用户名和密码')
      return
    }
    setError('')
    setLoading(true)
    try {
      const fn = mode === 'login' ? login : register
      await fn(username.trim(), password)
      onAuthed()
    } catch (err) {
      setError(err.message || (mode === 'login' ? '登录失败' : '注册失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo">
          <span className="logo-icon">🤖</span> Self-Agent
        </div>
        <p className="login-subtitle">企业级 AI Agent</p>

        <div className="login-tabs">
          <button
            className={mode === 'login' ? 'active' : ''}
            onClick={() => { setMode('login'); setError('') }}
          >登录</button>
          <button
            className={mode === 'register' ? 'active' : ''}
            onClick={() => { setMode('register'); setError('') }}
          >注册</button>
        </div>

        <form onSubmit={submit} className="login-form">
          <input
            type="text"
            placeholder="用户名"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
          />
          <input
            type="password"
            placeholder="密码（至少 6 位）"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />
          {error && <div className="login-error">{error}</div>}
          <button type="submit" disabled={loading}>
            {loading ? '处理中...' : (mode === 'login' ? '登录' : '注册')}
          </button>
        </form>

        <p className="login-hint">
          {mode === 'login' ? '没有账号？' : '已有账号？'}
          <a onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
            {mode === 'login' ? '去注册' : '去登录'}
          </a>
        </p>
      </div>
    </div>
  )
}
