import { useState, useRef, useEffect } from 'react'
import Ledger from './components/Ledger.jsx'

const API_BASE = '/api'

export default function App() {
  const [repoUrl, setRepoUrl] = useState('')
  const [jobId, setJobId] = useState(null)
  const [progress, setProgress] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const startAnalysis = async (e) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    setProgress(null)
    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
      })
      if (!res.ok) throw new Error(`Request failed: ${res.status}`)
      const data = await res.json()
      setJobId(data.job_id)
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    if (!jobId) return
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/status/${jobId}`)
        const data = await res.json()
        setProgress(data)
        if (data.status === 'done') {
          clearInterval(pollRef.current)
          const r = await fetch(`${API_BASE}/result/${jobId}`)
          setResult(await r.json())
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
        />
        <button type="submit" disabled={progress && progress.status !== 'done' && progress.status !== 'error'}>
          Excavate
        </button>
      </form>

      {progress && progress.status !== 'done' && (
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
            <div><strong>{result.stats.commits_analyzed}</strong>commits read</div>
            <div><strong>{result.stats.prs_analyzed}</strong>PRs read</div>
            <div><strong>{result.stats.findings_count}</strong>findings surfaced</div>
          </div>
          <Ledger findings={result.findings} repoUrl={result.repo_url} />
        </>
      )}

      {!progress && !result && !error && (
        <div className="empty-state">
          Paste a public GitHub repo above. Codicel reads its full commit history
          and works out what changed and why, along with any code that got left
          behind. Every claim links back to the commit that proves it.
        </div>
      )}
    </div>
  )
}
