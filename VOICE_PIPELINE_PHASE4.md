# Voice Pipeline — Phase 4 (Presence, Memory & Proactivity)

Phase 3 (done, uncommitted with Phase 2) added AudioWorklet capture, live STT
`transcript` messages, and client-side silence endpointing. Phase 4 makes the
assistant feel present: the wake word is actually controllable, the bubble gets
push-to-talk, the orb reflects the full pipeline, JARVIS remembers who you are,
and it proactively notifies you about events and email.

## Goals

1. **Wake-word reliability + always-on.** Honor the `enableWakeWord` setting
   (currently decorative), add an opt-in always-on listening mode, and gate
   live-transcript captions to active listening sessions.
2. **Voice responsiveness polish.** Fix the missing `generating_speech` status,
   surface the live STT caption next to the orb, give feedback while silence
   endpointing is pending, and add push-to-talk to the bubble window.
3. **Conversation memory depth.** Maintain a user profile/preference note in the
   vault, inject it into LLM context, add a `remember` command, and teach the
   LLM to handle follow-ups without repeating the subject.
4. **Notifications & proactive.** Desktop notifications (Electron) for long
   tasks, a background proactive loop that speaks upcoming events / unread mail
   over the live socket, and LLM guidance for cross-module action chaining.

## Design

### 1. Wake-word control (`jarvis_frontend/src/bubble.tsx`, `App.tsx`, `electron`)

- Both windows load from the same origin, so `localStorage` is shared. The
  bubble reads `voiceSettings.enableWakeWord` (and `alwaysOnListening`) at mount
  and on `storage` events, and stops/starts the listener accordingly.
- `App.tsx` settings init reads the full `voiceSettings` object back from
  `localStorage` so the toggle survives reload.
- New opt-in setting `alwaysOnListening`: when enabled, the bubble keeps the
  wake listener running even while the main window is visible (defaults to the
  current visibility-based handoff behavior otherwise).
- **Bubble PTT**: the bubble gains a small mic button. A press notifies the main
  process via a new `bubble-voice-control` IPC (`{action: 'start'|'stop'}`),
  which relays a `voice-control` push to the main window. `App.tsx` starts/stops
  a session on receipt. This keeps mic capture/STT in the main window only.

### 2. Voice responsiveness (`routes/state.py`, `App.tsx`, `bubble.tsx`)

- Backend: send `{ "type": "status", "status": "generating_speech" }` when TTS
  begins (currently only `audio_queue` triggers 'speaking', and the documented
  `generating_speech` is dead).
- Frontend: show the live STT caption as a subtitle beneath the orb during
  `listening`; show "Finishing..." in the orb hint while silence endpointing is
  pending (client already knows when the silence timer is counting down).
- Bubble PTT also drives `toggleTalk` from the always-on-top window.

### 3. Conversation memory (`routes/state.py`, `modules/llm_provider.py`, vault)

- Profile note: a `person`-type vault note at `People/me.md` (created if
  missing) is the user profile. Its body is injected into LLM context as a
  system message in `handle_user_input`.
- `remember`/`forget` commands in `process_command`: append a preference line to
  the profile note, or clear it. `what do you know about me` reads it back.
- System prompt gains follow-up guidance (assume omitted subjects refer to the
  current topic) and action-chaining guidance (suggest the natural next step
  after completing an action).

### 4. Notifications & proactive (`electron/main.js`, `preload.js`, `App.tsx`, `main.py`, `modules/proactive.py`)

- Electron: `show-notification` IPC → `new Notification({title, body}).show()`.
  Preload exposes `showNotification`.
- Long-task notifications: the frontend tracks processing start; when a response
  arrives after >10 s (or an error after a long task) and notifications are
  enabled, show a desktop notification.
- Proactive loop: a backend `asyncio` task in the lifespan polls every 5 minutes
  for events starting within 30 minutes and for unread email. On new findings it
  speaks a concise summary over every connected socket by reusing the TTS
  segment flow (extracted into a shared `_stream_tts_to_socket` helper). The
  frontend also shows a desktop notification when it receives a `proactive`
  message.

## Files

| File                                   | Change                                        |
|----------------------------------------|-----------------------------------------------|
| `jarvis_frontend/src/bubble.tsx`       | honor settings, always-on, PTT button + IPC   |
| `jarvis_frontend/src/App.tsx`          | settings init, live caption, `generating_speech`/`voice-control` handling, long-task notifications |
| `jarvis_frontend/src/components/Settings.tsx` | `alwaysOnListening` toggle             |
| `electron/preload.js`                  | `showNotification`, `onVoiceControl`, `sendBubbleVoiceControl` |
| `electron/main.js`                     | `show-notification`, `bubble-voice-control` IPC, relay to main window |
| `jarvis_backend/routes/state.py`       | `generating_speech`, profile injection, `remember`/`forget`, `_stream_tts_to_socket` |
| `jarvis_backend/modules/llm_provider.py` | follow-up + chaining prompt guidance       |
| `jarvis_backend/main.py`               | socket registry + proactive lifespan task    |
| `jarvis_backend/modules/proactive.py`  | new: proactive summary logic                 |
| `jarvis_backend/tests/`                | proactive + remember + profile tests         |
| `WS_PROTOCOL.md`                       | `proactive`, `generating_speech`, `voice-control` |
| `VOICE_PIPELINE_PHASE4.md`             | this document                                |

## Out of scope (future)

- Local on-device wake-word (Porcupine/Silero) instead of the cloud Web Speech API.
- Server-pushed proactive scheduling configuration UI.
- Multi-user profiles / per-user vaults.
