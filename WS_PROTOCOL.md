# JARVIS WebSocket Protocol

The primary real-time interface for JARVIS is the WebSocket endpoint at
`/ws/voice`. It carries voice/audio streams, text messages, and streamed
LLM/TTS responses between the Electron frontend and the FastAPI backend.

## Connection

```
ws://<backend_host>:<backend_port>/ws/voice?token=<SESSION_TOKEN>
```

### Authentication

The query parameter `token` **must** match the session token the backend
generated at start-up (or the `SESSION_TOKEN` env var). If the token is
missing or invalid the server immediately closes the connection with code
`4001` and reason `"Invalid or missing session token"`.

On connection the server creates a new **session** (UUID) and associates all
subsequent messages with that session for conversation-memory and document
confirmations.

## Message Envelope

All messages use JSON and share a common envelope:

```json
{
  "type": "<message-type>",
  ... type-specific fields ...
}
```

---

## Client → Server Messages

### `text`

Send a text message (alternative to voice).

```json
{
  "type": "text",
  "content": "What is the weather today?"
}
```

### `audio`

Send a base64-encoded WAV (PCM16, mono, 16 kHz) audio chunk for STT
transcription.

```json
{
  "type": "audio",
  "audio_base64": "<base64-encoded WAV>"
}
```

---

## Server → Client Messages

### `status`

```json
{ "type": "status", "status": "processing" }
```

Possible status values:

| Value               | Meaning                                                 |
|---------------------|---------------------------------------------------------|
| `transcribing`      | Audio received; running speech-to-text                 |
| `processing`        | Transcription complete; generating LLM response        |
| `generating_speech` | LLM response ready; producing TTS audio                |

### `partial`

Streaming partial LLM response text (sent as chunks arrive).

```json
{ "type": "partial", "text": "The weather to..." }
```

### `response`

Final consolidated response.

```json
{ "type": "response", "text": "The weather today is sunny.", "audio": null }
```

### `audio_queue`

Announces the number of audio segments that follow.

```json
{ "type": "audio_queue", "count": 3 }
```

### `audio_segment_start`

Begins an audio segment. The client should reset its audio chunk buffer.

### `audio_chunk`

A single base64-encoded audio chunk (OGG/MP3 or WAV).

```json
{ "type": "audio_chunk", "chunk": "<base64>" }
```

### `audio_segment_end`

Ends an audio segment. The client should concatenate all received
`audio_chunk` payloads since the last `audio_segment_start` and play them.

### `error`

Server-side error message.

```json
{ "type": "error", "message": "Speech recognition failed: model not loaded" }
```

---

## Disconnect / Reconnect

* On disconnect the session is preserved in SQLite; the conversation
  history remains accessible via `GET /api/memory/{session_id}`.
* The frontend should reconnect with **exponential backoff + jitter**:
  1 s → 2 s → 4 s → 8 s → 16 s → 32 s → 60 s (capped), then repeat.
* A reconnect attempt should include the same `token` query parameter.
