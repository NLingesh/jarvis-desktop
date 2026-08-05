# JARVIS Source Code - File Manifest

Generated: June 20, 2026  
Total Files: 30  
Total Code Lines: ~3,500+

## 📂 Project Structure

### Backend (`jarvis_backend/`)

**Core Server**
- `main.py` (340 lines) - FastAPI server, WebSocket handler, command processor

**Modules** (`modules/`)
- `__init__.py` - Package initialization
- `memory.py` (240 lines) - SQLite conversation storage with FTS5
- `claude_api.py` (90 lines) - Claude Haiku integration
- `tts.py` (140 lines) - ElevenLabs + fallback TTS
- `calendar_module.py` (200 lines) - Calendar integration (Evolution/GNOME)
- `mail_module.py` (250 lines) - IMAP/SMTP email access
- `notes_module.py` (190 lines) - JSON-based note storage
- `web_browse.py` (220 lines) - Web search, weather, translation APIs
- `system_actions.py` (230 lines) - System monitoring (CPU, memory, disk, processes)

**Configuration**
- `requirements.txt` - Python dependencies (13 packages)
- `.env.example` - Environment variables template
- `Dockerfile` - Docker image definition

### Frontend (`jarvis_frontend/`)

**Main Application**
- `src/App.tsx` (280 lines) - React app container, WebSocket management
- `src/App.css` (600 lines) - Complete styling (dark theme)
- `src/main.tsx` (10 lines) - React entry point
- `src/vite-env.d.ts` (80 lines) - TypeScript type definitions

**Components** (`src/components/`)
- `VoiceOrb.tsx` (240 lines) - Three.js audio-reactive particle orb
- `ChatInterface.tsx` (70 lines) - Message display + text input
- `Settings.tsx` (240 lines) - Configuration panel

**Build Configuration**
- `index.html` - HTML template
- `package.json` - Node.js dependencies (React, Three.js, TypeScript)
- `vite.config.ts` - Vite build configuration
- `tsconfig.json` - TypeScript compiler options
- `tsconfig.node.json` - Node-specific TypeScript config
- `Dockerfile` - Multi-stage Docker image

### Deployment & Documentation

**Deployment**
- `docker-compose.yml` - Full stack Docker setup

**Documentation**
- `JARVIS_README.md` (450 lines) - Complete documentation
- `QUICKSTART.md` (280 lines) - Quick start guide
- `ARCHITECTURE.md` (500 lines) - Architecture & code overview
- `FILE_MANIFEST.md` (this file) - File listing

**Utilities**
- `setup.sh` (100 lines) - Automated setup script
- `.gitignore` - Git ignore rules

## 📊 Code Statistics

### Backend Python Code
```
main.py             ~340 lines
memory.py           ~240 lines
claude_api.py       ~90 lines
tts.py              ~140 lines
calendar_module.py  ~200 lines
mail_module.py      ~250 lines
notes_module.py     ~190 lines
web_browse.py       ~220 lines
system_actions.py   ~230 lines
─────────────────────────────
Total Backend:      ~1,700 lines
```

### Frontend TypeScript/React Code
```
App.tsx             ~280 lines
VoiceOrb.tsx        ~240 lines
ChatInterface.tsx   ~70 lines
Settings.tsx        ~240 lines
App.css             ~600 lines
─────────────────────────────
Total Frontend:     ~1,430 lines
```

### Configuration Files
```
package.json        ~30 lines
vite.config.ts      ~25 lines
tsconfig.json       ~20 lines
requirements.txt    ~15 lines
docker-compose.yml  ~50 lines
─────────────────────────────
Total Config:       ~140 lines
```

## 🎯 Key Features by File

### Backend Modules

| File | Purpose | Key Classes/Functions | Dependencies |
|------|---------|----------------------|--------------|
| memory.py | Conversation storage | MemoryManager | sqlite3 |
| claude_api.py | LLM integration | ClaudeAPI | anthropic |
| tts.py | Text-to-speech | TextToSpeechModule | httpx, subprocess |
| calendar_module.py | Calendar access | CalendarModule | subprocess |
| mail_module.py | Email management | MailModule | imaplib, email |
| notes_module.py | Note storage | NotesModule | json, os |
| web_browse.py | Web integration | WebBrowseModule | httpx, beautifulsoup4 |
| system_actions.py | System monitoring | SystemActions | psutil, subprocess |

### Frontend Components

| File | Purpose | Technologies | Size |
|------|---------|--------------|------|
| VoiceOrb.tsx | 3D visualization | Three.js, WebGL | 240 lines |
| ChatInterface.tsx | Message display | React hooks | 70 lines |
| Settings.tsx | Configuration | React forms | 240 lines |
| App.tsx | Main container | WebSocket, Web Speech API | 280 lines |

## 🔧 Technologies Used

