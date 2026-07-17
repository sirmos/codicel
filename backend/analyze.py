"""
The reasoning core of Codicel.

Design principle: the LLM is only allowed to make claims that are anchored
to evidence we hand it. We don't ask "what happened in this repo's
history" as an open question. Instead we pre-cluster commits into candidate
"eras" and pre-detect dead-code candidates with plain static analysis
first, and only ask the model to *narrate and explain* those grounded
signals. This keeps hallucination risk down and keeps every Finding
traceable to a real commit/file, which is what the demo needs to be
credible to judges.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from openai import OpenAI

from ingest import RepoCorpus, CommitRecord
from models import Evidence, Finding, FindingType, AnalysisResult

MODEL = os.getenv("CODICEL_MODEL", "gpt-5.6")

# Groq's API speaks the same format as OpenAI's, so switching between them
# is just a matter of pointing the client at a different base_url and using
# a different key and model name. Set CODICEL_API_BASE and CODICEL_API_KEY
# in .env to point this at Groq while OpenAI billing isn't set up yet, then
# switch both back to OpenAI's defaults before the final demo, since the
# hackathon rules score how GPT-5.6 specifically was used.
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_base = os.getenv("CODICEL_API_BASE")
        api_key = os.getenv("CODICEL_API_KEY") or os.getenv("OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key, base_url=api_base) if api_base else OpenAI(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Step 1: cluster commits into candidate "eras" per module (cheap, local)
# ---------------------------------------------------------------------------

def _module_of(path: str) -> str:
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "root"


def cluster_eras(commits: List[CommitRecord], min_cluster_size: int = 3) -> dict:
    """Group commits by top-level module. Each commit is assigned to its
    *dominant* module (the one with the most files changed) rather than
    every module it touched. This prevents cross-cutting changes (e.g.
    async support landing in src/, docs/, and tests/ simultaneously) from
    generating duplicate findings for each folder."""
    by_module: dict[str, List[CommitRecord]] = defaultdict(list)
    for c in commits:
        if not c.files_changed:
            by_module["root"].append(c)
            continue
        # Count touched files per top-level module; assign to the plurality.
        module_counts: dict[str, int] = defaultdict(int)
        for f in c.files_changed:
            module_counts[_module_of(f)] += 1
        primary = max(module_counts, key=lambda m: module_counts[m])
        by_module[primary].append(c)

    clusters = {
        module: sorted(cs, key=lambda c: c.date)
        for module, cs in by_module.items()
        if len(cs) >= min_cluster_size
    }
    return clusters


# ---------------------------------------------------------------------------
# Step 2: static dead-code candidate detection (cheap, local, multi-language)
# ---------------------------------------------------------------------------

_DEF_PATTERNS = [
    re.compile(r"^\s*def\s+(\w+)\s*\("),                           # Python / Ruby
    re.compile(r"^\s*function\s+(\w+)\s*\("),                      # JS/TS (plain)
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\("),  # JS/TS (export/async)
    re.compile(r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+)?(?:async\s+)?\w[\w<>\[\]]*\s+(\w+)\s*\("),  # Java / C#
    re.compile(r"^\s*fn\s+(\w+)\s*[(<]"),                          # Rust
    re.compile(r"^\s*func\s+(\w+)\s*\("),                          # Go / Swift
    re.compile(r"^\s*fun\s+(\w+)\s*\("),                           # Kotlin
]

_CODE_EXTENSIONS = (
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rb", ".rs", ".swift", ".kt", ".cs",
)


def find_dead_code_candidates(local_path: str, file_index: List[str], sample_limit: int = 400) -> List[dict]:
    """Very intentionally simple: find top-level function/method definitions,
    then grep the rest of the tree for references. Anything defined once and
    referenced zero times outside its own file is a candidate. This is a
    heuristic pre-filter. The LLM pass explains *why* each candidate looks
    abandoned, using the commit history, and can discard false positives."""
    candidates = []
    code_files = [
        f for f in file_index
        if f.endswith(_CODE_EXTENSIONS)
    ][:sample_limit]

    definitions: dict[str, str] = {}  # name -> defining file
    file_contents: dict[str, str] = {}

    for rel_path in code_files:
        abs_path = os.path.join(local_path, rel_path)
        try:
            with open(abs_path, "r", errors="ignore") as fh:
                content = fh.read()
        except OSError:
            continue
        file_contents[rel_path] = content
        for line in content.splitlines():
            for pattern in _DEF_PATTERNS:
                m = pattern.match(line)
                if m:
                    name = m.group(1)
                    if len(name) > 3 and not name.startswith("_"):
                        definitions.setdefault(name, rel_path)

    for name, def_file in definitions.items():
        ref_count = 0
        for rel_path, content in file_contents.items():
            if rel_path == def_file:
                continue
            ref_count += content.count(name)
        if ref_count == 0:
            candidates.append({"name": name, "file": def_file})

    return candidates


# ---------------------------------------------------------------------------
# Step 3: LLM narration. Turns grounded clusters/candidates into Findings
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are Codicel's reasoning core: a software archaeologist.
You are given real evidence extracted from a git repository: commit
clusters and dead-code candidates. Your job is to explain what likely
happened and why, grounded ONLY in the evidence provided.

Rules:
- Never invent a commit sha, PR number, file path, or date that isn't in
  the evidence you were given.
- If the evidence is too thin to explain confidently, say so with a lower
  confidence score rather than inventing a story.
- Write narratives the way a senior engineer would explain repo history to
  a new hire: concrete, causal, no fluff.
- Output strict JSON matching the requested schema. No prose outside JSON.
"""


