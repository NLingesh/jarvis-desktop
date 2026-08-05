# JARVIS — Voice AI Assistant

A production-ready voice-first AI assistant for Linux that integrates with your calendar, email, notes, and the web. Powered by Mistral-4b with streaming support, built with FastAPI + React + Three.js.

## Features

- 🎤 **Voice Input/Output** — Hands-free interaction using Web Speech API + ElevenLabs TTS streaming
- 📅 **Calendar Integration** — Access and manage your calendar events via voice
- 📧 **Email Management** — Read, send, and manage emails by voice
- 📝 **Notes** — Create and organize notes through natural conversation
- 🌐 **Web Browsing** — Search the web and fetch information
- 🖥️ **System Info** — Monitor CPU, memory, disk, and processes
- 🔊 **Audio-Reactive Orb** — Three.js particle visualization that reacts to audio
- 💬 **Conversation Memory** — SQLite with FTS5 for fast full-text search
- ⚡ **Streaming Responses** — Real-time text and audio chunks for low-latency interaction
- 🤖 **Provider-Agnostic LLM** — Supports Mistral (primary) and Anthropic (fallback)
- 🎯 **NVIDIA Reranking** — Optional semantic reranking for better search results
- 🔒 **Privacy-First** — All conversations stored locally

## Architecture

```
Microphone → Web Speech API → WebSocket → FastAPI (Python)
↓
Mistral-4b API (with streaming)
↓
ElevenLabs TTS (streaming) → Browser Speaker

Alternative: Anthropic (Claude) if MISTRAL provider unavailable
Optional: NVIDIA Reranker for semantic search
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | Python 3.11+, FastAPI, SQLite with FTS5 |
| **Frontend** | TypeScript, React, Vite, Three.js |
| **Communication** | WebSocket with JSON + base64 audio streaming |
| **AI - Primary** | Mistral-4b (via mistral.ai API) |
| **AI - Fallback** | Claude Haiku (Anthropic) |
| **Reranking** | NVIDIA Reranker (optional) |
| **TTS** | ElevenLabs (with espeak-ng fallback) |
| **Containerization** | Docker & Docker Compose |

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (optional)
- **MISTRAL_API_KEY** (primary) — get from https://console.mistral.ai/
- **or ANTHROPIC_API_KEY** (fallback) — get from https://console.anthropic.com/
- **ELEVENLABS_API_KEY** (optional) — get from https://elevenlabs.io/

## Quick Start

### 1. Clone and Setup

```bash
# Clone the repository
git clone <repo-url>
cd jarvis

# Create environment file
cp jarvis_backend/.env.example jarvis_backend/.env
# Edit .env and add your Mistral and/or Anthropic API keys
```

### 2. Backend Setup

```bash
cd jarvis_backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py
```

The backend will start on `http://localhost:8000`

### 3. Frontend Setup

```bash
cd jarvis_frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will start on `http://localhost:5173`

### 4. Access JARVIS

Open your browser to `http://localhost:5173`

## Docker Deployment

### Using Docker Compose (Recommended)

```bash
# Create .env file with your API keys
cp jarvis_backend/.env.example .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f
```

Access at `http://localhost:5173`

### Manual Docker Build

```bash
# Build backend
cd jarvis_backend
docker build -t jarvis-backend .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your_key jarvis-backend

# Build frontend
cd jarvis_frontend
docker build -t jarvis-frontend .
docker run -p 5173:5173 jarvis-frontend
```

## Configuration

### Backend (.env file)

```bash
ANTHROPIC_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here  # Optional
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
LOG_LEVEL=INFO
```

### Frontend Settings

Access Settings (⚙️) in the UI to configure:
- Voice language and speed
- TTS volume
- Theme (light/dark)
- Server URL
- Email integration

## Usage

### Voice Mode

1. **Click the microphone button** (🎤)
2. **Speak your command** — the system will transcribe and process
3. **Wait for response** — Claude processes and responds with voice + text

### Text Mode

1. **Type in the text field** at the bottom
2. **Press Enter or click Send** (✉️)
3. **Get instant response** with voice feedback

### Example Commands

```
"What's on my calendar tomorrow?"
"Send an email to john@example.com saying hello"
"Create a note: Remember to buy groceries"
"Search for Python best practices"
"What's my system CPU usage?"
"Translate 'hello' to Spanish"
"What's the weather like?"
```

## Module Structure

### Backend Modules

