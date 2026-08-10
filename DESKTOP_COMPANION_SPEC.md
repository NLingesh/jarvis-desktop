# JARVIS — Desktop Companion UX & Architecture Spec (v2)

> **Product vision.** JARVIS is a real personal AI assistant that lives on the
> desktop. It is a **companion, not an application**. In its default state there
> is no window, no sidebar, no dashboard — only a small, living orb that is
> always present. It expands into a floating panel only when needed, and
> collapses back into the orb. Everything it does on the computer is gated by
> explicit permission and confirmation.
>
> **Scope.** This is the authoritative design + architecture document. It is
> **design-only — no implementation code.** It supersedes the fullscreen-shell
> assumptions in `UI_DESIGN.md`.
>
> **Daily-driver context.** This assistant is used every day for programming,
> AI development, Linux administration, file management, browsing, note taking,
> and voice interaction. Usability and practicality outrank aesthetics at every
> decision point.

---

## 1. Design Principles

1. **Presence over interface.** The orb is home. The panel is a tool. The OS
   is the canvas. JARVIS feels *with* you, not like something you open.
2. **Three planes of existence.**
   - **Ambient** — the floating orb; always visible, always breathing.
   - **Focused** — a compact floating panel, summoned on demand, dismissed.
   - **Systemic** — actions performed *on* the machine (files, apps, terminal,
     clipboard), with the orb as agent and the panel as console.
3. **Calm intelligence.** Quiet, confident, minimal. No dashboards, no HUDs,
   no decorative chrome. If it doesn't need to be seen, it is not shown.
4. **Motion is meaning.** The orb's animation *is* the status indicator —
   a heartbeat for idle, a ripple for listening, counter-rotating rings for
   thinking. Users learn the machine's mood from its motion alone, at a glance.
5. **Privacy first, locally.** Memory, files, and preferences live on the
   machine. Nothing leaves without explicit action.
6. **Reduction.** Every element earns its place. Apple-level polish,
   OpenAI-level simplicity, Iron Man inspiration — rendered with restraint,
   not cosplay. No futuristic decoration that isn't functional.
7. **Explicit consent for consequence.** Anything destructive or invisible
   (delete, close app, run command, write clipboard, monitor) requires a
   deliberate user confirmation. The assistant is helpful, never presumptuous.

---

## 2. The Orb — The Ambient Self

The orb is the assistant's body and the **only** thing always on the desktop.

### 2.1 Visual anatomy

```
            (aura: radial blur, ~2.2× core)
                 .-~~~~~-.
              .-'    ●    '-.      ← CORE  — glass, cyan radial gradient
             /    /     \    \         hot center (#E8F9FF → #00C8FF → near-black rim)
            |    '---'     |    ← STATUS ARC (2 px, appears ONLY in transient states)
             \           /            listening: fills cyan
              '-.     .-'             thinking:   counter-rotates
                 '~~~~~'              speaking:   pulses with audio
                                      error:      red arc
                                      offline:    none
         ●  ← NOTIFICATION DOT (6 px) — the only persistent badge
```

- **Core** — 48–64 px glass orb. Radial gradient, no hard borders; edges are
  pure soft light. Sits on `bg/base` darkness.
- **Aura** — blurred halo behind the core. Opacity breathes with the core;
  this is what makes it feel *alive* rather than like a widget.
- **Status arc** — thin ring shown only during transient states; never idle.
- **Notification dot** — upper-right; appears only when something needs
  attention (reminder due, reply ready, task result).
- **No text, ever, on the orb.** Context arrives on hover or by voice.

### 2.2 Ambient behaviors (idle)

| Behavior | Motion | Timing | Notes |
|---|---|---|---|
| Breathing | core scale 1.0 ↔ 1.03; aura opacity 0.5 ↔ 0.7 | 4.5 s sine | Always on; <1% CPU |
| Micro-drift | orbital wander 1–2 px | 12 s loop | Feels alive, never static |
| Hover | core 1.0 → 1.06; tooltip fades in | 150 ms ease-out | Tooltip: *"Hey Jarvis — or press Ctrl+Space"* |
| Wake pulse | core 1.1× + glow flash | 200 ms | On wake-word hit |
| Drag | core 1.15×, aura widens | follows pointer | Release → snap + persist |
| Occluded/idle 30 s | animation pauses → static glow | 300 ms fade | Power + focus hygiene |