def _era_prompt(module: str, commits: List[CommitRecord]) -> str:
    commit_lines = "\n".join(
        f"- sha={c.sha[:10]} date={c.date} msg={c.message[:140]!r} files={c.files_changed[:6]}"
        for c in commits[:40]  # cap tokens per module
    )
    return f"""Module: {module}
Commits (chronological):
{commit_lines}

Task: Identify 0-2 distinct architectural "eras" or decisions in this
module's history (e.g. a rewrite, a migration, a new dependency adopted,
a pattern abandoned). For each era, return:
{{
  "title": short label,
  "narrative": 2-4 sentences explaining what changed and why, grounded in
     the commit messages shown,
  "confidence": 0.0-1.0,
  "date_range": "YYYY-MM-DD to YYYY-MM-DD",
  "evidence_shas": [list of the specific commit shas above that support this]
}}
Return a JSON object: {{"eras": [...]}}. If nothing meaningful stands out,
return {{"eras": []}}.
"""


def narrate_eras(clusters: dict, cancel: Optional[threading.Event] = None) -> List[Finding]:
    # Focus on the top 15 modules by commit volume — large repos can have
    # 50+ top-level dirs and processing all of them sequentially is the
    # second biggest source of latency after commit extraction.
    MAX_MODULES = 15
    ranked = sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)[:MAX_MODULES]

    def _narrate_one(module: str, commits: List[CommitRecord]) -> List[Finding]:
        if cancel and cancel.is_set():
            return []
        try:
            resp = _get_client().chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _era_prompt(module, commits)},
                ],
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
        except Exception:
            return []

        sha_lookup = {c.sha[:10]: c for c in commits}
        module_findings: List[Finding] = []
        for era in data.get("eras", []):
            evidence = [
                Evidence(
                    commit_sha=sha_lookup[sha].sha,
                    commit_message=sha_lookup[sha].message,
                    date=sha_lookup[sha].date,
                    file_path=None,
                )
                for sha in era.get("evidence_shas", [])
                if sha in sha_lookup
            ]
            if not evidence:
                continue  # never emit an ungrounded finding
            module_findings.append(
                Finding(
                    id=str(uuid.uuid4()),
                    type=FindingType.ERA,
                    title=era.get("title", f"{module} changes"),
                    narrative=era.get("narrative", ""),
                    confidence=float(era.get("confidence", 0.5)),
                    module=module,
                    date_range=era.get("date_range"),
                    evidence=evidence,
                )
            )
        return module_findings

    findings: List[Finding] = []
    # Fire all module LLM calls concurrently instead of one-at-a-time.
    # 5 workers keeps total concurrent requests reasonable without hammering
    # the API rate limit.
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(_narrate_one, module, commits): module
            for module, commits in ranked
        }
        for future in as_completed(futures):
            if cancel and cancel.is_set():
                break
            try:
                findings.extend(future.result())
            except Exception:
                pass

    return findings


