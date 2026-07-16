# Codicel

Reads a GitHub repo's full git history and surfaces what changed, why, and what got left behind — every claim backed by a real commit link.

## Stack

- **Backend**: Python / FastAPI (port 8000) — `backend/`
- **Frontend**: React / Vite (port 5000) — `frontend/`

## How to run

Two workflows run the app:

| Workflow | Command | Port |
|---|---|---|
| Backend API | `cd backend && uvicorn main:app --host 0.0.0.0 --port 8000` | 8000 |
| Start application | `cd frontend && npm run dev` | 5000 (webview) |

The frontend proxies `/api/*` → `http://localhost:8000`.

## Required secrets

| Key | Purpose |
|---|---|
| `OPENAI_API_KEY` | GPT model for commit reasoning (required) |
| `GITHUB_TOKEN` | Optional — raises GitHub API rate limit for PR metadata |
| `CODICEL_MODEL` | Optional — override model name (default: `gpt-4o`) |

Set these via Replit Secrets.

## Usage

Paste a public GitHub repo URL into the UI and click **Excavate**. Pick a repo with some years of history for the most interesting results.

## User preferences

- Keep the project's existing backend/frontend split; do not merge into a monorepo.
