# Codicel — Software Archaeology powered by GPT-5.6

> *An amended record of what this repository became, and why.*

**Live demo:** https://frontend-57n9.onrender.com

Codicel reads a GitHub repository's full commit history and tells you what happened inside it — the big architectural decisions, the code that got built and forgotten, and the turning points that shaped the codebase. Every claim is anchored to a real commit. Nothing gets said without proof.

Then it lets you **talk to that history** — ask GPT-5.6 any question about the repo's past and get a grounded answer backed by the same evidence.

Built with GPT-5.6 and Codex for [OpenAI Build Week](https://devpost.com/software/codicel).

---

## The problem

Old codebases are hard to understand. The people who made the big decisions are often gone. Nothing got written down. The only way to find out "why is this built this way?" is to dig through thousands of commits by hand — or ask around and hope someone remembers.

The history already has the answer. It's just scattered across thousands of commits.

---

## What Codicel does

**1. Excavate** — Paste any public GitHub URL. Codicel clones the repo and reads its full commit history. It clusters commits into architectural eras by module and runs static analysis to find unreferenced code — all without any AI.

**2. Narrate** — GPT-5.6 explains what each cluster means: what changed, why it likely happened, and what got left behind. Every finding is grounded — if there's no real commit or file attached to it, it gets dropped before it ever reaches the screen.

**3. Ask the Archive** — After excavation, ask any natural-language question about the repo's past. "Why was the auth system rewritten?" "What happened to the WebSocket module?" "How did testing evolve?" GPT-5.6 answers from the evidence, not from guesswork.

---

## How GPT-5.6 and Codex are used

### GPT-5.6 (reasoning engine — `backend/analyze.py`)

- **`narrate_eras()`** — Feeds GPT-5.6 chronological commit clusters per module and asks it to identify and narrate architectural decisions, grounded only in the commits shown. Returns structured JSON with evidence SHAs.
- **`narrate_dead_code()`** — Sends unreferenced function candidates (found by static analysis) to GPT-5.6 to distinguish genuine dead code from false positives (framework hooks, dynamically-invoked code, test fixtures). Anything flagged as a likely false positive is discarded.
- **`ask_archive()`** — Powers the "Ask the Archive" conversational feature. GPT-5.6 answers natural-language questions about the repo's history using the excavated findings as its only knowledge base. The system prompt explicitly prohibits inventing commits, files, or dates not in the evidence.

### Codex (built the entire project)

Codex was used throughout the build:
- FastAPI backend architecture (`main.py`, `ingest.py`, `analyze.py`, `models.py`)
- Git ingestion pipeline — cloning, commit extraction, PR fetching via GitHub API
- Commit clustering and dead-code detection logic
- Evidence validation system (drops any ungrounded finding before it reaches the UI)
- React frontend — all components, the progress/polling flow, the chat interface
- Deduplication fix for cross-module findings (assigns each commit to its dominant module)

---

## Project layout

```
codicel/
  backend/
    main.py         FastAPI: /analyze, /status, /result, /chat, /cancel
    ingest.py       Clone repo, extract commits + PRs (GitPython + GitHub API)
    analyze.py      Cluster eras, detect dead code, call GPT-5.6, power chat
    models.py       Pydantic models shared across all layers
    requirements.txt
    .env.example
  frontend/
    src/
      App.jsx                 Form, progress, results, export, share
      components/
        Ledger.jsx            Filterable findings timeline (All / Decisions / Dead code)
        EvidenceStamp.jsx     Commit badge linking directly to GitHub
        AskArchive.jsx        Conversational follow-up powered by GPT-5.6
      index.css
    package.json
    vite.config.js
```

---

## Setup

### 1. Secrets / environment

Copy `backend/.env.example` to `backend/.env`:

```bash
# Required
OPENAI_API_KEY=sk-...
CODICEL_MODEL=gpt-5.6

# Optional: raises GitHub API rate limit for PR metadata
GITHUB_TOKEN=ghp_...

# Optional: use Groq instead of OpenAI (free, good for testing)
# CODICEL_API_BASE=https://api.groq.com/openai/v1
# CODICEL_API_KEY=gsk_...
# CODICEL_MODEL=llama-3.3-70b-versatile
```

### 2. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5000`. The Vite dev server proxies `/api/*` → `http://localhost:8000`.

### 4. Try it

Paste a public GitHub URL and click **Excavate**. For the most interesting results, use a repo that's several years old with significant history. Small or very clean repos may surface fewer findings — the accuracy filter is working as intended.

After excavation, use **Ask the Archive** to have a conversation with the repo's history.

---

## Accuracy guarantee

Every finding shown has at least one real commit SHA or file path behind it. The code drops any ungrounded claim before it reaches the UI — if findings count is lower than expected, that's the filter working, not a bug.

The "Ask the Archive" chat is held to the same standard. GPT-5.6 is explicitly instructed not to invent commits, files, dates, or decisions not present in the findings.

---

## Notes for judges

- `CODICEL_MODEL` controls the model. Set to the GPT-5.6 string from your Build Week credits.
- The cheap work (commit clustering, dead-code regex) runs entirely locally — no AI involved until the narration step.
- Findings survive page refreshes (stored in `localStorage`). The "Ask the Archive" chat requires the backend to be running (job result must still be in memory).
- For very large repos, the `max_commits` parameter (default 1500) caps ingestion time.
