# JARVIS Setup Guide

## ⚡ Quick Start

### One-Command Launch (Recommended)

```bash
# 1. Copy environment file and add your API keys
cp jarvis_backend/.env.example jarvis_backend/.env
# Edit jarvis_backend/.env with your keys

# 2. Launch everything
./start.sh        # Mac / Linux
start.bat         # Windows
```

That's it. The script will:
- Create the Python virtual environment if missing
- Install backend dependencies
- Build the frontend if needed
- Start the server on `http://localhost:8000`
- Open your browser automatically

To stop it later:
```bash
kill $(lsof -ti:8000)
```

## 📦 What You've Got

Complete source code for JARVIS - a voice-first AI assistant. All files are ready to use with no additional configuration except API keys.

### File Structure

```
.
├── jarvis_backend/          # Python FastAPI backend
│   ├── main.py              # Main server with WebSocket
│   ├── requirements.txt      # Python dependencies
│   ├── .env.example          # Environment template
│   ├── Dockerfile            # Docker image
│   └── modules/              # Core functionality modules
│       ├── memory.py         # Conversation storage + search
│       ├── claude_api.py      # Claude integration
│       ├── tts.py            # Text-to-speech
│       ├── calendar_module.py # Calendar integration
│       ├── mail_module.py     # Email access
│       ├── notes_module.py    # Note management
│       ├── web_browse.py      # Web search
│       ├── system_actions.py  # System monitoring
│       └── documents_module.py # Document control
│
├── jarvis_frontend/         # React + Three.js frontend
│   ├── src/
│   │   ├── App.tsx           # Main React app
│   │   ├── App.css           # Styling
│   │   ├── main.tsx          # Entry point
│   │   └── components/
│   │       ├── VoiceOrb.tsx   # Audio-reactive orb
│   │       ├── ChatInterface.tsx  # Message display
│   │       └── Settings.tsx   # Configuration panel
│   ├── index.html            # HTML template
│   ├── package.json          # Node dependencies
│   ├── vite.config.ts        # Build config
│   ├── tsconfig.json         # TypeScript config
│   └── Dockerfile            # Docker image
│
├── start.sh                  # One-command launcher (Mac/Linux)
├── start.bat                 # One-command launcher (Windows)
├── docker-compose.yml        # Full stack deployment
├── setup.sh                  # Automated setup script
├── JARVIS_README.md          # Full documentation
└── .gitignore               # Git ignore rules
```

## 🔧 For Development

If you want to run the backend and frontend separately for hot-reloading:

### Backend Setup

```bash
cd jarvis_backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Copy and edit environment file
cp .env.example .env
# Edit .env with your API keys:
# ANTHROPIC_API_KEY=your_key_here
# ELEVENLABS_API_KEY=your_key_here (optional)

# Install dependencies
pip install -r requirements.txt

# Run server
python main.py
```

Server starts at `http://localhost:8000`

### Frontend Setup (in another terminal)

```bash
cd jarvis_frontend

# Install dependencies
npm install

# Run dev server
npm run dev
```

Frontend starts at `http://localhost:5173` and proxies `/api` to the backend.

## 🔑 Get API Keys (Required)

### 1. Mistral API Key (Primary)
- Visit: https://console.mistral.ai/
- Create new API key
- Add to `.env` as `MISTRAL_API_KEY=your_key`

### 2. Anthropic API Key (Fallback)
- Visit: https://console.anthropic.com/
- Create new API key
- Add to `.env` as `ANTHROPIC_API_KEY=your_key`

### 3. ElevenLabs API Key (Optional)
- Visit: https://elevenlabs.io/
- Create account and get API key
- Add to `.env` as `ELEVENLABS_API_KEY=your_key`
- If not set, uses system TTS (espeak on Linux)

## 🎤 Using JARVIS

1. **Open browser** to http://localhost:8000
2. **Say "JARVIS"** to wake the assistant
3. **Speak your command** — system transcribes it
4. **Get response** — LLM processes and responds with voice + text

### Example Commands

```
"What's on my calendar tomorrow?"
"Send an email to john@example.com"
"Create a note: Buy groceries"
"Search for Python best practices"
"What's my CPU usage?"
"Open my document notes.txt"
"Create a document called ideas.md"
```

