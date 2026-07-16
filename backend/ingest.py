"""
Ingestion: turns a git repository into the structured corpus that the
reasoning layer (analyze.py) works over.

Deliberately dependency-light: GitPython for local history, a thin GitHub
REST wrapper for PR/issue titles (optional. Codicel degrades gracefully to
commit-only reasoning if no GitHub token / API access is available, which
matters for the demo if you hit rate limits).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

import git
import httpx


@dataclass
class CommitRecord:
    sha: str
    author: str
    date: str
    message: str
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0


@dataclass
class PullRequestRecord:
    number: int
    title: str
    body: str
    merged_at: Optional[str]
    files: List[str] = field(default_factory=list)


@dataclass
class RepoCorpus:
    repo_url: str
    local_path: str
    commits: List[CommitRecord]
    pull_requests: List[PullRequestRecord]
    file_index: List[str]  # current tracked files, for dead-code cross-referencing


def clone_repo(repo_url: str) -> str:
    """Shallow-ish clone into a temp dir. Returns local path."""
    tmp_dir = tempfile.mkdtemp(prefix="codicel_")
    # Full history is required (not --depth=1) since the whole point is
    # reading historical intent, not just current state.
    git.Repo.clone_from(repo_url, tmp_dir)
    return tmp_dir


def extract_commits(local_path: str, max_commits: int) -> List[CommitRecord]:
    repo = git.Repo(local_path)
    records: List[CommitRecord] = []
    for commit in repo.iter_commits(max_count=max_commits):
        try:
            stats = commit.stats.total
            files = list(commit.stats.files.keys())
        except Exception:
            stats = {"insertions": 0, "deletions": 0}
            files = []
        records.append(
            CommitRecord(
                sha=commit.hexsha,
                author=str(commit.author),
                date=commit.committed_datetime.isoformat(),
                message=commit.message.strip(),
                files_changed=files,
                insertions=stats.get("insertions", 0),
                deletions=stats.get("deletions", 0),
            )
        )
    return records


def extract_current_files(local_path: str) -> List[str]:
    repo = git.Repo(local_path)
    return [item.path for item in repo.tree().traverse() if item.type == "blob"]


def _parse_owner_repo(repo_url: str) -> Optional[tuple[str, str]]:
    url = repo_url.rstrip("/").removesuffix(".git")
    if "github.com" not in url:
        return None
    tail = url.split("github.com/")[-1]
    parts = tail.split("/")
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def extract_pull_requests(
    repo_url: str, github_token: Optional[str] = None, limit: int = 200
) -> List[PullRequestRecord]:
    """Best-effort PR pull via GitHub REST API. Returns [] if unavailable.
    the reasoning layer treats commit messages as the source of truth in
    that case, so this is an enrichment, not a hard dependency."""
    owner_repo = _parse_owner_repo(repo_url)
    if not owner_repo:
        return []
    owner, repo = owner_repo

    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    prs: List[PullRequestRecord] = []
    try:
        with httpx.Client(timeout=15.0) as client:
            page = 1
            while len(prs) < limit:
                resp = client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/pulls",
                    params={"state": "closed", "per_page": 50, "page": page},
                    headers=headers,
                )
                if resp.status_code != 200:
                    break
                batch = resp.json()
                if not batch:
                    break
                for pr in batch:
                    prs.append(
                        PullRequestRecord(
                            number=pr["number"],
                            title=pr.get("title", ""),
                            body=(pr.get("body") or "")[:2000],
                            merged_at=pr.get("merged_at"),
                        )
                    )
                page += 1
    except httpx.HTTPError:
        return prs
    return prs


def build_corpus(repo_url: str, max_commits: int = 1500, github_token: Optional[str] = None) -> RepoCorpus:
    local_path = clone_repo(repo_url)
    commits = extract_commits(local_path, max_commits)
    files = extract_current_files(local_path)
    prs = extract_pull_requests(repo_url, github_token)
    return RepoCorpus(
        repo_url=repo_url,
        local_path=local_path,
        commits=commits,
        pull_requests=prs,
        file_index=files,
    )


def cleanup_corpus(corpus: RepoCorpus) -> None:
    shutil.rmtree(corpus.local_path, ignore_errors=True)
