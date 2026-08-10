# JARVIS — Voice AI Assistant

A voice-first AI assistant for Linux that integrates with your calendar, email, notes, documents, and the web. JARVIS runs as an Electron desktop app (or in the browser) with a FastAPI + React + Three.js backend, and streams text + audio for a hands-free experience.

## Features

- 🎤 **Offline Speech Recognition** — Vosk STT runs locally, no API key needed (OpenAI Whisper fallback optional)
- 🔊 **Streaming TTS** — ElevenLabs → Microsoft Edge TTS → system `espeak`/`piper` fallback chain
- 📅 **Calendar Integration** — Access and manage calendar events via voice
- 📧 **Email Management** — Read, send, and manage emails by voice (IMAP/SMTP)
- 📝 **Notes** — Create and organize notes through natural conversation
- 📄 **Document Control** — Create, read, edit, append, replace, and delete documents by voice, with confirmation prompts for destructive actions
- 🌐 **Web Browsing** — Search the web, check weather, translate text
- 🖥️ **System Info** — Monitor CPU, memory, disk, and processes
- 🪄 **Skill Registry** — Declarative intent-based routing to modules
- 💬 **Conversation Memory** — SQLite with FTS5 for fast full-text search
- ⚡ **Streaming Responses** — Real-time `partial` text + segmented audio chunks
- 🤖 **Provider-Agnostic LLM** — Mistral (primary) with Anthropic fallback
- 🎯 **NVIDIA Reranking** — Optional semantic reranking for better search results
- 💻 **Desktop App** — Electron shell with tray, floating bubble, wake-word, and auto-updates
- 🔒 **Privacy-First** — Conversations stored locally; session-token auth on the WebSocket and API
- 👁️ **Vision** — Screenshot capture, OCR, image analysis, window awareness
- 📋 **Task Management** — Create tasks, reminders, and scheduled jobs with cron
- 🔄 **Automation** — Rule-based workflows with if/then logic
- 🧠 **Adaptive Intelligence** — Behavior pattern learning and predictive suggestions
- 🔔 **Proactive AI** — AI-powered proactive suggestions and smart notifications
- 🛡️ **Security & Privacy** — Fernet encryption, privacy controls, data export/delete
- 📊 **Performance Monitoring** — Request metrics, latency tracking, system health checks

## Architecture

```
Electron / Browser (React + Three.js)
├── VoiceOrb (audio-reactive particle visualization)
├── Bubble (floating always-on-top orb, desktop only)
└── MediaRecorder → WAV (PCM16 16 kHz) → WebSocket
                    ↓
         FastAPI Backend (Python)  :8000
├── /ws/voice  (token-authenticated WebSocket)
│   ├── audio → Vosk STT (offline)
│   └── text  → Skill Registry → context (calendar/email/web/system/notes/documents)
│              → LLMProvider (Mistral streaming / Anthropic)
│              → TTS (ElevenLabs / Edge TTS / espeak)
│              → partial + audio_queue + audio_chunk* streamed back
└── /api/*     (REST: system, memory, mail, notes, calendar, llm, stt, settings)
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.11+, FastAPI, SQLite with FTS5 |
| **Frontend** | TypeScript, React 18, Vite, Three.js |
| **Desktop** | Electron 30 (tray, bubble window, auto-update) |
| **Communication** | WebSocket with JSON + base64 audio streaming |
| **AI - Primary** | Mistral (via mistral.ai / NVIDIA-hosted API) |
| **AI - Fallback** | Anthropic Claude |
| **STT** | Vosk (offline), OpenAI Whisper fallback |
| **Reranking** | NVIDIA Reranker (optional) |
| **TTS** | ElevenLabs → Edge TTS → espeak/piper |
| **Containerization** | Docker & Docker Compose |

## Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend build / dev only)
- **MISTRAL_API_KEY** (primary) — https://console.mistral.ai/ (an `nvapi-*` key also works via NVIDIA-hosted models)
- **or ANTHROPIC_API_KEY** (fallback) — https://console.anthropic.com/
- **ELEVENLABS_API_KEY** (optional) — https://elevenlabs.io/ (falls back to Edge TTS, then system TTS)
- **Vosk model** (optional, for offline voice input) — `bash scripts/download-vosk-model.sh`

## Quick Start

### One-Command Launch (Recommended)

```bash
cp jarvis_backend/.env.example jarvis_backend/.env
# Edit jarvis_backend/.env and add at least one LLM API key

./start.sh        # Mac / Linux   (start.bat on Windows)
```

The script creates the virtualenv, installs dependencies, starts the backend, and opens the browser.

### Desktop App

```bash
# First time
npm install
npm run build:install

