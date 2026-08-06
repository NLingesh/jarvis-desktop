# AGENTS.md

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