### 2.3 Placement rules

- **Always on top** (toggleable), excluded from the taskbar.
- **Default:** lower-right, 24 px from work-area edges.
- **Drag anywhere**; position persisted across restarts.
- **Work-area aware:** the orb never leaves the visible work area on its own;
  it docks to edges with a 4 px "park" inset.
- **Never steals focus.** Clicking the orb never jumps a window in front of
  the user's work. All orb interactions are focus-free.

---

## 3. Interaction Model

### 3.1 Gesture map

| Gesture | Action | Feedback |
|---|---|---|
| **Single click** | Open **quick actions** (transient ring around orb) | ripple + soft chime |
| **Double click** | Open **conversation history** in the panel | panel slides open |
| **Right click** | **Context menu** — desktop integration + settings | compact menu near orb |
| **Voice wake** — "Hey Jarvis" | Wake → listening → respond | wake pulse + chime |
| **Ctrl + Space** | Toggle panel (or start capture — user-configurable) | slide in/out |
| **Drag** | Reposition orb | follows pointer |
| **Drop file / text** | Give to JARVIS (analyze, summarize, transcribe, OCR) | glow flare + chime |
| **Hover** | Preview state + tooltip | soft expand |
| **ESC** | Collapse panel → orb / dismiss quick actions | slide back / fade |
| **Pinch (touch)** | Not supported on desktop — all touch handled via hover equivalents | — |

### 3.2 Gesture disambiguation (click vs double-click vs drag)

Distinguishing these reliably is essential — the orb has no window chrome to
absorb sloppy input.

- **Timing thresholds:** a click is down + up within 220 ms with
  ≤ 6 px pointer travel. A double-click is two clicks within 320 ms.
- **Behavior:** on first mouse-down, start a 220 ms timer. If pointer travels
  > 6 px → it's a **drag** (cancel click timer). If released within 220 ms →
  wait up to 320 ms for a second click; if it comes → **double-click**
  (conversation history); if not → **single click** (quick actions).
- **Result:** drag always wins over click; single click always wins over
  double-click unless the second press arrives in time. No accidental menus.
- **Feedback:** the orb subtly scales down 0.97× on press so the user always
  knows a gesture registered.

### 3.3 Quick actions (single click)

A minimal arc of 4 actions rendered **around** the orb — not a menu, not a dock:

```
              [ Talk ]
         [ Chat ]  ●  [ Tools ]
              [ Memory ]
```

- Appears with a 120 ms staggered entrance; auto-dismisses after 6 s
  inactivity, on ESC, or click-away.
- **Talk** — start a voice session (same path as wake word).
- **Chat** — open the conversation panel.
- **Memory** — open the memory browser.
- **Tools** — open the desktop-integration action sheet.

### 3.4 Context menu (right click)

A compact native-style menu near the orb: Talk / Chat / Memory / Files /
Settings / Models / Plugins / **Quit**. Matches OS conventions (keyboard
navigation, ESC dismiss).

### 3.5 Keyboard

| Shortcut | Action |
|---|---|
| `Ctrl+Space` | Toggle panel (default) |
| `Ctrl+Space` (hold) | Push-to-talk (configurable) |
| `Ctrl+Shift+Space` | Start/stop voice capture from panel |
| `Esc` | Collapse panel / dismiss transient UI |
| `Tab` | Navigate panel; orb is focusable |
| `Enter` | Activate focused action |

All shortcuts configurable in Settings; conflicts detected and reported.

### 3.6 Voice — the primary input

Voice is the default channel, not an add-on:

- **Wake word** opens a listening session. The orb emits a wake pulse + soft
  chime; the user speaks; endpointing (≈1.2 s silence) finalizes; the orb
  moves to THINKING.
- **No wake, no mic.** The orb does not capture audio unless (a) the wake
  word is enabled AND the user enabled "always listening", or (b) the user
  starts a session explicitly (PTT, Talk, Ctrl+Space). An **active-mic
  indicator** is always shown while capturing.
- **Interrupt:** wake word or PTT during SPEAKING stops speech and re-enters
  LISTENING. Interrupt is instant (≤100 ms).