### Backend Stack
- **Framework**: FastAPI 0.104.1
- **Server**: Uvicorn
- **Database**: SQLite3 with FTS5
- **AI**: Anthropic Claude Haiku
- **TTS**: ElevenLabs + espeak
- **HTTP**: httpx (async)
- **System**: psutil
- **Parsing**: BeautifulSoup4

### Frontend Stack
- **UI Framework**: React 18
- **Build Tool**: Vite
- **Language**: TypeScript 5.2
- **3D Graphics**: Three.js r156
- **Styling**: CSS3 with variables
- **APIs**: Web Speech API, Web Audio API, Fetch API

### DevOps
- **Containerization**: Docker
- **Orchestration**: Docker Compose
- **Package Manager**: npm (Node), pip (Python)

## 📦 Dependencies Summary

### Python (13 packages)
```
fastapi==0.104.1
uvicorn==0.24.0
anthropic==0.7.1
httpx==0.25.1
beautifulsoup4==4.12.2
psutil==5.9.6
python-dotenv==1.0.0
```

### Node.js (4 core packages)
```
react@^18.2.0
react-dom@^18.2.0
three@^r156
typescript@^5.2.0
vite@^5.0.0
```

## 🚀 Deployment Options

### Local Development
```bash
./setup.sh          # Automated setup
# or manual setup via QUICKSTART.md
```

### Docker Single Container
```bash
docker build -t jarvis-backend jarvis_backend/
docker run -p 8000:8000 jarvis-backend
```

### Docker Compose (Recommended)
```bash
docker-compose up -d
```

### Kubernetes
Deploy using manifests (not included, but easy to generate)

### Cloud Platforms
- **AWS**: ECS, App Runner, Lambda
- **Google Cloud**: Cloud Run, Cloud Functions
- **Azure**: App Service, Container Instances
- **Heroku**: Container Registry deployment

## 📋 File Checklist

Backend Files:
- [x] main.py
- [x] requirements.txt
- [x] .env.example
- [x] Dockerfile
- [x] modules/__init__.py
- [x] modules/memory.py
- [x] modules/claude_api.py
- [x] modules/tts.py
- [x] modules/calendar_module.py
- [x] modules/mail_module.py
- [x] modules/notes_module.py
- [x] modules/web_browse.py
- [x] modules/system_actions.py

Frontend Files:
- [x] index.html
- [x] src/main.tsx
- [x] src/App.tsx
- [x] src/App.css
- [x] src/vite-env.d.ts
- [x] src/components/VoiceOrb.tsx
- [x] src/components/ChatInterface.tsx
- [x] src/components/Settings.tsx
- [x] package.json
- [x] vite.config.ts
- [x] tsconfig.json
- [x] tsconfig.node.json
- [x] Dockerfile

Config & Deployment:
- [x] docker-compose.yml
- [x] setup.sh
- [x] .gitignore

Documentation:
- [x] JARVIS_README.md
- [x] QUICKSTART.md
- [x] ARCHITECTURE.md
- [x] FILE_MANIFEST.md (this file)

## 🔍 Code Quality

### Design Patterns Used
- **Async/Await**: Non-blocking I/O throughout
- **Dependency Injection**: Modules initialized in main.py
- **Context Manager**: Proper resource cleanup
- **Observer Pattern**: WebSocket event handlers
- **Factory Pattern**: Session creation
- **Singleton Pattern**: Database connections

### Best Practices
- Type hints in TypeScript and Python (where applicable)
- Docstrings for public methods
- Error handling with try-catch/except
- Environment variables for sensitive data
- Logging for debugging
- CORS configuration
- Input validation

### Security Features
- API key management via .env
- SQL injection prevention (parameterized queries)
- HTTPS-ready (use with reverse proxy)
- WebSocket over WSS in production
- Rate limiting ready (add middleware)
- CORS filtering

## 📚 Learning Resources

By studying this code, you'll learn:

1. **Backend**: FastAPI, WebSockets, SQLite, async Python
2. **Frontend**: React with TypeScript, Three.js, Web APIs
3. **AI Integration**: Claude API, streaming responses
4. **Full-Stack**: How voice AI systems work end-to-end
5. **DevOps**: Docker, Docker Compose, containerization
6. **Real-Time Communication**: WebSocket optimization

## 🎓 Extension Ideas

- Add authentication (JWT tokens)
- Implement plugin system for modules
- Add multi-user support
- Create web dashboard
- Mobile app (React Native)
- Desktop app (Electron/Tauri)
- Additional integrations (Slack, Jira, etc.)
- Advanced analytics
- Model fine-tuning pipeline

## 📄 License & Attribution

All code is MIT Licensed - free to use and modify.

Built with:
- Claude API by Anthropic
- FastAPI community
- React ecosystem
- Three.js community
- Docker community

---

**Ready to deploy?** Start with `QUICKSTART.md` or run `./setup.sh`!