- **`memory.py`** — Conversation history, SQLite FTS5 search, note storage
- **`claude_api.py`** — Claude Haiku integration with context awareness
- **`tts.py`** — ElevenLabs text-to-speech with system fallback
- **`calendar_module.py`** — Evolution/GNOME Calendar integration
- **`mail_module.py`** — IMAP/SMTP email access
- **`notes_module.py`** — Local JSON-based note storage
- **`web_browse.py`** — DuckDuckGo search, weather, news, translation
- **`system_actions.py`** — CPU, memory, disk, process monitoring

### Frontend Components

- **`App.tsx`** — Main application container, WebSocket management
- **`VoiceOrb.tsx`** — Audio-reactive Three.js particle visualization
- **`ChatInterface.tsx`** — Message display and text input
- **`Settings.tsx`** — Configuration panel

## API Endpoints

### WebSocket

```
ws://localhost:8000/ws/voice
```

**Message Format:**
```json
{
  "type": "text",
  "content": "Your message here"
}
```

**Response Format:**
```json
{
  "type": "response",
  "text": "Claude's response",
  "audio": "base64_encoded_audio"
}
```

### REST Endpoints

- `GET /health` — Server health check
- `GET /api/calendar/events` — Get upcoming events
- `GET /api/mail/inbox` — Get recent emails
- `POST /api/notes` — Create a note
- `GET /api/memory/{session_id}` — Get conversation history

## Performance Tips

- **Use Claude Haiku** for 10x faster responses than Sonnet
- **SQLite FTS5** is faster than vector DBs for memory search (no infrastructure needed)
- **WebSocket** over HTTP reduces latency significantly for voice
- **Additive blending** in Three.js transforms the particle orb visuals

## Troubleshooting

### No Sound Output
- Check if ElevenLabs API key is set
- Fallback uses `espeak` on Linux — install with `apt-get install espeak`
- Check browser audio permissions

### WebSocket Connection Failed
- Ensure backend is running on `http://localhost:8000`
- Check if proxy settings in `vite.config.ts` are correct
- Try accessing `/health` in browser

### Email Not Working
- For Gmail: Use an App Password (not your regular password)
- Enable IMAP in Gmail settings
- Check email credentials in Settings panel

### Microphone Not Working
- Grant microphone permissions in browser
- Check if another app is using the microphone
- Try a different browser

## Development

### Backend Development

```bash
cd jarvis_backend
source venv/bin/activate
pip install -r requirements.txt
python main.py  # Runs with auto-reload via Uvicorn
```

### Frontend Development

```bash
cd jarvis_frontend
npm run dev  # Runs with hot module replacement
```

### Database Inspection

```bash
# Connect to SQLite database
sqlite3 jarvis_memory.db

# View conversations
SELECT * FROM conversations LIMIT 10;

# Search full-text
SELECT * FROM conversations_fts 
WHERE conversations_fts MATCH 'calendar';
```

## Extending JARVIS

### Add a New Module

1. Create a new file in `jarvis_backend/modules/`
2. Implement your functionality as an async class
3. Import in `main.py`
4. Add processing logic in `process_command()`

### Add a New Voice Command

Edit the `process_command()` function in `main.py`:

```python
async def process_command(user_input: str) -> dict:
    user_lower = user_input.lower()
    
    if "your trigger words" in user_lower:
        context["your_key"] = await your_module.get_data()
    
    return context
```

## Deployment

### Production Setup

1. **Update `.env`** with production API keys
2. **Set `DEBUG=False`** in environment
3. **Use a reverse proxy** (nginx) in front of FastAPI
4. **Run behind HTTPS** with valid certificates
5. **Use managed TTS service** for reliability

### Example Nginx Config

```nginx
server {
    listen 443 ssl;
    server_name jarvis.example.com;
    
    ssl_certificate /path/to/cert;
    ssl_certificate_key /path/to/key;
    
    location / {
        proxy_pass http://localhost:5173;
    }
    
    location /ws/voice {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    location /api {
        proxy_pass http://localhost:8000;
    }
}
```

## Contributing

Contributions welcome! Areas for improvement:

- Additional calendar integrations (Outlook, Caldav)
- Real-time transcription improvements
- Multi-language support
- Custom wake words
- Integration with more email providers
- Desktop app (Electron/Tauri)

## License

MIT License — See LICENSE file for details

## Support

- Issues: GitHub Issues
- Documentation: Full API docs at `/docs` (FastAPI Swagger)
- Community: Discord server (coming soon)

## Credits

Built with:
- [Claude API](https://anthropic.com) — LLM backbone
- [FastAPI](https://fastapi.tiangolo.com) — Web framework
- [React](https://react.dev) — UI framework
- [Three.js](https://threejs.org) — 3D visualization
- [ElevenLabs](https://elevenlabs.io) — Text-to-speech

---

Made with ❤️ for hands-free productivity