# Run in development mode (launches Electron + backend)
npm start

# Package a distributable build
npm run build:app
```

### Manual — Backend

```bash
cd jarvis_backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your API keys
python main.py         # http://localhost:8000
```

### Manual — Frontend (browser dev)

```bash
cd jarvis_frontend
npm install
npm run dev            # http://localhost:5173 (proxies /api + /ws to :8000)
```

> The backend also serves the production frontend (`jarvis_frontend/dist`) at `http://localhost:8000` when built.

## Configuration

### Backend (.env)

```bash
# LLM (primary: Mistral, fallback: Anthropic)
LLM_PROVIDER=mistral
MISTRAL_API_KEY=your-key
MISTRAL_MODEL=mistralai/mistral-nemotron
MISTRAL_API_URL=https://api.mistral.ai
ANTHROPIC_API_KEY=your-key            # optional fallback

# TTS — ElevenLabs optional; Edge TTS is the default fallback
ELEVENLABS_API_KEY=your-key
EDGE_TTS_VOICE=en-US-GuyNeural

# Offline speech-to-text (Vosk) — model dir, empty = auto-detect
VOSK_MODEL_DIR=

# NVIDIA reranking (optional)
NVIDIA_API_KEY=your-key
NVIDIA_RERANK_MODEL=nv-rerank-qa-mistral-4b:1

# Email
EMAIL_IMAP_SERVER=imap.gmail.com
EMAIL_IMAP_PORT=993
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587

# Server
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
DEBUG=False
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://127.0.0.1:5173

# Calendar
CALENDAR_TYPE=evolution

# Database & documents
DATABASE_PATH=jarvis_memory.db
DOCUMENTS_ROOT=~/Documents/jarvis
ALLOWED_DOCUMENT_EXTENSIONS=.txt,.md,.csv,.docx,.pdf
ALLOWED_WRITE_EXTENSIONS=.txt,.md,.docx

# Logging
LOG_LEVEL=INFO
```

### Frontend Settings

Access Settings (⚙️) in the UI to configure:
- Voice language, volume, speech speed
- Theme (light/dark)
- Server URL, wake word
- Email integration (IMAP credentials)

## Usage

### Voice Mode

1. **Tap the orb** (or press `Space`) to start recording — tap again to stop and send
2. Audio is transcribed offline (Vosk) and processed by the skill registry + LLM
3. The response streams back as text and segmented audio

### Text Mode

Type in the input field at the bottom and press Enter.

### Example Commands

```
"What's on my calendar tomorrow?"
"Send an email to john@example.com saying hello"
"Remember to buy groceries"                      # creates a note
"Create a document named ideas.md with content …"
"Read document notes.txt"
"Search for Python best practices"
"What's my system CPU usage?"
"Translate 'hello' to Spanish"
"What's the weather like?"
```

Destructive document actions (overwrite, replace, delete) require a spoken confirmation ("yes"/"no").

## Module Structure

### Backend — `jarvis_backend/`

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, middleware (CSP, rate-limit, performance tracking), WebSocket `/ws/voice` |
| `routes/` | REST routers: `system`, `memory`, `mail`, `notes`, `calendar`, `llm`, `stt`, `settings`, `vision`, `tasks`, `automation`, `adaptive`, `proactive`, `security`, `performance` |
| `routes/state.py` | Shared singletons, session-token auth, skill registry wiring, `handle_user_input()` |
| `routes/deps.py` | Backward-compatible re-exports for tests and legacy imports |
| `managers/memory_manager.py` | `MemoryManager` — SQLite conversations + FTS5 search, behavior patterns, learning feedback |
| `managers/conversation_manager.py` | `ConversationManager`, `PreferenceManager`, `ContextManager` |
| `managers/system_manager.py` | `SystemManager` — system actions and info |
| `managers/audio_manager.py` | `AudioManager` — audio I/O |
| `managers/stt_manager.py` | `STTManager` — speech-to-text pipeline |
| `managers/tts_manager.py` | `TTSManager` — text-to-speech pipeline |
| `managers/voice_manager.py` | `VoiceManager` — voice pipeline orchestration |
| `managers/model_manager.py` | `ModelManager` — model routing and selection |
| `managers/vision_manager.py` | `VisionManager` — screenshot, OCR, image analysis, windows |
| `managers/task_manager.py` | `TaskManager` — tasks, reminders, scheduled jobs (APScheduler) |
| `managers/workflow_manager.py` | `WorkflowManager` — rule-based automation workflows |
| `managers/adaptive_intelligence.py` | `AdaptiveIntelligenceManager` — behavior learning, predictions |
| `managers/proactive_ai.py` | `ProactiveAIManager` — AI-powered suggestions and notifications |
| `managers/security_manager.py` | `SecurityManager` — Fernet encryption, privacy controls, data export/delete |
| `managers/performance_manager.py` | `PerformanceManager` — metrics, latency tracking, system health |
| `modules/llm_provider.py` | `LLMProvider` — Mistral (streaming) / Anthropic, NVIDIA reranking |
| `modules/tts.py` | `TextToSpeechModule` — ElevenLabs → Edge TTS → espeak/piper |
| `modules/stt.py` | `SpeechToTextModule` — offline Vosk with Whisper fallback |
| `modules/calendar_module.py` | Evolution / GNOME Calendar integration |
| `modules/mail_module.py` | IMAP/SMTP email access |
| `modules/notes_module.py` | JSON-based note storage |
| `modules/documents_module.py` | Sandboxed document read/write/edit in `DOCUMENTS_ROOT` |
| `modules/web_browse.py` | DuckDuckGo search, weather, translation |
| `modules/system_actions.py` | CPU/memory/disk/process monitoring (psutil) |
| `modules/audit.py` | Audit logging for security and compliance |
| `modules/auth.py` | `AuthService` — PBKDF2 password hashing, session tokens, bearer auth |
| `plugins/` | Plugin system: base, registry, loader, permissions, builtin skills |

