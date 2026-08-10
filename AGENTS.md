# AGENTS.md

## Project Constraints (READ FIRST)

This is a strictly personal, private, single-user project. It is never published,
distributed, commercialized, or uploaded to GitHub. It runs exclusively on the
owner's local PC.

- **Local-first, single-user, privacy-focused.** Optimize for one trusted local user.
- **Full local access allowed.** May integrate deeply with the local machine when
  explicitly allowed: files/folders, applications, terminal/shell, clipboard,
  screenshots, microphone, speakers, system info, local processes, local network
  services, notifications, browser interaction.
- **Do not** design around public deployment, SaaS, multi-user support, or public
  distribution. Do not add unnecessary cloud infrastructure.
- **Dangerous/destructive operations still require confirmation** before running
  (e.g. deleting files, destructive commands, modifying critical system resources).
- **Secrets stay local:** sensitive credentials, API keys, personal data, and local
  configuration must not be committed to source-controlled files (use `.env`,
  `.gitignore`, or an untracked local store).
- **Priority order:** Local-first → Single-user → Privacy-focused → Full functionality
  → Deep OS integration → Reliability → Performance.

## Commands

### Backend (Python — jarvis_backend/)
| Command | Description |
|---------|-------------|
| `venv/bin/python -m pytest jarvis_backend/tests/ -v` | Run backend tests |
| `venv/bin/pip install -r jarvis_backend/requirements.txt` | Install deps |

### Frontend (TypeScript — jarvis_frontend/)
| Command | Description |
|---------|-------------|
| `cd jarvis_frontend && npx tsc --noEmit` | TypeScript type check |
| `cd jarvis_frontend && npx vitest run` | Run frontend unit tests |
| `cd jarvis_frontend && npx eslint . --ext .ts,.tsx` | Lint |
| `cd jarvis_frontend && npx prettier --check "src/**/*.{ts,tsx}"` | Format check |

### Lint & Format (root)
| Command | Description |
|---------|-------------|
| `ruff check jarvis_backend/` | Python linter |
| `black --check jarvis_backend/` | Python formatter check |
