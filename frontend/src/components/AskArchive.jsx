import { useState, useRef, useEffect } from 'react'

const API_BASE = '/api'

const SUGGESTED = [
  'What was the biggest architectural decision in this repo?',
  'What code got built but abandoned — and why?',
  'How did the testing strategy evolve over time?',
  'Which part of the codebase changed the most dramatically?',
  'Were there any major rewrites or migrations?',
]

export default function AskArchive({ jobId, repoUrl }) {
  const [question, setQuestion] = useState('')
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history, loading])

  const ask = async (q) => {
    const text = (q || question).trim()
    if (!text || loading) return
    setQuestion('')
    setError(null)
    setHistory(h => [...h, { role: 'user', content: text }])
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/chat/${jobId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Error ${res.status}`)
      }
      const data = await res.json()
      setHistory(h => [...h, { role: 'assistant', content: data.answer }])
    } catch (err) {
      setError(err.message)
      setHistory(h => h.slice(0, -1))
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask()
    }
  }

  return (
    <div className="ask-archive">
      <div className="ask-header">
        <span className="ask-icon">⟡</span>
        <div>
          <h2 className="ask-title">Ask the Archive</h2>
          <p className="ask-subtitle">
            Ask anything about this repository's history. Every answer is grounded
            in the excavated findings — no invention, no guesswork.
          </p>
        </div>
      </div>

      {history.length === 0 && (
        <div className="suggestions">
          {SUGGESTED.map((s) => (
            <button key={s} className="suggestion-chip" onClick={() => ask(s)}>
              {s}
            </button>
          ))}
        </div>
      )}

      {history.length > 0 && (
        <div className="chat-history">
          {history.map((msg, i) => (
            <div key={i} className={`chat-msg chat-msg--${msg.role}`}>
              {msg.role === 'user' ? (
                <span className="chat-label">You</span>
              ) : (
                <span className="chat-label chat-label--archive">Archive</span>
              )}
              <p className="chat-content">{msg.content}</p>
            </div>
          ))}
          {loading && (
            <div className="chat-msg chat-msg--assistant">
              <span className="chat-label chat-label--archive">Archive</span>
              <p className="chat-content chat-thinking">Consulting the record…</p>
            </div>
          )}
          {error && (
            <div className="chat-error">{error}</div>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      <form
        className="ask-form"
        onSubmit={(e) => { e.preventDefault(); ask() }}
      >
        <textarea
          ref={inputRef}
          className="ask-input"
          placeholder="Ask about this repository's history…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKey}
          rows={2}
          disabled={loading}
        />
        <button
          type="submit"
          className="ask-submit"
          disabled={!question.trim() || loading}
        >
          {loading ? '…' : 'Ask'}
        </button>
      </form>
      <p className="ask-hint">Press Enter to send · Shift+Enter for new line</p>
    </div>
  )
}