- **No-speech handling:** if no speech within 12 s, return to IDLE with a
  single soft state-chime (no verbal apology).
- **Wake engineering constraint:** the bundled small Vosk model cannot decode
  the proper name "Jarvis". The shipped working phrase is **"computer"**,
  configurable, until a custom lexicon / Porcupine integration lands (Phase E).

---

## 4. The Orb State Machine

### 4.1 State map

```
                  ┌────────────────────────────────────────────┐
                  │              PANEL OPEN                    │
                  │  Chat · Memory · Files · Models · Plugins  │
                  │  Settings · Tools (transient)              │
                  └────────────▲──────────────────┬────────────┘
                               │ open             │ collapse (Esc/click-away/command)
   NOTIFICATION ─► IDLE ─────► LISTENING ──► THINKING ──► SPEAKING ──► IDLE
      ▲            ▲   ▲        │                   │  (interruptible)
      │            │   │        └── no speech ──────┘
      │            │   └── wake / PTT / Talk / Ctrl+Space
      ▼            │
   (badge + pulse) │
   ERROR ──────────┘   OFFLINE (grey orb, no aura, static)

   PROCESSING: transient sub-state reached from THINKING when a tool/desktop
   task runs (files, terminal, search). Orb pulses a soft amber ring.
```

### 4.2 Per-state specification

| State | Trigger | Visual | Motion | Audio | Exit |
|---|---|---|---|---|---|
| **IDLE** | default | cyan orb, breathing + drift | 4.5 s sine + 12 s drift | silence | any interaction |
| **LISTENING** | wake word, PTT, Talk, shortcut | orb 1.15×; ripple rings emanate; aura brightens | ripple every 0.8 s; glow 300 ms | mic-open chime | endpoint, timeout, cancel, interrupt |
| **THINKING** | audio_end → LLM request | 2 counter-rotating arcs; core dims; ≤6 particles | arcs 2.4 s / 3.6 s; particles drift out | near-silence / faint tick | first token, error |
| **SPEAKING** | TTS begins | waveform ripples around orb; core pulses with syllables | wave amplitude ∝ audio RMS | the reply | TTS end, interrupt |
| **PROCESSING** | tool/task runs | soft amber pulse ring, stays calm | 3 s pulse | none | task complete |
| **NOTIFICATION** | reminder / result ready | orb 1.1× pulse + badge dot | 300 ms pulse; dot fades in | soft chime | dismiss, open |
| **OFFLINE** | backend/network down | grey `#6B7280`, no aura, no motion | static | none | reconnected |
| **ERROR** | STT/LLM/tool failure | red arc + 2 red pulses; core dims | 2 pulses 400 ms apart | error chime | resolved / dismissed |
| **PANEL-OPEN** | any open command | orb shrinks to 40 px "anchor"; panel slides from it | 220 ms ease-out-cubic | very subtle whoosh | collapse |

### 4.3 Transition rules (edge cases)

1. **One transient state at a time.** The status arc renders only during
   listening/thinking/speaking/processing/error — never idle.
2. **Listening timeout:** no speech in 12 s → IDLE with soft chime.
3. **Thinking watchdog:** LLM over user-configured timeout (default 45 s) →
   ERROR *"That took too long — try again."* The orb never spins forever.
4. **Interrupt priority:** LISTENING > SPEAKING > THINKING. Wake/PTT during
   speaking or thinking cancels it and starts LISTENING.
5. **Batched events:** notifications arriving during a voice session are
   deferred to the badge dot, never interrupting speech.
6. **State is always knowable without sight.** Each state has an optional
   audio signature (toggleable) so a user working in another window can track
   the orb.
7. **Reconnect:** OFFLINE auto-retries with exponential backoff
   (1→2→4→8→16→32→60 s, capped); on success, one NOTIFICATION pulse
   ("I'm back").

---

## 5. The Floating Panel — The Focused Self

The panel is summoned from the orb and collapses back into it. It is a sheet,
not a window.

### 5.1 Geometry & behavior

- **Anchored to the orb** — expands upward/left so it never covers the orb or
  jumps the screen. Constrained to the work area; clamps on window-move.
- **Default 380 × 560 px**, resizable to 85% of work area max. **Never
  fullscreen.**
