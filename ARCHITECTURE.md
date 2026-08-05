# JARVIS Architecture & Code Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (React + Three.js)                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ VoiceOrb (Particle Visualization)                       │ │
│  │ ChatInterface (Messages + Text Input)                   │ │
│  │ Web Speech API (Microphone Input)                       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                         ↓ WebSocket                           │
│                   Base64 Audio + JSON                         │
│                         ↓                                      │
│                     localhost:8000                            │
└─────────────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────────┐
        │    FastAPI Server (Python)              │
        ├─────────────────────────────────────────┤
        │ main.py                                 │
        │ - WebSocket endpoint (/ws/voice)        │
        │ - REST endpoints (/api/*)               │
        │ - Session management                    │
        └─────────────────────────────────────────┘
            ↓ (processes) ↓ (stores) ↓ (searches)
    ┌──────────────────────────────────────────┐
    │    Backend Modules                       │
    ├──────────────────────────────────────────┤
    │ memory.py           → SQLite FTS5              │
    │ llm_provider.py    → Mistral (primary)        │
    │ claude_api.py      → Anthropic (fallback)      │
    │ tts.py             → ElevenLabs / espeak        │
    │ calendar_module.py → Evolution Calendar         │
    │ mail_module.py     → IMAP/SMTP                  │
    │ notes_module.py    → JSON files                │
    │ web_browse.py      → DuckDuckGo / APIs         │
    │ system_actions.py  → psutil                    │
    └──────────────────────────────────────────┘
```

## Backend Architecture (FastAPI + Python)

### main.py - Server Entry Point

**Responsibilities:**
- FastAPI application setup
- WebSocket connection management
- Session creation and tracking
- Command processing and routing
- Context building for Claude

**Key Functions:**
```python
websocket_endpoint()      # WebSocket handler
process_command()         # Parse user input & gather context
```

**Flow:**
1. User sends message via WebSocket
2. Server adds to memory
3. Context is gathered (calendar, emails, etc.)
4. LLMProvider (Mistral/Anthropic) generates response
5. TTS converts to audio
6. Both text + audio sent back to client

### memory.py - Conversation Storage

**Technology:** SQLite with FTS5 (Full-Text Search 5)

**Tables:**
- `conversations` - Stores all messages
- `conversations_fts` - FTS5 index for full-text search
- `sessions` - User session tracking
- `notes` - Local note storage

**Key Methods:**
```python
create_session()          # Create new conversation session
add_message()            # Store message in DB
get_conversation()       # Retrieve chat history
search_memory()          # FTS5 full-text search
create_note()            # Save a note
```

**Why SQLite FTS5?**
- Zero infrastructure (no vector DB needed)
- Faster than vector searches for text
- Persistent local storage
- No API costs
- Easy to backup/restore

### llm_provider.py - LLM Integration

**Architecture:** `LLMProvider` is the single integration point. `MISTRAL_API_KEY` drives the primary Mistral chat-completions path; `modules/claude_api.py` (`ClaudeAPI`) is used as a fallback when `LLM_PROVIDER=anthropic`.

**Key Methods:**
```python
get_response()           # Single message from the configured provider
stream_response()        # Async generator yielding text chunks
rerank()               # Semantic reranking via NVIDIA endpoint
```

**Environment Variables:**
- `LLM_PROVIDER` (`mistral` | `anthropic`, default `mistral`)
- `MISTRAL_API_KEY`, `MISTRAL_MODEL` (`mistral-4b`), `MISTRAL_API_URL` (`https://api.mistral.ai`)
- `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` (fallback; default `claude-3-haiku-20240307`)

**Resilience:**
- Retries with backoff on 5xx; returns a `str` error on non-200 (never a `dict`)
- Graceful degradation when no API key is configured

### tts.py - Text-to-Speech

**Priority Stack:**
1. ElevenLabs API (if key provided) - Natural British voice
2. System `espeak` - Linux fallback
3. System `say` - macOS fallback

**Returns:** Base64-encoded audio for WebSocket transmission

**Key Methods:**
```python
generate_speech()        # Main TTS generator
_elevenlabs_tts()       # ElevenLabs API call
_system_tts()           # Fallback to espeak/say
_to_base64()            # Encode for transmission
```

### calendar_module.py - Calendar Integration

**Supported:** Evolution (GNOME Calendar), with mock data fallback

**Key Methods:**
```python
get_upcoming_events()    # Next 7 days of events
create_event()           # Add new event
check_availability()     # Check if slot is free
find_available_slot()    # Find next open time
```

**Integrations:**
- Evolution: Reads from ~/.local/share/evolution/calendar/
- GNOME Calendar: Reads from ~/.local/share/gnome-calendar/
- Mock data: Returns demo events for testing

### mail_module.py - Email Access

**Protocol:** IMAP/SMTP (tested with Gmail)

**Key Methods:**
```python
authenticate()           # Login to email
get_recent_emails()     # Fetch recent messages
get_unread_emails()     # Get unread count
send_email()            # Send new email
mark_as_read()          # Mark as read
delete_email()          # Delete message
```

**Gmail Setup:**
1. Enable 2-factor authentication
2. Create App Password (https://myaccount.google.com/apppasswords)
3. Use app password (not regular password)

### notes_module.py - Note Storage

**Storage:** JSON files in `~/.jarvis/notes/`

**Structure:**
```json
{
  "id": "abc123",
  "title": "Shopping list",
  "content": "Buy milk, eggs, bread",
  "tags": ["shopping", "todo"],
  "created_at": "2024-06-20T10:30:00",
  "modified_at": "2024-06-20T10:30:00"
}
```

**Key Methods:**
```python
create_note()            # Save new note
get_notes()             # List all notes
update_note()           # Edit existing note
delete_note()           # Remove note
search_notes()          # Find by title/content/tags
```

### web_browse.py - Web Integration

**Services:**
- **Search:** DuckDuckGo API (no key needed)
- **Weather:** Open-Meteo API (no key needed)
- **Translation:** MyMemory API (no key needed)
- **News:** NewsAPI (optional)

**Key Methods:**
```python
search()                # Web search
fetch_url()             # Get page content
get_weather()           # Weather lookup
get_news()              # News articles
translate_text()        # Language translation
```

### system_actions.py - System Monitoring

**Libraries:** psutil

**Key Methods:**
```python
get_system_info()       # CPU, memory, disk, uptime
_get_cpu_info()        # CPU usage & frequency
_get_memory_info()      # RAM usage
_get_disk_info()        # Disk usage
get_processes()         # Top processes by memory
get_open_ports()        # Network connections
open_application()      # Launch apps
```

## Frontend Architecture (React + TypeScript)

### App.tsx - Main Application

**Responsibilities:**
- WebSocket connection management
- Audio context initialization
- Session state management
- Message history tracking
- Error handling

**State:**
```typescript
isConnected              // WebSocket status
messages                 // Chat history
isListening              // Mic active
isProcessing             // Claude thinking
orbState                 // Particle orb state
error                    // Error message
```

**Key Functions:**
```typescript
startListening()         // Begin voice recognition
sendMessage()            // Send text/voice to backend
playAudio()             // Play response audio
```

### VoiceOrb.tsx - Three.js Visualization

**Features:**
- Audio-reactive particle system
- 1000 particles in sphere formation
- State-based colors:
  - **Idle**: Green (#00ff88) - slow rotation
  - **Listening**: Cyan (#00ffff) - pulsing
  - **Thinking**: Yellow (#ffff00) - audio-reactive
  - **Speaking**: Magenta (#ff00ff) - energetic
- Additive blending for glow effect

**Algorithm:**
1. Create particles distributed on sphere surface
2. Apply random velocities
3. Each frame:
   - Get audio frequency data
   - Calculate average amplitude
   - Expand/contract particles based on audio
   - Rotate based on state
   - Render with state-specific color

**Performance:**
- 60 FPS on modern browsers
- GPU-accelerated via WebGL
- Efficient particle pooling

### ChatInterface.tsx - Message Display

**Features:**
- Auto-scrolling to latest message
- Message styling by role (user vs assistant)
- Text input field
- Send button

**Message Format:**
```typescript
{
  role: "user" | "assistant",
  content: string
}
```

### Settings.tsx - Configuration Panel

**Settings Groups:**
1. **Voice Settings**
   - Language selection
   - Volume control
   - Speech speed

2. **Display Settings**
   - Theme (dark/light/auto)
   - Notifications

3. **Server Configuration**
   - API endpoint URL

4. **Email Integration**
   - Email address
   - App password

5. **About Section**
   - Version info

**Storage:** Browser localStorage

### App.css - Styling

**Color Scheme:**
- Primary: #00ff88 (neon green)
- Secondary: #00ffff (cyan)
- Background: #1a1a2e (dark blue)
- Text: #ffffff (white)

**Key Classes:**
- `.voice-btn` - Microphone button
- `.messages-container` - Chat area
- `.particle-orb` - Three.js canvas
- `.settings-panel` - Settings overlay

## Data Flow

### Voice Input to Response

```
1. User clicks microphone
   ↓
2. Browser requests microphone access
   ↓
3. Web Speech API captures audio
   ↓
4. Transcription sent to backend via WebSocket
   ↓
5. Backend processes command:
   - Adds to memory
   - Gathers context (calendar, email, web)
    - Sends to LLMProvider (Mistral/Anthropic)
    ↓
6. LLM generates response (streaming)
   ↓
7. Response sent to TTS service
   ↓
8. Audio generated & encoded to base64
   ↓
9. Both text + audio sent back to client
   ↓
10. Client plays audio + displays text
    ↓
11. Particle orb animates during playback
```

### WebSocket Message Format

**User Message:**
```json
{
  "type": "text",
  "content": "What's on my calendar?"
}
```

**Server Response:**
```json
{
  "type": "response",
  "text": "You have a meeting at 2pm",
  "audio": "base64_encoded_mp3_here"
}
```

> When audio is streamed, the server emits `audio_chunk` + `audio_end` messages and the final `response` carries `"audio": null`. The client assembles chunks locally.

**Partial Update:**
```json
{"type": "partial", "text": "You have a meeting..."}
```

**Audio Chunk:**
```json
{"type": "audio_chunk", "chunk": "base64_audio_bytes"}
```

**Audio End:**
```json
{"type": "audio_end"}
```

**Status Update:**
```json
{
  "type": "status",
  "status": "processing|generating_speech|error"
}
```

## Performance Optimizations

### Backend
- **SQLite FTS5**: No network calls for memory search
- **Claude Haiku**: 10x faster than Sonnet
- **WebSocket**: Lower latency than HTTP polling
- **Async/await**: Non-blocking I/O

### Frontend
- **Vite**: Fast hot module replacement in dev
- **Three.js**: GPU acceleration for particles
- **React hooks**: Efficient state management
- **Base64 audio**: Single WebSocket message

## Security Considerations

### API Keys
- Never commit `.env` file
- Use environment variables in production
- Rotate keys regularly

### WebSocket
- No authentication in demo (add JWT in production)
- Rate limiting recommended
- Message validation on backend

### Database
- SQLite: Local storage, no network exposure
- Encrypt backups if distributed

### Email
- Use app-specific passwords (Gmail)
- Don't store passwords in localStorage
- Consider OAuth2 in production

## Deployment Checklist

- [ ] Set production API keys in .env
- [ ] Set DEBUG=False
- [ ] Use HTTPS with valid certificates
- [ ] Enable CORS only for your domain
- [ ] Add authentication (JWT tokens)
- [ ] Set up logging/monitoring
- [ ] Configure reverse proxy (nginx)
- [ ] Enable rate limiting
- [ ] Test voice with multiple browsers
- [ ] Backup database regularly

## Testing

### Backend
```bash
# Unit tests (not included, add pytest)
pytest tests/

# API testing
curl http://localhost:8000/health
curl http://localhost:8000/docs
```

### Frontend
```bash
# Run dev server with hot reload
npm run dev

# Build for production
npm run build
```

### End-to-End
1. Start backend: `python main.py`
2. Start frontend: `npm run dev`
3. Open browser to http://localhost:5173
4. Test microphone and text input

---

This architecture prioritizes **speed** (Haiku, FTS5, WebSocket), **simplicity** (SQLite, local files), and **privacy** (everything local except API calls).
