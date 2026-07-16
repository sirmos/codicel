export default function EvidenceStamp({ evidence, repoUrl }) {
  const label = evidence.commit_sha
    ? evidence.commit_sha.slice(0, 7)
    : evidence.file_path || 'evidence'

  const href = evidence.commit_sha && repoUrl
    ? `${repoUrl.replace(/\.git$/, '')}/commit/${evidence.commit_sha}`
    : undefined

  const content = (
    <span className="stamp" title={evidence.commit_message || evidence.file_path || ''}>
      {label}
    </span>
  )

  return href ? (
    <a href={href} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
      {content}
    </a>
  ) : content
}