- Position + size persisted per view.
- **Non-modal:** the panel floats while the user works elsewhere; it never
  forces focus.
- **Collapse paths:** ESC, click-away, chevron, or the command "collapse".
  Slides back into the orb (220 ms).

### 5.2 Anatomy

```
  ┌────────────────────────────────────────────┐
  │ ●  JARVIS        ● listening   [model ▾]   │  ← header: mini-orb + live state + model
  ├────────────────────────────────────────────┤
  │   Chat · Memory · Files · Models · Plugins │  ← view switcher (slim segmented row —
  │                 · Settings                 │    NOT a sidebar)
  │                                            │
  │                 [content]                  │  ← active view (see 5.4)
  │                                            │
  ├────────────────────────────────────────────┤
  │  🎙 Hold to talk       [send ⏎]  [⚙]      │  ← universal input bar
  └────────────────────────────────────────────┘
```

- **Header** — mini-orb mirroring the main state, connection dot, model
  picker (opens Models), and a PTT control.
- **View switcher** — one labeled row; no icons-only rail.
- **Footer** — universal input: hold-to-talk + text + send, so the user can
  always just *talk*.

### 5.3 View switch behavior

- One view at a time; switching cross-fades in 120 ms.
- View state is preserved per view (scroll, drafts, filters).
- No sidebar, no persistent nav column anywhere.

### 5.4 View specifications

| View | Purpose | Layout & states |
|---|---|---|
| **Chat** | Conversation with context + memory | asymmetric bubbles (user right/cyan edge, assistant left/glass); streaming text with caret; code blocks w/ copy; regenerate; inline voice captions; **empty state** = greeting + suggested prompts; **loading** = typed placeholder dots |
| **Memory** | Recall what JARVIS knows | searchable 3-pane: left = categories (Projects/Notes/Conversations/Tasks/Preferences/Knowledge), middle = items, right = detail; global search; **empty states** per category; pinned items |
| **Files** | File operations + results | local tree (scoped), preview pane, action results inline; confirmations shown as cards; **empty** = "drop a file on the orb to start" |
| **Models** | Providers & models | status rows (ok/error), latency, RAM/GPU badges, switch, add/remove; **offline** banner |
| **Plugins** | System integrations | enable/disable toggles, permission summaries per plugin, audit log entry |
| **Settings** | Personalization | grouped sections: Wake word & voice, Hotkeys, Privacy & permissions, Appearance (theme/size), Startup, Memory (export/clear/encrypt), Updates |
| **Tools (transient)** | Desktop actions sheet | action cards: Files / Search / Apps / Terminal / Clipboard / Screenshot / OCR; each opens its confirmation flow (§6) |

---

## 6. Desktop Integration — The Systemic Self

JARVIS acts *on* the machine. Every capability has an explicit
permission + confirmation policy.

### 6.1 Capability catalog with policy

| Capability | Default | Confirmation? | Surface |
|---|---|---|---|
| Read files | allowed (scoped to home by default; grant wider scope) | no | panel + drag-drop |
| Create files | allowed | no | panel result |
| Rename files | allowed | no | panel result |
| **Delete files** | **blocked** | **yes — explicit, with typed/press-and-hold confirm option** | Tools sheet |
| Search the computer | allowed (indexed) | no | panel results |
| Open applications | allowed | no | Tools sheet |
| **Close applications** | **blocked** | **yes** | Tools sheet |
| **Execute terminal commands** | **blocked** | **yes — command preview + Run/Deny; output in panel console** | Tools sheet |
| Read clipboard | allowed **on demand** | first-time consent | command |
| Write clipboard | allowed **on demand** | yes for one-shot | command |
| Take screenshots | allowed | first-time consent | Tools sheet |
| OCR screenshots | allowed | no (same session) | Tools sheet |
| Monitor active window | **off** | explicit opt-in + persistent indicator | Settings |
| Read notifications | **off** | explicit opt-in | Notification pulse |
| System tray | on | — | tray mirrors orb |
| Startup with OS | on | first-run choice | Settings |
| Drag & drop | on | no | orb |

### 6.2 Confirmation UX (the consent model)

- **Non-destructive** (read, create, rename, open, search): run immediately;
  result appears in the panel.
