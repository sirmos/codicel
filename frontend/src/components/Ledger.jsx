import EvidenceStamp from './EvidenceStamp.jsx'

const TYPE_LABELS = {
  era: 'Architectural decision',
  dead_code: 'Abandoned code',
  hidden_api: 'Hidden / undocumented API',
  abandoned_feature: 'Abandoned feature',
}

export default function Ledger({ findings, repoUrl }) {
  if (!findings.length) {
    return <div className="empty-state">No findings to show yet.</div>
  }

  return (
    <div className="ledger">
      {findings.map((f) => (
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
  )
}