def _dead_code_prompt(candidates: List[dict], commits: List[CommitRecord]) -> str:
    cand_lines = "\n".join(f"- {c['name']} in {c['file']}" for c in candidates[:60])
    # Give the model a small window of commit messages for context on intent.
    recent_msgs = "\n".join(f"- {c.message[:120]!r}" for c in commits[:80])
    return f"""Unreferenced-elsewhere function/method candidates (heuristic
pre-filter. May include false positives like framework entry points,
test fixtures, or dynamically-invoked code; use judgment):
{cand_lines}

Recent commit messages for context:
{recent_msgs}

Task: For each candidate that plausibly represents genuinely abandoned or
forgotten code (not a false positive), return:
{{
  "name": ..., "file": ...,
  "narrative": "1-3 sentences on what it was likely for and why it looks abandoned",
  "confidence": 0.0-1.0,
  "likely_false_positive": true/false
}}
Return {{"findings": [...]}}. Omit candidates you judge to be false
positives (or include them with likely_false_positive=true and low
confidence, but Codicel will discard those before showing users).
"""


def narrate_dead_code(candidates: List[dict], commits: List[CommitRecord]) -> List[Finding]:
    if not candidates:
        return []
    try:
        resp = _get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _dead_code_prompt(candidates, commits)},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception:
        return []

    cand_lookup = {c["name"]: c for c in candidates}
    findings: List[Finding] = []
    for item in data.get("findings", []):
        if item.get("likely_false_positive"):
            continue
        name = item.get("name")
        cand = cand_lookup.get(name)
        if not cand:
            continue
        findings.append(
            Finding(
                id=str(uuid.uuid4()),
                type=FindingType.DEAD_CODE,
                title=f"{name}() looks abandoned",
                narrative=item.get("narrative", ""),
                confidence=float(item.get("confidence", 0.4)),
                module=_module_of(cand["file"]),
                evidence=[Evidence(file_path=cand["file"])],
            )
        )
    return findings


def ask_archive(result: AnalysisResult, question: str) -> str:
    """Answer a natural-language question about the repo's history using
    the excavated findings as the only knowledge base. GPT-5.6 is explicitly
    prohibited from inventing commits, files, or dates not in the evidence."""
    repo_base = result.repo_url.rstrip("/").removesuffix(".git")
    lines: List[str] = [
        f"Repository: {result.repo_url}",
        f"Analyzed: {result.generated_at}",
        f"Commits read: {result.stats.get('commits_analyzed', '?')}",
        f"Files indexed: {result.stats.get('files_in_tree', '?')}",
        f"Findings: {len(result.findings)}",
        "",
    ]
    for f in result.findings:
        lines.append(f"## {f.title} [{f.type}]")
        if f.module:
            lines.append(f"Module: {f.module}")
        if f.date_range:
            lines.append(f"Period: {f.date_range}")
        lines.append(f"Confidence: {round(f.confidence * 100)}%")
        lines.append(f"Narrative: {f.narrative}")
        if f.evidence:
            lines.append("Evidence:")
            for e in f.evidence:
                if e.commit_sha:
                    msg = (e.commit_message or "").split("\n")[0][:120]
                    lines.append(f"  - commit {e.commit_sha[:10]} ({e.date or ''}): {msg}")
                    lines.append(f"    link: {repo_base}/commit/{e.commit_sha}")
                elif e.file_path:
                    lines.append(f"  - file: {e.file_path}")
        lines.append("")

    context = "\n".join(lines)

    resp = _get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the Codicel archive assistant — a software archaeologist.\n"
                    "You have access to an excavation report for a git repository: "
                    "findings about architectural decisions and abandoned code, each "
                    "backed by real commit evidence.\n\n"
                    "Rules:\n"
                    "- Answer ONLY from the findings provided. Never invent a commit "
                    "SHA, file path, date, or decision that is not in the report.\n"
                    "- If the answer is not in the findings, say so clearly.\n"
                    "- When evidence supports your answer, cite the commit SHA or file.\n"
                    "- Write like a senior engineer explaining history to a colleague: "
                    "direct, concrete, no filler."
                ),
            },
            {
                "role": "user",
                "content": f"Excavation report:\n\n{context}\n\nQuestion: {question}",
            },
        ],
    )
    return resp.choices[0].message.content


def run_full_analysis(corpus: RepoCorpus, cancel: Optional[threading.Event] = None) -> List[Finding]:
    clusters = cluster_eras(corpus.commits)
    era_findings = narrate_eras(clusters, cancel)

    if cancel and cancel.is_set():
        return era_findings

    dead_candidates = find_dead_code_candidates(corpus.local_path, corpus.file_index)
    dead_findings = narrate_dead_code(dead_candidates, corpus.commits)

    return era_findings + dead_findings