- **Destructive or invisible** (delete, close, terminal, clipboard write):
  a compact **confirmation card** shows exactly what will happen — resolved
  command, target path, side effects — with a **Run / Deny** choice.
  - Delete: default selection is **Deny**; press-and-hold or type-to-confirm
    for irreversible operations.
  - Terminal: commands render in a read-only console; output streams back;
    a kill button is always available.
- **Audit log:** the last 200 system actions (command, target, timestamp,
  permission used) are stored locally and viewable in Settings. **Undo**
  offered wherever technically possible (e.g., restore-from-trash).
- **One-shot grants** never persist silently; sensitive capabilities re-ask
  unless set to "always allow" explicitly.
- **Privacy indicator:** the orb shows a tiny indicator dot whenever
  clipboard/screen/window-monitoring is actively engaged.

### 6.3 Security posture

- All system operations run in a **sandboxed backend worker** with minimal
  privileges; the UI can never inject shell input into an already-running
  shell.
- Commands are never chained or auto-expanded beyond what the user sees.
- Sensitive output (credentials, tokens) is redacted from the panel console
  by default with a "reveal" action.

---

## 7. Memory — The Local Self

JARVIS remembers locally. No cloud, no telemetry.

### 7.1 Stores

| Store | Content | Surfaces |
|---|---|---|
| **Projects** | working dirs, tech stack, recent tasks | contextual recall in chat |
| **Notes** | vault notes, quick captures | Memory view; "remember that…" |
| **Conversations** | full chat/voice history | Chat history, recall |
| **Tasks** | reminders, to-dos, scheduled items | proactive pulse + notifications |
| **Preferences** | wake word, voice, hotkeys, permissions | behavior + settings |
| **Knowledge** | learned facts, idioms, decisions | "you told me…" recall |

### 7.2 Memory behaviors on the orb

- **Memory pulse:** when a task/reminder is due, orb emits one pulse + badge;
  clicking opens the item.
- **Proactive whisper:** during idle the orb may glow faintly with a
  low-priority suggestion ("3 events in the next hour") — never louder than
  the current activity, always dismissible, frequency-capped (≤1/10 min).
- **Explicit capture:** "remember that X" stores to Knowledge and echoes a
  one-line confirmation in the panel with a chime.
- **Recall in chat:** assistant may attach relevant memory as context,
  always visible as a small "recalled" chip that can be dismissed.

### 7.3 Privacy & lifecycle

- **Storage:** local SQLite + markdown vault. No analytics, no cloud sync.
- **Encryption at rest:** optional, keyed from the OS keychain.
- **Export:** one-click full export (markdown + JSON).
- **Clear:** one-click wipe with confirmation; fine-grained per-category
  deletion in Memory view.
- **Scoped reads:** JARVIS only surfaces what it actually read, and file
  reads are logged to the audit log.

---

## 8. Design System

### 8.1 Color

| Token | Value | Role |
|---|---|---|
| `bg/base` | `#090B10` | deepest backdrop |
| `bg/panel` | `rgba(16, 20, 29, 0.78)` | glass sheet |
| `bg/inset` | `#10141D` | inputs, cards |
| `accent` | `#00C8FF` | primary cyan (orb, actions) |
| `accent/hi` | `#38BDF8` | highlights, links |
| `text/hi` | `#F1F5F9` | primary text |
| `text/mid` | `#94A3B8` | secondary text |
| `text/lo` | `#475569` | disabled |
| `success` | `#34D399` | confirmations |
| `warning` | `#FBBF24` | caution |
| `error` | `#F87171` | errors |
| `offline` | `#6B7280` | offline orb |

### 8.2 Typography

| Token | Size / Weight | Use |
|---|---|---|
| display | 28 / 600 | panel headings, hero states |
| title | 18 / 600 | view titles |
| body | 14 / 400 | default |
| caption | 12 / 400 | metadata, timestamps |
| mono | 13 / 400 | code, commands, logs |
| Fonts | Inter (UI), JetBrains Mono (code) | system-first |

### 8.3 Spacing / radius / glass

- Spacing scale: **4 / 8 / 12 / 16 / 24 / 32** px.
- Radii: cards **12**, panel **20**, orb **circular**, pills **999**.
- Glass: `backdrop-filter: blur(24px)` + `saturate(140%)`; border
  `1px rgba(255,255,255,0.08)`. Elevation via shadow, never hard lines.

