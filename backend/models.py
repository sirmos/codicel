"""
Shared data models for Codicel.

These are the shapes that flow from git ingestion -> Codex reasoning -> the
frontend timeline. Keeping them explicit (rather than passing raw dicts
around) makes the reasoning prompts easier to grade for accuracy: every
claim the model makes has to fit one of these evidence-bearing shapes.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class FindingType(str, Enum):
    ERA = "era"                # a period of related commits representing one decision
    DEAD_CODE = "dead_code"    # defined but unreferenced code
    HIDDEN_API = "hidden_api"  # still-live but undocumented/unreferenced-from-app-flow
    ABANDONED_FEATURE = "abandoned_feature"


class Evidence(BaseModel):
    """A single piece of grounding evidence. Every Finding must cite at least one."""
    commit_sha: Optional[str] = None
    commit_message: Optional[str] = None
    pr_number: Optional[int] = None
    pr_title: Optional[str] = None
    file_path: Optional[str] = None
    line_range: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None


class Finding(BaseModel):
    id: str
    type: FindingType
    title: str                       # short label, e.g. "Auth rewritten to JWT"
    narrative: str                   # the reconstructed "why" explanation
    confidence: float = Field(ge=0.0, le=1.0)
    module: Optional[str] = None     # e.g. "auth", "payments"
    date_range: Optional[str] = None
    evidence: List[Evidence] = []


class AnalyzeRequest(BaseModel):
    repo_url: str
    max_commits: int = 1500          # safety cap for demo-time performance
    github_token: Optional[str] = None


class JobStatus(str, Enum):
    QUEUED = "queued"
    CLONING = "cloning"
    INDEXING = "indexing"
    REASONING = "reasoning"
    DONE = "done"
    ERROR = "error"


class JobProgress(BaseModel):
    job_id: str
    status: JobStatus
    step_label: str
    percent: int = 0
    error: Optional[str] = None


class AnalysisResult(BaseModel):
    job_id: str
    repo_url: str
    generated_at: str
    findings: List[Finding]
    stats: dict


class ChatRequest(BaseModel):
    question: str
    result_snapshot: Optional[dict] = None  # full AnalysisResult sent by the frontend


class ChatMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatResponse(BaseModel):
    answer: str
