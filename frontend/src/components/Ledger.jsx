import { useState } from 'react'
import EvidenceStamp from './EvidenceStamp.jsx'

const TYPE_LABELS = {
  era: 'Architectural decision',
  dead_code: 'Abandoned code',
  hidden_api: 'Hidden / undocumented API',
  abandoned_feature: 'Abandoned feature',
}

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'era', label: 'Decisions' },
  { key: 'dead_code', label: 'Dead code' },
]

export default function Ledger({ findings, repoUrl }) {
  const [filter, setFilter] = useState('all')

  if (!findings.length) {
    return (
      <div className="empty-state">
        <p>No findings surfaced for this repository.</p>
        <p className="empty-state-hint">
          This usually means the repo is small or very clean. Try a larger,
          older repository with more history to dig through.
        </p>
      </div>
    )
  }

  const visible = filter === 'all' ? findings : findings.filter(f => f.type === filter)

  const counts = {
    all: findings.length,
    era: findings.filter(f => f.type === 'era').length,
    dead_code: findings.filter(f => f.type === 'dead_code').length,
  }

  return (
    <div>
      <div className="filter-bar">
        {FILTERS.map(({ key, label }) => (
          counts[key] > 0 || key === 'all' ? (
            <button
              key={key}
              className={`filter-btn${filter === key ? ' active' : ''}`}
              onClick={() => setFilter(key)}
            >
              {label}
              <span className="filter-count">{counts[key]}</span>
            </button>
          ) : null
        ))}
      </div>

      {visible.length === 0 ? (
        <div className="empty-state">No {FILTERS.find(f => f.key === filter)?.label.toLowerCase()} findings.</div>
      ) : (
        <div className="ledger">
          {visible.map((f) => (
            <div className="entry" key={f.id}>
              <div className={`entry-type ${f.type}`}>
                {TYPE_LABELS[f.type] || f.type}
                {f.module ? ` · ${f.module}` : ''}
              </div>
              <h3 className="entry-title">{f.title}</h3>
              <p className="entry-narrative">{f.narrative}</p>
              <div className="entry-meta">
                <div className="stamp-row">
                  {f.evidence.map((e, i) => (
                    <EvidenceStamp evidence={e} repoUrl={repoUrl} key={i} />
                  ))}
                </div>
                <span className="confidence-badge">
                  confidence {Math.round(f.confidence * 100)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