### 8.4 Motion tokens

| Token | Value | Use |
|---|---|---|
| `ease/out` | cubic-bezier(0.16, 1, 0.3, 1) | panels, views |
| `ease/spring` | cubic-bezier(0.34, 1.56, 0.64, 1) | orb micro-expansions |
| `t/fast` | 120 ms | micro feedback (press, hover) |
| `t/med` | 220 ms | panel, view switches |
| `t/slow` | 450 ms | state choreography |
| `breath` | 4.5 s sine | idle |
| `ripple` | 0.8 s | listening |
| `arc/think` | 2.4 s / 3.6 s | thinking rings |

---

## 9. Motion & Accessibility

- **Motion is informative.** Every animation maps to a state or transition in
  §4. Nothing moves for its own sake.
- **Reduced motion:** ambient animation (breathing, drift, particles) reduces
  to a static glow; transitions collapse to 80 ms cross-fades. Honored for
  the whole app (system + app-level toggle).
- **Contrast:** text meets WCAG AA everywhere; cyan vs dark base well above
  threshold.
- **Keyboard:** `Ctrl+Space` opens the panel; Tab navigates; orb focusable,
  Enter = quick actions, Esc = dismiss.
- **Screen readers:** orb exposes state via `aria-live` ("idle", "listening",
  "thinking", "speaking", "error", "offline"); panel views use proper
  landmarks and heading hierarchy.
- **State chimes:** optional audio cues, independently toggleable, so the orb
  is trackable without vision.
- **Haptics:** optional on supported platforms (notebook vibration).

---

## 10. Production-Ready Architecture

### 10.1 Process & window model

```
 ┌─────────────────────────────────────────────┐
 │  Electron main (Node)                       │
 │  · window lifecycle (orb + panel)           │
 │  · IPC hub, tray, startup, hotkeys          │
 │  · permission gating for OS capabilities    │
 ├─────────────────────────────────────────────┤
 │  Orb renderer (frameless, always-on-top)    │
 │  Panel renderer (compact sheet)             │
 └───────────────┬─────────────────────────────┘
                 │ localhost HTTP/WS (+token)
 ┌───────────────▼─────────────────────────────┐
 │  Backend (FastAPI child process)            │
 │  · /ws/voice: wake-start/chunk + voice loop │
 │  · Vosk STT + wake keyphrase                │
 │  · LLM provider (NVIDIA/Anthropic, timeout+ │
 │    fallback) · TTS (edge-tts)               │
 │  · Memory manager (SQLite + vault)          │
 │  · System/tool sandbox worker               │
 └─────────────────────────────────────────────┘
```

- **Exactly two windows, ever.** The panel does not spawn child windows.
- **Backend** is a child process with health checks + auto-restart, session
  token via env, and WS auth (`/ws/voice?token=…`).
- **Security hardening:** `contextIsolation: true`, `sandbox: true`,
  `nodeIntegration: false`, preload-only IPC bridge, permission handlers for
  mic/media. All system ops live in the sandboxed worker, never the UI.

### 10.2 Mapping to the current codebase

| Design layer | Current implementation | Work needed |
|---|---|---|
| Orb (ambient window) | `bubble.html` → `src/bubbleMain.tsx` → `bubble.tsx` frameless always-on-top window | reshape to orb anatomy + motion language (§2) |
| Panel (focused window) | main `BrowserWindow` (480×720) | compact sheet, attach-to-orb, collapse-to-orb (§5) |
| Wake word | Vosk keyphrase spotter (`stt.py`), orb streams mic → `wake_start/chunk` | keep; default "computer"; add mic indicator |
| Voice loop | `/ws/voice` → Vosk → LLM → TTS → streamed audio | no structural change |
| Quick actions / tools | none | new IPC + gated system worker (§6) |
| Memory | SQLite manager + vault | add Projects/Tasks/Knowledge + export/encrypt (§7) |
| Tray / startup | tray menu exists | mirror orb actions in tray |

### 10.3 Performance budgets (the orb must stay light)

