import { useState, useRef, useEffect } from 'react'
import Ledger from './components/Ledger.jsx'

const API_BASE = '/api'
const LS_JOB_KEY = 'codicel_job_id'
const LS_RESULT_KEY = 'codicel_result'

export default function App() {
  const [repoUrl, setRepoUrl] = useState('')
  const [jobId, setJobId] = useState(null)
  const [progress, setProgress] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  // Restore a previous result from localStorage on first load
  useEffect(() => {
    const savedResult = localStorage.getItem(LS_RESULT_KEY)
    if (savedResult) {
      try {
        const parsed = JSON.parse(savedResult)
        setResult(parsed)
        setRepoUrl(parsed.repo_url || '')
      } catch {}
    }
  }, [])

  const startAnalysis = async (e) => {
    e.preventDefault()
    clearInterval(pollRef.current)
    setError(null)
    setResult(null)
    setProgress(null)
    setJobId(null)
    localStorage.removeItem(LS_JOB_KEY)
    localStorage.removeItem(LS_RESULT_KEY)
    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      })
      if (!res.ok) throw new Error(`Request failed: ${res.status}`)
      const data = await res.json()
      localStorage.setItem(LS_JOB_KEY, data.job_id)
      setJobId(data.job_id)
    } catch (err) {
      setError(err.message)
    }
  }

  const cancelAnalysis = async () => {
    if (!jobId) return
    clearInterval(pollRef.current)
    try {
      await fetch(`${API_BASE}/cancel/${jobId}`, { method: 'POST' })
    } catch {}
    setProgress(null)
    setJobId(null)
    localStorage.removeItem(LS_JOB_KEY)
  }

  useEffect(() => {
    if (!jobId) return
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/status/${jobId}`)
        if (res.status === 404) {
          clearInterval(pollRef.current)
          setError('Job not found — the server may have restarted. Try again.')
          return
        }
        const data = await res.json()
        setProgress(data)
        if (data.status === 'done') {
          clearInterval(pollRef.current)
          const r = await fetch(`${API_BASE}/result/${jobId}`)
          const resultData = await r.json()
          setResult(resultData)
          localStorage.setItem(LS_RESULT_KEY, JSON.stringify(resultData))
        } else if (data.status === 'error') {
          clearInterval(pollRef.current)
          setError(data.error || 'Analysis failed.')
        }
      } catch (err) {
        clearInterval(pollRef.current)
        setError(err.message)
      }
    }, 1200)
    return () => clearInterval(pollRef.current)
  }, [jobId])

  const isRunning = progress && progress.status !== 'done' && progress.status !== 'error'

  const clearResult = () => {
    setResult(null)
    setProgress(null)
    setError(null)
    setJobId(null)
    setRepoUrl('')
    localStorage.removeItem(LS_JOB_KEY)
    localStorage.removeItem(LS_RESULT_KEY)
  }

  return (
    <div className="app-shell">
      <header className="masthead">
        <h1 className="wordmark">Codicel</h1>
        <div className="tagline">an amended record of what this repository became, and why</div>
      </header>

      <form className="repo-form" onSubmit={startAnalysis}>
        <input
          type="text"
          placeholder="https://github.com/owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          required
          disabled={isRunning}
        />
        {isRunning ? (
          <button type="button" className="btn-cancel" onClick={cancelAnalysis}>
            Cancel
          </button>
        ) : (
          <button type="submit">
            Excavate
          </button>
        )}
      </form>

      {isRunning && (
        <div className="progress-block">
          {progress.step_label}
          <div className="progress-bar-track">
            <div className="progress-bar-fill" style={{ width: `${progress.percent}%` }} />
          </div>
        </div>
      )}

      {error && <div className="error-state">{error}</div>}

      {result && (
        <>
          <div className="stats-strip">
            <div><strong>{result.stats.commits_analyzed.toLocaleString()}</strong>commits read</div>
            <div><strong>{result.stats.prs_analyzed.toLocaleString()}</strong>PRs read</div>
            <div><strong>{result.stats.files_in_tree.toLocaleString()}</strong>files indexed</div>
            <div><strong>{result.stats.findings_count}</strong>findings surfaced</div>
            <button className="btn-new-excavation" onClick={clearResult}>↩ New excavation</button>
          </div>
          <Ledger findings={result.findings} repoUrl={result.repo_url} />
        </>
      )}

      {!isRunning && !result && !error && (
        <div className="empty-state">
          Paste a public GitHub repo above. Codicel reads its full commit history
          and works out what changed and why, along with any code that got left
          behind. Every claim links back to the commit that proves it.
        </div>
      )}
    </div>
  )
}
