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

### `audio_start`

Begin a streaming voice utterance. The server resets its per-connection audio
buffer and creates an incremental recognizer.

```json
{
  "type": "audio_start",
  "format": "pcm16",
  "sample_rate": 16000,
  "channels": 1
}
```

### `audio_chunk`

A chunk of raw PCM16 little-endian, mono audio (base64). Chunks are fed to the
recognizer incrementally as they arrive; small chunks (≈50–100 ms) are
recommended.

```json
{ "type": "audio_chunk", "data": "<base64 of PCM16 LE mono bytes>" }
```

### `audio_end`

Finalize the current utterance and run transcription. The server responds with
the normal `status` / `partial` / `response` / `error` flow.

```json
{ "type": "audio_end" }
```

### `audio` (legacy)

Send a whole base64-encoded WAV (PCM16, mono, 16 kHz) in a single message. Still
supported for backwards compatibility.

```json
{
  "type": "audio",
  "audio_base64": "<base64-encoded WAV>"
}
```

### `wake_start`

Begin continuous wake-word spotting on this connection. The server builds a
keyphrase recognizer and replies `{ "type": "wake_ready", "phrase" }`. Feed it
with `wake_chunk` messages (PCM16 mono, 16 kHz by default) until `wake_stop`.

```json
{
  "type": "wake_start",
  "phrase": "computer",
  "sample_rate": 16000
}
```

The phrase **must** be in the bundled Vosk model's vocabulary (e.g. `computer`).
Proper nouns like "jarvis" are not decodable by the small English model and will
never trigger.

### `wake_chunk`

A chunk of raw PCM16 little-endian, mono audio (base64) fed to the spotter. On a
hit the server sends `{ "type": "wake_word", "phrase" }` and resets the decoder.

```json
{ "type": "wake_chunk", "data": "<base64 of PCM16 LE mono bytes>" }
```

### `wake_stop`

Stop the spotter on this connection and release its worker thread.

```json
{ "type": "wake_stop" }
```

### `ping`

Heartbeat. The server replies `{ "type": "pong" }`. Send one every ~25 s so the
server never closes the connection for idleness.

```json
{ "type": "ping" }
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

### `transcript`

Live speech-to-text hypothesis while the user is still speaking (streamed from
Vosk `PartialResult`). Distinct from `partial` (which carries the assistant's
LLM response). The client should render this as the user's live caption.

```json
{ "type": "transcript", "text": "hello my name is..." }
```

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

### `pong`

Reply to a client `ping` (heartbeat).

```json
{ "type": "pong" }
```

### `wake_ready`

Reply to `wake_start`, confirming the spotter is active for the given phrase.

```json
{ "type": "wake_ready", "phrase": "computer" }
```

### `wake_word`

A wake-word hit while always-on listening. The client should chime and open the
main window to begin a voice session.

```json
{ "type": "wake_word", "phrase": "computer" }
```

### `proactive`

Unsolicited reminder pushed by the backend's background proactive loop. The
client should speak/surface the summary and may show a desktop notification.

```json
{ "type": "proactive", "text": "You have 2 events in the next hour. Your first reminder 'Call Sam' is at 3:00 PM. You also have 1 unread email." }
```

---

## Client → Main Window (Electron IPC)

The bubble window and the main window talk through the Electron main process.

| Channel                 | Payload                      | Direction                      | Effect                                    |
|--------------------------|------------------------------|--------------------------------|-------------------------------------------|
| `bubble-voice-control`   | `{ action: 'start'\|'stop' }` | bubble → main process → main | Shows the main window and starts/stops the voice session |
| `voice-control`          | `'start'\|'stop'`            | main process → main window    | `App.tsx` begins/ends `beginVoiceSession()` / `stopManualRecording()` |
| `show-notification`      | `{ title, body }`            | main window → main process    | Shows a desktop notification (Electron)   |

---

## Disconnect / Reconnect

* On disconnect the session is preserved in SQLite; the conversation
  history remains accessible via `GET /api/memory/{session_id}`.
* The frontend should reconnect with **exponential backoff + jitter**:
  1 s → 2 s → 4 s → 8 s → 16 s → 32 s → 60 s (capped), then repeat.
* A reconnect attempt should include the same `token` query parameter.
* The server closes connections that are idle for **90 s** (no message
  received). Clients should send a `ping` every ~25 s to stay alive.
* A dead/half-open connection is detected when a `ping` is not answered by a
  `pong` within 15 s; the client then force-closes and reconnects.
