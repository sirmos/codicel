"""
Codicel API server.

POST /analyze        -> kicks off a background analysis job, returns job_id
GET  /status/{job_id} -> poll for progress (used by the frontend timeline
                          to show live "excavating..." progress)
GET  /result/{job_id} -> the final AnalysisResult once status == done

Kept intentionally simple (in-memory job store, background thread) since
this only needs to survive a hackathon demo, not production traffic. If you
have time on Day 4, swapping JOBS for Redis is a 20-minute change and not
worth doing before then.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ingest import build_corpus, cleanup_corpus
from analyze import run_full_analysis
from models import AnalyzeRequest, AnalysisResult, JobProgress, JobStatus

app = FastAPI(title="Codicel API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before anything beyond the demo
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, JobProgress] = {}
RESULTS: dict[str, AnalysisResult] = {}


def _set_progress(job_id: str, status: JobStatus, label: str, percent: int, error: str | None = None):
    JOBS[job_id] = JobProgress(job_id=job_id, status=status, step_label=label, percent=percent, error=error)


def _run_job(job_id: str, req: AnalyzeRequest):
    corpus = None
    try:
        _set_progress(job_id, JobStatus.CLONING, "Cloning repository and reading full commit history…", 10)
        corpus = build_corpus(req.repo_url, req.max_commits, req.github_token)

        _set_progress(job_id, JobStatus.INDEXING, "Indexing commits, PRs, and current file tree…", 35)
        # (indexing happens inside run_full_analysis's clustering step; this
        # progress step exists mainly so the UI has something to show)

        _set_progress(job_id, JobStatus.REASONING, "Reconstructing architecture decisions and dead code…", 60)
        findings = run_full_analysis(corpus)

        result = AnalysisResult(
            job_id=job_id,
            repo_url=req.repo_url,
            generated_at=datetime.now(timezone.utc).isoformat(),
            findings=findings,
            stats={
                "commits_analyzed": len(corpus.commits),
                "prs_analyzed": len(corpus.pull_requests),
                "files_in_tree": len(corpus.file_index),
                "findings_count": len(findings),
            },
        )
        RESULTS[job_id] = result
        _set_progress(job_id, JobStatus.DONE, "Excavation complete.", 100)
    except Exception as e:
        _set_progress(job_id, JobStatus.ERROR, "Analysis failed.", 0, error=str(e))
    finally:
        if corpus is not None:
            cleanup_corpus(corpus)


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    job_id = str(uuid.uuid4())
    _set_progress(job_id, JobStatus.QUEUED, "Queued…", 0)
    thread = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/status/{job_id}", response_model=JobProgress)
def status(job_id: str) -> JobProgress:
    if job_id not in JOBS:
        raise HTTPException(404, "Unknown job_id")
    return JOBS[job_id]


@app.get("/result/{job_id}", response_model=AnalysisResult)
def result(job_id: str) -> AnalysisResult:
    if job_id not in RESULTS:
        raise HTTPException(404, "Result not ready")
    return RESULTS[job_id]


@app.get("/health")
def health() -> dict:
    return {"ok": True}
