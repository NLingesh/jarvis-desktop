# Voice Pipeline — Phase 3 (Live Experience)

Phase 2 (completed) streamed raw PCM16 over the WebSocket into an incremental
Vosk recognizer with a heartbeat, bounded concurrency, and startup model
preload. The remaining UX gaps, listed as "out of scope" in the Phase 2 doc:

1. Audio is still captured with the deprecated `ScriptProcessorNode`
   (runs on the main thread, glitch-prone).
2. The user sees no live feedback while speaking — the transcript only appears
   after the utterance is finalized.
3. Recording stops only on tap (or the 30 s safety cap), never on silence.

## Goals

1. **AudioWorklet capture.** Move resample-to-PCM16 off the main thread into an
   `AudioWorkletProcessor` for lower-latency, glitch-free capture.
2. **Live partial transcripts.** Stream Vosk `PartialResult` updates to the UI
   mid-utterance so the user watches their words appear as they speak.
3. **True endpointing.** Detect silence in the PCM stream and auto-stop
   recording after a configurable quiet period (plus the existing 30 s cap).

## Protocol changes (`/ws/voice`)

Server → Client (new, during an in-flight utterance):

| Message      | Payload                                    |
|--------------|--------------------------------------------|
| `transcript` | `text: "<live partial hypothesis>"`        |

Deliberately **not** reusing the existing `partial` type, which already means
"assistant LLM response is streaming" to the renderer. `transcript` only ever
carries the user's live STT hypothesis.

Client → Server: unchanged (`audio_start` / `audio_chunk` / `audio_end` /
`ping`). Endpointing is client-side, so no protocol change is needed to stop on
silence — the client just sends `audio_end` itself.

## Backend design

- `_StreamingRecognizer` gains an `on_partial: Callable[[str], None]` callback
  (default `None`). In the Vosk path, after each `AcceptWaveform(chunk)`, call
  `PartialResult()` and invoke `on_partial(text)` when the hypothesis changed.
  Throttling: Vosk already returns the same text until it changes, so emitting
  only on change is naturally rate-limited. The cloud fallback path has no
  partials.
- `websocket_endpoint` captures the running event loop at `audio_start` and
  passes an `on_partial` that schedules `send_json({"type": "transcript",
  "text": ...})` back onto the loop via `call_soon_threadsafe` (the recognizer
  thread cannot touch the WebSocket directly).
- No change to the semaphore/idle-timeout/heartbeat logic.

## Frontend design

- New `src/pcmWorklet.js`: a plain-JS `AudioWorkletProcessor` registered as
  `pcm16-capture`. It embeds the linear-interpolation resampler (ported from
  `audioStream.ts`) running at the context sample rate → 16 kHz, encodes PCM16
  LE, buffers to ≥ ~64 ms chunks, and posts them to the main thread with a
  transfer. Loaded via `audioContext.audioWorklet.addModule()` using
  `import pcmWorkletUrl from './pcmWorklet.js?url'`.
- `App.tsx`: replace `ScriptProcessorNode` + `createPcm16Resampler` with an
  `AudioWorkletNode`. The source still feeds an `AnalyserNode` for the orb
  visual, and the worklet is pulled through a zero-gain node (no mic echo).
- Stop protocol: main thread sends `{type: "flush"}` to the worklet port; the
  worklet emits the deferred boundary sample and replies with
  `{type: "pcm", final: true}`; the main thread sends the remaining `audio_chunk`
  then `audio_end`. A 500 ms guard prevents hanging if the node is gone.
- Live transcript: on `transcript` messages, update `liveTranscript` (the
  existing transcript sheet) instead of the assistant response panel.
- Endpointing (`src/audioStream.ts`): add `computeRms(pcmBytes)` (or reuse
  `decodePcm16Le`). In the port handler, track per-chunk RMS. After speech has
  been detected (RMS above threshold), if the RMS stays below the threshold for
  ≥ 900 ms, call `stopManualRecording()` automatically. Keep the 30 s cap as a
  hard backstop and skip endpointing until some speech has been heard.

## Files

| File                                   | Change                                        |
|----------------------------------------|-----------------------------------------------|
| `jarvis_backend/modules/stt.py`        | `on_partial` callback, `PartialResult` emission |
| `jarvis_backend/main.py`               | wire `on_partial` → `transcript` WS messages  |
| `jarvis_backend/tests/test_stt.py`     | partial-emission tests with a fake recognizer |
| `jarvis_frontend/src/pcmWorklet.js`    | new AudioWorkletProcessor (resample + PCM16)  |
| `jarvis_frontend/src/audioStream.ts`   | `computeRms` helper                            |
| `jarvis_frontend/src/App.tsx`          | AudioWorklet capture, flush/endpointing, transcript display |
| `WS_PROTOCOL.md`                       | document `transcript` message                 |

## Out of scope (future)

- Server-side endpointing (send a `stop` hint to the client).
- Push-to-talk overlays / always-on listening UI polish.
- Wake-word gating of the live transcript display.