## 📋 Requirements

- **Python 3.11+** — for backend
- **Node.js 18+** — for frontend (only needed for `npm run build` / dev mode)
- **Modern browser** with WebRTC support
- **Microphone** — for voice input
- **Internet connection** — for APIs

## 🐳 Docker Requirements

- **Docker** — Install from https://docker.com
- **Docker Compose** — Usually included with Docker

## 🔧 Troubleshooting

### Server Won't Start
```bash
# Check backend logs
cd jarvis_backend
python main.py

# Verify Python version
python3 --version
```

### Frontend Not Loading
```bash
# Rebuild frontend
cd jarvis_frontend
npm run build

# Or clear and rebuild
rm -rf dist node_modules
npm install
npm run build
```

### WebSocket Connection Failed
```bash
# Check backend is running
curl http://localhost:8000/health

# Check firewall isn't blocking port 8000
```

### No Sound Output
```bash
# Install espeak for Linux
sudo apt-get install espeak

# Or add ElevenLabs API key to .env
```

### Microphone Not Working
1. Check browser permissions (look for 🔒 icon in address bar)
2. Try a different browser
3. Check `/dev/audio` permissions on Linux

### Email Not Working
- For Gmail: Use App Password (not regular password)
- Enable IMAP in Gmail settings
- Check credentials in Settings panel

## 📚 Core Features Explained

### 1. Voice Assistant Core
- Web Speech API for transcription
- Mistral/Claude for fast responses
- ElevenLabs for natural TTS with fallback to system `espeak`
- WebSocket for real-time latency (not HTTP)

### 2. Memory System
- SQLite with FTS5 (Full-Text Search)
- Stores all conversations locally
- No vector database needed — FTS5 is faster
- Sessions for managing multiple conversations

### 3. Integrations
- **Calendar**: Evolution/GNOME Calendar on Linux
- **Email**: IMAP/SMTP (Gmail recommended)
- **Notes**: Local JSON storage
- **Documents**: Read/write/edit files in ~/Documents/jarvis
- **Web**: DuckDuckGo search, weather, translation
- **System**: CPU, memory, disk, processes

### 4. Frontend UI
- Installable PWA (Add to Home Screen)
- Orb-only default, compact bottom-sheet on wake word
- Audio-reactive Three.js particle orb
- Settings panel for configuration
- Dark theme optimized for night usage

## 🚀 Production Deployment

### Using Docker Compose
```bash
# Create .env with production keys
cp jarvis_backend/.env.example .env
# Edit .env with your API keys

# Start services
docker-compose up -d

# View logs
docker-compose logs -f
```

Access at `http://localhost:8000`

### Using Nginx Reverse Proxy
```nginx
upstream jarvis_backend {
    server localhost:8000;
}

server {
    listen 443 ssl;
    server_name jarvis.example.com;
    
    ssl_certificate /etc/ssl/certs/cert.pem;
    ssl_certificate_key /etc/ssl/private/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
    }
    
    location /ws/voice {
        proxy_pass http://jarvis_backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## 📖 Next Steps

1. **Read** `JARVIS_README.md` for full documentation
2. **Explore** the modules in `jarvis_backend/modules/`
3. **Customize** components in `jarvis_frontend/src/`
4. **Deploy** using Docker Compose to production

## 🛠️ Development

### Adding New Voice Commands

Edit `jarvis_backend/main.py`, in the `process_command()` function:

```python
async def process_command(user_input: str, session_id: Optional[str] = None) -> dict:
    user_lower = user_input.lower()
    
    if "your keywords" in user_lower:
        context["your_key"] = await your_module.get_data()
    
    return context
```

### Adding New Integrations

1. Create new module: `jarvis_backend/modules/your_module.py`
2. Implement async functions
3. Import and use in `main.py`
4. Test via WebSocket

### Customizing the UI

React components are in `jarvis_frontend/src/components/`. Edit colors in `App.css`.

## 📞 Support

- **Issues**: Check logs
- **Docs**: Read `JARVIS_README.md`
- **API Docs**: http://localhost:8000/docs (FastAPI Swagger)

## 📄 License

MIT — Free to use, modify, and distribute
