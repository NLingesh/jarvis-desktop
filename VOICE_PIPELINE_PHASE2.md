# Voice Pipeline — Phase 2 (Production Upgrade)

Phase 1 (completed) fixed the "tap to speak does nothing" class of bugs with
incremental hardening: processing watchdog, `getUserMedia` timeouts, WS session
token, threaded STT, guaranteed terminal frames, wake-word/mic handoff, Space-key
guards, mic-permission caching, thread-safe Vosk loading, and unmount cleanup.

Phase 2 replaces the remaining architectural weakness: the voice path still sends
**one giant base64 WAV blob per utterance** (record webm → decode → re-encode →
base64 → WS) and does **batch transcription only after the user stops talking**.
It also preloads nothing at boot and has no heartbeat for dead connections.

## Goals

1. **Stream audio instead of a giant blob.** Capture raw PCM16 (16 kHz, mono) in
   the renderer and push small chunks over the WebSocket as the user speaks.
2. **Incremental Vosk transcription.** Feed PCM chunks to the recognizer as they
   arrive; the final result is available almost immediately after `audio_end`.
3. **Preload the Vosk model at startup** so the first utterance is not slow.
4. **Bound concurrency** so many simultaneous utterances cannot exhaust threads.
5. **Heartbeat / dead-connection detection** on both ends.

## Protocol changes (`/ws/voice`)

Client → Server (replaces `{ "type": "audio", "audio_base64" }`):

| Message            | Payload                                              |
|--------------------|------------------------------------------------------|
| `audio_start`      | `format: "pcm16"`, `sample_rate: 16000`, `channels: 1` |
| `audio_chunk`      | `data: "<base64 of PCM16 LE mono bytes>"`            |
| `audio_end`        | (none)                                               |
| `ping`             | (none); server replies `{ "type": "pong" }`          |

Server → Client: unchanged, plus `{ "type": "pong" }`.

The legacy `audio` + `audio_base64` blob message stays supported for backwards
compatibility (browser-only clients / tests).

## Backend design

- `SpeechToTextModule` gains a streaming recognizer (`stt.stream(sample_rate)`).
  A daemon worker thread consumes PCM chunks from a `queue.Queue`, calls
  `KaldiRecognizer.AcceptWaveform` per chunk (incremental), and on finish returns
  `FinalResult()`. If Vosk is unavailable or returns empty text, it falls back to
  the cloud Whisper-compatible endpoint using the accumulated WAV.
- `websocket_endpoint` keeps a per-connection `StreamingRecognizer` for the
  current utterance; `audio_chunk` feeds it, `audio_end` finalizes it inside
  `asyncio.to_thread` under a global `asyncio.Semaphore(4)`.
- The Vosk model is preloaded on a background thread in the FastAPI lifespan.
- `receive_json` is wrapped in a 90 s idle timeout; idle/dead connections are
  closed. `ping` → `pong` keeps the socket alive and lets the client detect
  half-open connections.

## Frontend design

- Replace `MediaRecorder` capture with a `ScriptProcessorNode` (4096, mono)
  connected to the mic `MediaStreamSource`. Each `onaudioprocess` pass is
  resampled to 16 kHz mono PCM16 by a streaming linear-interpolation resampler
  and pushed as an `audio_chunk`.
- On tap-to-talk: send `audio_start`, then chunks, then `audio_end` on stop.
- Heartbeat: every 25 s send `ping`; if no `pong` within 15 s, force-close so the
  reconnect logic kicks in.

## Files

| File                                   | Change                                        |
|----------------------------------------|-----------------------------------------------|
| `jarvis_backend/modules/stt.py`        | `stream()`, `_StreamingRecognizer`, `preload()` |
| `jarvis_backend/main.py`               | streaming WS handlers, semaphore, idle timeout, lifespan preload |
| `jarvis_frontend/src/App.tsx`          | PCM16 capture/resample/send, ping/pong heartbeat |
| `WS_PROTOCOL.md`                       | document streaming + ping/pong                |
| `jarvis_backend/tests/test_stt.py`     | streaming recognizer tests                    |

## Out of scope (future)

- AudioWorklet capture (drop `ScriptProcessorNode`).
- Live partial transcripts mid-utterance (`PartialResult` streaming to UI).
- True endpointing (stop recording on silence) instead of tap-to-stop.
