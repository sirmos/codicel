"""
Codicel API server.

POST /analyze           -> kicks off a background analysis job, returns job_id
GET  /status/{job_id}   -> poll for progress
GET  /result/{job_id}   -> the final AnalysisResult once status == done
POST /cancel/{job_id}   -> signal a running job to stop
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
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
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Keep the most recent MAX_STORED jobs; older ones are evicted automatically.
MAX_STORED = 50
JOBS: OrderedDict[str, JobProgress] = OrderedDict()
RESULTS: OrderedDict[str, AnalysisResult] = OrderedDict()
CANCEL_FLAGS: dict[str, threading.Event] = {}


def _evict_old():
    while len(RESULTS) > MAX_STORED:
        oldest = next(iter(RESULTS))
        RESULTS.pop(oldest, None)
        JOBS.pop(oldest, None)
        CANCEL_FLAGS.pop(oldest, None)


def _classify_error(e: Exception) -> str:
    msg = str(e).lower()
    if "authentication" in msg or "403" in msg or "401" in msg:
        return "Authentication failed — the repository may be private, or your API key is invalid."
    if "not found" in msg or "404" in msg or "does not exist" in msg:
        return "Repository not found — check the URL and make sure it is public."
    if "rate limit" in msg or "429" in msg:
        return "GitHub API rate limit hit — add a GITHUB_TOKEN secret to raise the limit."
    if "timed out" in msg or "timeout" in msg:
        return "Request timed out — the repository may be very large. Try a smaller one."
    if "api_key" in msg or "openai" in msg or "groq" in msg:
        return "AI model error — check that your API key is set and has available credits."
    if "cancelled" in msg:
        return "Cancelled by user."
    return f"Analysis failed: {e}"


def _set_progress(
    job_id: str, status: JobStatus, label: str, percent: int, error: str | None = None
):
    JOBS[job_id] = JobProgress(
        job_id=job_id, status=status, step_label=label, percent=percent, error=error
    )


def _run_job(job_id: str, req: AnalyzeRequest):
    cancel = CANCEL_FLAGS[job_id]
    corpus = None
    try:
        _set_progress(job_id, JobStatus.CLONING, "Cloning repository and reading full commit history…", 10)
        corpus = build_corpus(req.repo_url, req.max_commits, req.github_token)

        if cancel.is_set():
            _set_progress(job_id, JobStatus.ERROR, "Cancelled.", 0, error="Cancelled by user.")
            return

        _set_progress(job_id, JobStatus.INDEXING, "Indexing commits, PRs, and current file tree…", 35)

        if cancel.is_set():
            _set_progress(job_id, JobStatus.ERROR, "Cancelled.", 0, error="Cancelled by user.")
            return

        _set_progress(job_id, JobStatus.REASONING, "Reconstructing architecture decisions and dead code…", 60)
        findings = run_full_analysis(corpus, cancel)

        if cancel.is_set():
            _set_progress(job_id, JobStatus.ERROR, "Cancelled.", 0, error="Cancelled by user.")
            return

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
        _evict_old()
        _set_progress(job_id, JobStatus.DONE, "Excavation complete.", 100)
    except Exception as e:
        _set_progress(job_id, JobStatus.ERROR, "Analysis failed.", 0, error=_classify_error(e))
    finally:
        if corpus is not None:
            cleanup_corpus(corpus)


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    job_id = str(uuid.uuid4())
    CANCEL_FLAGS[job_id] = threading.Event()
    _set_progress(job_id, JobStatus.QUEUED, "Queued…", 0)
    thread = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str) -> dict:
    if job_id not in CANCEL_FLAGS:
        raise HTTPException(404, "Unknown job_id")
    CANCEL_FLAGS[job_id].set()
    return {"ok": True}


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