| Metric | Budget |
|---|---|
| Orb idle CPU | < 1% (animation pauses when occluded) |
| Orb idle RAM | < 60 MB |
| Panel open → first paint | +100 ms max |
| Wake → chime latency | < 900 ms typical |
| Voice round trip (speak → reply) | ≤ 10 s p95 with a working LLM |
| Window count | 2 (orb + panel), never more |
| Memory footprint of stores | bounded; vault pages lazily |

### 10.4 Power & focus hygiene

- Pause all animation when fully occluded or display asleep (30 s idle → static
  glow).
- Wake-word streaming is the only always-on mic path; **off by default**;
  explicit enable + visible indicator.

### 10.5 Packaging & updates

- Single signed bundle; orb + panel ship together as one app.
- Backend + models are a separate, versioned payload; the wake-word lexicon is
  downloadable so the app ships tiny and upgrades "Hey Jarvis" support later.
- Updates: staged download → verify checksum → swap → restart; user
  notification via orb pulse (never a forced mid-task restart).

---

## 11. Onboarding & First Run

First-run must not feel like a wizard inside a window; it happens **at the
orb**.

1. **Arrival:** orb appears with a gentle wake-pulse; the tooltip says
   *"I'm here. Say 'computer' or press Ctrl+Space."*
2. **Voice probe:** JARVIS asks one question ("Say the wake word to test
   my ears") and confirms detection with a pulse + chime.
3. **Permissions tour:** one card at a time — microphone, startup, memory
   (all optional, all reversible in Settings).
4. **Quick start:** offers 3 starter commands ("Search my files", "Remember
   this project", "Open the panel") to teach the interaction model.
5. **Complete:** a single notification pulse — *"I'm set up. Ask me anything."*

---

## 12. Error Handling Matrix

| Failure | Orb state | Message (one line) | Recovery |
|---|---|---|---|
| Backend down | OFFLINE (grey, static) | — | auto-reconnect w/ backoff |
| STT no model | ERROR | "I need my speech model — is it installed?" | link to downloader |
| STT hears nothing | ERROR | "I couldn't hear anything." | auto-return to IDLE |
| LLM timeout | ERROR | "That took too long — try again." | retry button |
| LLM provider down | ERROR | "My brain is unreachable right now." | retry w/ fallback model |
| TTS fails | THINKING → response shown as text only | — | text stays visible |
| Command denied | ERROR | "That needs permission — see Settings." | open Settings |
| Command failed | ERROR | short failure reason | show output in panel |
| Mic busy (orb vs panel) | ERROR | "Microphone is in use." | the orb releases mic |

Every error is: visible on the orb, one line in the panel, actionable or
auto-recovering. **Never a crash, never a frozen window, never silent death.**

---

## 13. Quality Bar (the daily-driver contract)

- **Always responsive.** Orb reacts to every input within 100 ms; panel within
  220 ms. Nothing blocks the UI thread.
- **Failures are graceful.** Degrade to clear states with actionable messages.
- **Confirmation before consequence.** Anything destructive or invisible
  requires explicit consent (§6.2).
- **Quiet unless asked.** No pop-ups, no dashboards, no unsolicited windows.
- **Private by default.** Local storage, no telemetry, explicit grants.
- **Feels alive, stays light.** Continuous subtle motion at <1% CPU; never
  static, never flashy.

---

## 14. Roadmap

| Phase | Deliverable | Acceptance criteria |
|---|---|---|
| **A — Living Orb** | orb anatomy, breathing/drift, drag+persist, hover, quick-actions ring, all §4 states | animates at <1% CPU; states distinguishable at a glance; all gestures work incl. disambiguation |
| **B — Focused Panel** | attach/expand/collapse, view switcher, Chat + Settings | opens/closes 220 ms, never fullscreen, collapses to orb, persists geometry |
| **C — Systemic Self** | Tools sheet + permission/confirmation layer + audit log + undo | every destructive action confirms; undo works where possible; audit log complete |
| **D — Memory** | all six stores, recall chips, proactive pulse, export/clear/encrypt | "remember that…" round-trips; scheduled tasks pulse the orb; export/clear complete |
| **E — Voice polish** | real "Hey Jarvis" (lexicon/Porcupine), always-listening toggle + indicator, interrupt | wake detection ≥90% in noise; interrupt ≤100 ms |