### Frontend — `jarvis_frontend/src/`

| File | Purpose |
|------|---------|
| `App.tsx` | Main app, WebSocket management, recording + playback |
| `components/VoiceOrb.tsx` | Audio-reactive Three.js particle visualization |
| `components/Settings.tsx` | Configuration panel |
| `components/Onboarding.tsx` | First-run setup |
| `bubble.tsx` | Floating desktop bubble UI (`/bubble.html`) |
| `panel/Panel.tsx` | Main panel with tabbed views |
| `panel/views/` | Chat, Memory, Files, Models, Plugins, Settings, Tools, Tasks, Automation, Adaptive, Proactive, Security, Performance |
| `api/` | Typed API clients for all backend routes |
| `main.tsx` | React entry point |

### Desktop — `electron/`

`main.js` spawns the FastAPI backend, manages the main window + floating bubble + tray, stores API keys via OS keychain (keytar), and handles auto-updates. `preload.js` exposes a safe IPC bridge (session token, wake word, etc.).

## WebSocket Protocol

Connect to `ws://<host>:8000/ws/voice?token=<SESSION_TOKEN>`.

The token is generated at startup (or set via `SESSION_TOKEN` env var). Invalid/missing tokens are closed with code `4001`.

**Client → Server**
```json
{ "type": "text", "content": "What is the weather today?" }
{ "type": "audio", "audio_base64": "<base64 WAV PCM16 mono 16kHz>" }
```

**Server → Client**
```json
{ "type": "status", "status": "transcribing|processing|generating_speech" }
{ "type": "partial", "text": "The weather to..." }
{ "type": "audio_queue", "count": 3 }
{ "type": "audio_segment_start" }
{ "type": "audio_chunk", "chunk": "<base64>" }
{ "type": "audio_segment_end" }
{ "type": "response", "text": "The weather today is sunny.", "audio": null }
{ "type": "error", "message": "..." }
```

## REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/api/system/info` | CPU, memory, disk, processes |
| `POST` | `/api/system/execute` | Run an allowlisted command (token-protected) |
| `GET` | `/api/memory/{session_id}` | Conversation history |
| `POST` | `/api/mail/auth` | Authenticate IMAP/SMTP, returns token |
| `GET` | `/api/mail/inbox` | Recent emails |
| `GET` | `/api/mail/unread` | Unread emails |
| `POST` | `/api/notes` | Create a note |
| `GET` | `/api/notes` | List notes |
| `GET` | `/api/calendar/events` | Upcoming events |
| `POST` | `/api/llm/generate` | Generate text from configured provider |
| `POST` | `/api/llm/rerank` | Rerank passages (NVIDIA) |
| `POST` | `/api/stt/transcribe` | Transcribe base64 WAV to text |
| `GET` | `/api/stt/status` | STT availability |
| `GET/POST` | `/api/settings/keys` | Read/update masked `.env` keys |
| `GET/POST` | `/api/vision/screenshot` | Capture screenshot |
| `POST` | `/api/vision/ocr` | OCR on base64 image |
| `POST` | `/api/vision/analyze` | LLM-powered image analysis |
| `GET` | `/api/vision/windows` | List open windows |
| `GET/POST` | `/api/tasks/` | List/create tasks, reminders, jobs |
| `GET/PATCH/DELETE` | `/api/tasks/{id}` | Get/update/delete task |
| `POST` | `/api/tasks/{id}/complete` | Mark task complete |
| `GET/POST` | `/api/automation/workflows` | List/create workflows |
| `POST` | `/api/automation/workflows/{id}/execute` | Execute workflow |
| `DELETE` | `/api/automation/workflows/{id}` | Delete workflow |
| `GET` | `/api/adaptive/behavior` | Behavior pattern analysis |
| `GET` | `/api/adaptive/insights` | Adaptive intelligence insights |
| `GET` | `/api/adaptive/suggestions` | Predictive suggestions |
| `POST` | `/api/adaptive/learn` | Learn from interaction |
| `POST` | `/api/adaptive/feedback` | Record prediction feedback |
| `GET` | `/api/proactive/suggestions` | Proactive AI suggestions |
| `POST` | `/api/proactive/notifications` | Create smart notification |
| `GET` | `/api/security/status` | Security posture |
| `GET/POST` | `/api/security/privacy` | Privacy settings |
| `GET` | `/api/security/export` | Export user data |
| `DELETE` | `/api/security/data` | Delete all user data |
| `GET` | `/api/performance/metrics` | Request metrics |
| `GET` | `/api/performance/health` | System health |

Interactive docs: `http://localhost:8000/docs`.

## Docker Deployment

```bash
cp jarvis_backend/.env.example .env   # add API keys
docker-compose up -d
```

Access at `http://localhost:8000` (backend serves the built frontend).

## Development

### Backend

```bash
cd jarvis_backend
source venv/bin/activate
python main.py        # Uvicorn with auto-reload

# Tests
venv/bin/python -m pytest jarvis_backend/tests/ -v
ruff check jarvis_backend/
black --check jarvis_backend/
```

### Frontend

```bash
cd jarvis_frontend
npx tsc --noEmit
npx vitest run
npx eslint . --ext .ts,.tsx
npx prettier --check "src/**/*.{ts,tsx}"
```

## Extending JARVIS

### Add a New Skill

1. Create or use a module in `jarvis_backend/modules/`
2. Register a `Skill` in `routes/state.py`:
   ```python
   skill_registry.register(
       Skill(
           "weather",
           ["weather", "forecast", "temperature"],
           _skill_weather,
           "Weather lookups",
       )
   )
   ```
3. The LLM receives the skill output in context and answers naturally.

### Add a New Panel View

1. Create a view component in `jarvis_frontend/src/panel/views/`
2. Export it from `src/panel/views/index.ts`
3. Add the view type to `PanelView` in `src/panel/Panel.tsx`
4. Wire it into the `VIEWS` array and the render switch

### Add a New Backend Manager

1. Create a manager in `jarvis_backend/managers/`
2. Wire the singleton in `routes/state.py`
3. Add routes in `jarvis_backend/routes/`
4. Include the router in `main.py`
5. Add an API client in `jarvis_frontend/src/api/`

## Troubleshooting

### No Sound Output
- No ElevenLabs key? Edge TTS is used automatically (no key needed).
- Final fallback: `apt-get install espeak-ng` (or `piper`).

### Voice Input Doesn't Transcribe
- Install the Vosk model: `bash scripts/download-vosk-model.sh`
- Or set `OPENAI_API_KEY` for cloud transcription fallback.
- Check `GET /api/stt/status`.

### WebSocket Connection Failed
- Ensure the backend is running on `http://localhost:8000`.
- In dev, the frontend proxies `/ws` to the backend — check `vite.config.ts`.
- Verify the session token matches (`SESSION_TOKEN` or generated at startup).

### Email Not Working
- Gmail: enable IMAP and use an App Password (not your regular password).

## Documentation

- `QUICKSTART.md` — setup guide
- `ARCHITECTURE.md` — detailed code overview
- `WS_PROTOCOL.md` — full WebSocket protocol
- `DEPLOYMENT.md` — deployment & release process
- `FILE_MANIFEST.md` — file-by-file breakdown

## License

MIT License — See LICENSE file for details.

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com) — Web framework
- [React](https://react.dev) — UI framework
- [Three.js](https://threejs.org) — 3D visualization
- [Electron](https://www.electronjs.org) — desktop shell
- [Vosk](https://alphacephei.com/vosk/) — offline speech recognition
- [Mistral AI](https://mistral.ai) — LLM
- [Anthropic](https://anthropic.com) — LLM fallback
- [ElevenLabs](https://elevenlabs.io) — Text-to-speech
