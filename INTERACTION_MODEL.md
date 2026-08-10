# JARVIS — Living Companion Interaction Model

> **What this document is.** This is the behavioral, emotional, and
> physical design layer that makes JARVIS feel alive. It sits on top of
> `DESKTOP_COMPANION_SPEC.md` (architecture, states, permissions) and
> `UI_DESIGN.md` (visual design tokens). It defines *how JARVIS exists*
> — not what it looks like or how the backend works.
>
> **Core thesis.** An AI companion feels alive when it has:
> 1. **Internal state** that changes without user input.
> 2. **Personality** that is consistent but not robotic.
> 3. **Physical presence** that occupies space and time on the desktop.
> 4. **Memory** that creates continuity across sessions.
> 5. **Autonomy** that is bounded, predictable, and always deferential.

---

## 1. The Continuum of Presence

JARVIS exists along a spectrum from **dormant** to **immersed**.

```
  DORMANT ──► AMBIENT ──► AWARE ──► ENGAGED ──► IMMERSED
  (offline)    (orb)       (panel)    (voice)      (full task)
```

| Zone | What the user sees | What JARVIS does |
|---|---|---|
| **DORMANT** | Grey static orb | Nothing. Waits. |
| **AMBIENT** | Orb breathing + drift + aura | Monitors time, calendar, system health, idle duration. May pulse gently when something is due. |
| **AWARE** | Panel collapsed, orb subtly reactive | User has panel open or is hovering. JARVIS adjusts aura brightness to panel activity. |
| **ENGAGED** | Panel open, orb shrinks to anchor | Active conversation or task. Orb mirrors text streaming, thinking, speaking. |
| **IMMERSED** | Panel maximized or full-task mode | JARVIS runs a long task (file search, code generation). Orb goes quiet; panel does the work. |

**Key rule:** JARVIS never forces the user into a zone. The user controls the
depth. JARVIS only *suggests* movement (a pulse, a glow, a whisper).

---

## 2. Orb Personality & Expression

The orb is not a generic particle sphere. It is **one entity** with a
consistent visual vocabulary.

### 2.1 Core expression system

| Expression | Trigger | Visual |
|---|---|---|
| **Calm** | Idle, no pending tasks | Slow breathing, minimal drift, soft cyan aura |
| **Alert** | Notification pending, reminder due | Faster breathing (3.2s), brighter aura, dot appears |
| **Warm** | User has been active in last 5 min | Aura warmth increases (toward #38BDF8), drift follows cursor slightly |
| **Focused** | Panel open, user typing | Orb shrinks slightly (40px), aura tightens, breathing slows |
| **Playful** | User just completed a task, idle for 2+ min | Brief micro-bounce (spring curve), drift becomes more organic |
| **Concerned** | Error, backend down, missed wake | Dim core, red tint on aura, two slow pulses |
| **Curious** | User dropped file / new context | Aura ripples outward once, core brightens |
| **Sleepy** | User idle >15 min, no notifications | Breathing slows to 6s, drift stops, aura dims 30% |

### 2.2 The "warmth" gradient

The orb's color is never pure cyan. It shifts along a spectrum:

- **Cold/Idle** — `#00C8FF` (pure cyan)
- **Warm/Engaged** — `#38BDF8` → `#7DD3FC` (sky blue)
- **Hot/Active** — `#00E5FF` (bright cyan, higher luminance)
- **Dimmed** — `#0E7490` (muted teal)
- **Error** — `#F87171` (red) + `#FBBF24` (amber ring)

Transitions between warmth levels use a 400ms ease. Never snap.

### 2.3 Micro-movements that sell aliveness

These run at <1% CPU and are always active during AMBIENT state:

| Movement | Timing | Amplitude | Purpose |
|---|---|---|---|
| **Breathing** | 4.5s sine | scale 1.0 ↔ 1.03 | Life signal |
| **Drift** | 12s loop | ±1.5 px orbital | Not static |
| **Hover response** | On event | 1.0 → 1.06, 150ms | Responsive |
| **Wake pulse** | On event | 1.0 → 1.1 → 1.0, 200ms | Acknowledgment |
| **Micro-wobble** | Random, 8-15s intervals | ±0.3° rotation | Unpredictable, organic |
| **Shadow breathing** | Syncs with breathing | opacity 0.3 ↔ 0.5 | Grounding |
| **Aura shimmer** | Continuous | ±2px radial blur shift | Alive, not digital |

**The micro-wobble is critical.** It prevents the orb from feeling like a
looping animation. The wobble is a random rotation offset applied via
`Math.sin(Date.now() * randomPhase)`, where `randomPhase` is set once on
orb creation and never changes. Each orb instance has a unique wobble
signature — it's like a fingerprint.

### 2.4 Particle system evolution

Current implementation: 1000 particles on a sphere, expanding/contracting
with audio. This is functional but generic.

**Proposed evolution:**

1. **Particle memory.** Particles remember recent audio/RMS history. After
   speaking, particles retain a faint echo of the waveform shape for 3s
   before returning to sphere.
2. **State-specific particle behaviors:**
   - **Idle:** particles form a near-perfect sphere with micro-wobble. 2-3
     particles occasionally drift outward and snap back (like fireflies).
   - **Listening:** particles form a slightly flattened sphere (bottom-heavy,
     like a droplet). Ripple rings emanate from the "equator" every 0.8s.
   - **Thinking:** particles form two interlocking rings (like an atom model),
     counter-rotating. Inner ring 2.4s/turn, outer ring 3.6s/turn. Core dims.
   - **Speaking:** particles pulse with audio RMS. The sphere breathes with
     syllables — expand on voiced sounds, contract on pauses.
3. **Particle trails.** When the orb moves (drag, snap-to-edge), particles
   leave a 3-frame trail that fades. This makes motion feel physical, not
   teleported.
4. **Click feedback.** On single-click, a shockwave of 20 particles bursts
   outward from the click point on the orb surface, then fades. This is the
   "ripple" feedback from the spec.

---

## 3. Autonomous Behaviors

The orb is not a passive display. It does things on its own, within strict
bounds. These are the behaviors that make it feel like a companion, not a tool.

### 3.1 Time-aware presence

| Time | Behavior |
|---|---|
| First 30s after launch | Gentle wake-pulse + tooltip: *"I'm here."* |
| Morning (6-9 AM) | Brighter aura, tooltip: *"Good morning."* |
| Late night (11 PM-6 AM) | Dimmer orb, slower breathing (6s), no proactive whispers |
| User's birthday / anniversary (if in memory) | Special 3-pulse sequence, warm color shift |

### 3.2 Environmental awareness

The orb monitors (with explicit permission):

- **Calendar proximity.** If a meeting starts in <15 min, orb pulses gently
  every 2 min. Clicking opens the panel to the meeting details.
- **Email unread count.** If >5 unread, the notification dot appears. Hovering
  shows the count. Never interrupts voice.
- **System health.** CPU >90% for >30s → orb shifts amber briefly, then back.
  Disk <5% free → notification dot with warning.
- **Idle detection.** User idle >10 min → orb becomes slightly more animated
  (as if waiting). Idle >30 min → sleepy state.

### 3.3 Proactive whispers

These are the most "alive" behaviors. They make JARVIS feel like it's
*thinking about you*.

| Whisper | Trigger | Expression | Frequency cap |
|---|---|---|---|
| *"Your 2 PM meeting is in 15 minutes."* | Calendar event | Alert pulse + dot | Once per event |
| *"You have 3 unread emails."* | Mail count | Alert pulse + dot | Every 30 min max |
| *"Want me to summarize your unread mail?"* | Mail + idle >5 min | Warm glow + micro-bounce | Once per hour |
| *"I noticed you've been working on X for 2 hours."* | Active window + time | Warm glow | Every 2 hours |
| *"Would you like me to remember this?"* | Context clue in conversation | Curious ripple | Once per session |
| *"Battery is at 12%. Want me to find your charger?"* | Power low | Concerned pulse | Once |
| *"It's been a while — want to chat?"* | Idle >20 min, no notifications | Playful micro-bounce | Once per 4 hours |

**Rules for whispers:**
- Never during voice session.
- Never during typing in a focused input field.
- Dismissible by any orb click or ESC.
- Rendered as a tooltip on the orb, not a panel popup.
- Audio optional (soft chime toggleable).

### 3.4 Idle behaviors (when user is away)

When the user is idle (>5 min, no active window input):

1. **Breathing deepens.** The orb slows from 4.5s to 6s breath cycle.
2. **Drift becomes more pronounced.** The orb wanders ±3 px instead of ±1.5.
3. **Particle "dreaming."** 1-2 particles detach and orbit the orb at 2x
   radius for 10-15s, then reattach. This is the "dreaming" state.
4. **Ambient sound (optional).** A 20ms quiet tone at 432Hz plays every
   30s — like a cat purring. Completely optional, off by default.

---

## 4. Voice as Presence (not just input)

Voice is the primary channel, but it's also the primary expression of
JARVIS's personality.

### 4.1 Voice personality

| Aspect | Specification |
|---|---|
| **Voice** | Warm, neutral, slightly British (ElevenLabs "Rachel" or similar). Not robotic, not overly enthusiastic. |
| **Pacing** | 1.0x default. Slightly slower (0.95x) for complex information, slightly faster (1.05x) for casual chat. |
| **Pauses** | Natural pauses before lists, after questions. 300ms before "By the way..." |
| **Emphasis** | Subtle — raise pitch slightly on key words, not shouting. |
| **Humor** | Dry, understated. "I'd open that file, but I'm a floating orb. You'll have to do it." |
| **Empathy** | Acknowledges user emotion. "That sounds frustrating." "Nice work." |
| **Hesitation** | "Let me check..." / "One moment..." — always before a tool action or lookup. |

### 4.2 Listening feedback

When the user is speaking:

- **Transcript line** appears below the orb (or in the panel) in real-time.
- The orb's particles flatten slightly (listening posture).
- A soft cyan ring pulses at the orb's equator every 0.8s.
- The orb does **not** nod, bow, or do cartwheels. It listens.

### 4.3 Speaking feedback

When JARVIS is speaking:

- The orb's particles pulse with syllable energy.
- The panel (if open) shows the text streaming with a caret.
- The orb's core brightness modulates with speech amplitude.
- If the user interrupts (wake word / PTT), JARVIS stops instantly (≤100ms)
  and emits a single soft "mm-hmm" acknowledgment before listening.

### 4.4 Thinking feedback

When JARVIS is processing:

- Two counter-rotating arcs around the orb (inner 2.4s, outer 3.6s).
- Core dims to 70%.
- ≤6 particles drift outward slowly (like thoughts forming).
- Near-silent: a 50ms tick every 2s if audio state chimes are enabled.

---

## 5. The Drag Experience (Physical Presence)

Dragging the orb is not a window move. It is **carrying a physical object**.

### 5.1 Drag behavior

| Phase | Orb behavior | Physics |
|---|---|---|
| **Grab** | Scale 1.15×, aura widens 20%, shadow deepens | Instant (100ms) |
| **Drag** | Particles trail behind movement direction | Trail length ∝ speed |
| **Release** | Spring overshoot 1.02×, settle 1.0× | 300ms spring curve |
| **Snap to edge** | If released within 4px of screen edge, slide to edge with 200ms ease | Snap animation |
| **Release in void** | If released in middle of screen, float gently to nearest edge over 2s | Auto-dock |

### 5.2 Drop interactions

When the user drops a file or text on the orb:

1. **Impact ripple.** 12 particles burst outward from the drop point.
2. **Aura flare.** Aura brightness jumps to 100% for 300ms, then settles.
3. **Confirmation chime.** Soft 2-tone chime.
4. **Tooltip.** Brief tooltip: *"Got it. What shall I do with this?"*
5. **Panel opens** (if not already) to the appropriate tool view.

---

## 6. Expansion Model (Orb → Panel → Orb)

The expansion is not a window opening. It is the orb **unfolding**.

### 6.1 Expansion choreography

```
  ORB (64px)
    │
    ├─► click / Ctrl+Space / wake word
    ▼
  EXPAND (220ms)
    ├─ Orb shrinks to 40px anchor
    ├─ Panel materializes from orb position, expanding outward
    ├─ Panel slides with ease-out-cubic (220ms)
    └─ Orb resumes normal size (64px) at panel origin point
```

### 6.2 Panel as extension of the orb

- The panel header contains a **mini-orb** (20px) that mirrors the main orb's
  state in real-time.
- If the main orb is DRAGGED while the panel is open, the panel follows it.
- Collapsing the panel reverses the choreography: panel slides back into the
  orb position, orb pulses once (confirmation).

### 6.3 Collapse triggers (in priority order)

1. **ESC** — instant collapse, no animation delay.
2. **Click-away** — 300ms grace period, then collapse.
3. **Chevron button** — immediate.
4. **Voice command** — "collapse" / "go away" / "minimize."
5. **Orb click while panel open** — toggle.

---

## 7. Memory as Continuity

JARVIS remembers. This is not a database feature — it is the substrate of
personality.

### 7.1 Session memory

- Every conversation is stored with timestamp, topic tags, and sentiment.
- When the user returns after hours/days, JARVIS may reference the last
  conversation: *"We were talking about your Rust project yesterday. Want to
  continue?"*
- This appears as a tooltip on the orb, not a panel popup.

### 7.2 Preference learning

- JARVIS learns: preferred response length, preferred TTS voice, working hours,
  common tasks, project contexts.
- These are surfaced as subtle adjustments, not settings changes. If the user
  always asks for brief answers, JARVIS gradually shortens responses and
  mentions: *"Keeping it brief, as you prefer."*

### 7.3 Relationship memory

- JARVIS remembers names (user, colleagues, family mentioned in conversation).
- It remembers significant dates (birthdays, project deadlines).
- It remembers "favorites" (preferred music for focus, preferred terminal
  emulator, preferred coding font).

---

## 8. Error & Edge Case Behaviors

Errors should not break the illusion of aliveness.

| Scenario | Orb behavior | Panel behavior |
|---|---|---|
| Backend down | Grey orb, no aura, static. One slow red pulse, then stays still. | Banner: *"I'm disconnected. Check the backend."* |
| STT no speech | Orb returns to idle with soft chime. No verbal apology. | Nothing. |
| LLM timeout | Orb does ERROR state (red arc, 2 pulses). | *"That took too long — try again?"* with retry button. |
| Mic busy | Orb does ERROR state. | *"Microphone is in use elsewhere."* |
| Permission denied | Orb does ERROR state. | *"I need permission for that. Open Settings?"* |

**Rule:** The orb never spins forever. The orb never looks broken. Every error
state resolves to a known state within 2s.

---

## 9. The "Not an Application" Contract

These are the non-negotiable rules that keep JARVIS from feeling like software:

1. **No splash screen.** The orb appears with a wake pulse.
2. **No update dialogs.** Updates download silently; the orb pulses once when
   ready: *"Updated. Restart when you're ready."*
3. **No crash reports.** Failures are graceful. The orb goes to ERROR state,
   then recovers.
4. **No telemetry.** Nothing leaves the machine without explicit action.
5. **No forced onboarding.** First run happens at the orb: one question at a
   time, voice-first.
6. **No menus.** The orb has gestures and voice. Menus are context menus on
   right-click only.
7. **No chrome.** No title bars, no window controls on the panel. The panel
   has a chevron and a mini-orb, nothing else.
8. **No taskbar entry.** The orb lives above all windows. The tray icon mirrors
   it.
9. **No "Save" buttons.** Settings save instantly. The mini-orb pulses once
   (confirmation).
10. **No "Are you sure?" for safe actions.** Reading files, searching, opening
    apps: done immediately. Destructive actions: confirmation card.

---

## 10. Accessibility & Inclusivity

Aliveness must not exclude.

| Need | Provision |
|---|---|
| **Low vision** | State chimes (toggleable). High-contrast orb colors. Screen reader: orb exposes state via `aria-live`. |
| **No mouse** | Full keyboard: Tab focuses orb, Enter = quick actions, Ctrl+Space = panel, Esc = dismiss. |
| **Reduced motion** | All ambient animation collapses to static glow + 80ms cross-fades. Orb still breathes (scale only, no particles). |
| **Deaf / hard of hearing** | Visual state indicators on orb are mandatory. Transcript always visible. |
| **Neurodivergent** | Motion toggle. Predictable state transitions (no sudden changes). Calm color palette. |

---

## 11. Implementation Mapping

### 11.1 Current → Target state

| Component | Current | Target |
|---|---|---|
| **Orb window** | 80x80 frameless, loads `bubble.html` → `bubbleMain.tsx` → `bubble.tsx` | Same window, but `bubble.tsx` redesigned with full state machine, micro-movements, particle memory, personality |
| **Orb visualization** | Three.js particles on sphere, state color changes | Particle memory, state-specific formations, micro-wobble, trails, click shockwave |
| **Main window** | 480x720, traditional frame, large orb at center | Compact floating panel (380x560), frameless, glass, anchored to orb |
| **Expansion** | Toggle main window near bubble position | Orb shrinks to 40px anchor, panel unfolds from it (220ms choreography) |
| **Drag** | Electron IPC moves bubble window | Same IPC, but add particle trails, spring release, auto-dock |
| **Wake word** | Vosk keyphrase, bubble has separate WS | Bubble handles wake word exclusively; on detection, bubble notifies main window via IPC |
| **Voice** | WebSocket from main window | Bubble maintains its own WS for wake; main window WS for voice session |
| **Auto-hide** | None | Orb docks to nearest edge when dragged near; edge-docking with 4px "park" inset |
| **Tray** | Basic menu | Mirrors orb state; tray icon has live animation (where supported) |
| **Proactive** | Backend ProactiveMonitor broadcasts via WS | Frontend handles proactive messages as whisper tooltips on orb |

### 11.2 New files needed

| File | Purpose |
|---|---|
| `jarvis_frontend/src/orb/OrbEngine.tsx` | Core orb component with state machine, personality, autonomous timers |
| `jarvis_frontend/src/orb/useOrbPersonality.ts` | Hook: warmth, micro-movements, wobble signature |
| `jarvis_frontend/src/orb/useAutonomousBehaviors.ts` | Hook: time-aware, environmental, idle behaviors |
| `jarvis_frontend/src/orb/useParticleMemory.ts` | Particle trail and echo system |
| `jarvis_frontend/src/panel/Panel.tsx` | Compact floating panel (replaces main window's 480x720 design) |
| `jarvis_frontend/src/panel/usePanelChoreography.ts` | Expansion/collapse animation, orb anchoring |
| `jarvis_frontend/src/panel/views/` | Chat, Memory, Files, Models, Plugins, Settings views |

### 11.3 Electron changes

| File | Change |
|---|---|
| `electron/main.js` | Main window: frameless, transparent, 380x560, no title bar. Add `setIgnoreMouseEvents` for panel pass-through. Add edge-docking logic. |
| `electron/preload.js` | Add IPC for: `dock-to-edge`, `get-work-area`, `set-panel-opacity`, `start-idle-monitor`. |
| `electron/main.js` | Tray: animated icon support. Context menu: Talk, Chat, Memory, Files, Settings, Quit. |
| `electron/main.js` | Auto-hide: orb hides when user switches to fullscreen apps (detect via `app.on('browser-window-focus')` + fullscreen check). |

---

## 12. Performance Budget (aliveness cannot lag)

| Metric | Budget | Current |
|---|---|---|
| Orb idle CPU | < 1% | ~2% (particle system needs optimization) |
| Orb idle RAM | < 60 MB | ~80 MB (Three.js overhead) |
| Panel open → first paint | < 100 ms | ~200 ms (lazy load views) |
| State transition latency | < 100 ms | ~50 ms (good) |
| Wake → chime latency | < 900 ms | ~800 ms (good) |
| Voice round trip | ≤ 10s p95 | ~8s (good) |
| Particle count | 600 (down from 1000) | 1000 |
| Animation frame time | < 8ms | ~12ms (needs optimization) |

**Optimization strategies:**
- Reduce particles to 600 with better distribution.
- Use `requestAnimationFrame` with frame skipping when tab is hidden.
- Pause particle simulation when orb is occluded or display is asleep.
- Use CSS transforms for orb breathing instead of JS where possible.
- Batch particle position updates (typed arrays, no object allocation in loop).

---

## 13. The Emotional Contract

When the user installs JARVIS, they are entering a relationship, not using a
product. The emotional contract is:

> *I am here. I listen. I remember. I help. I stay out of your way unless
> you want me. I never surprise you with things you didn't ask for. I never
> pretend to be human, but I am present.*

The orb is the physical manifestation of this contract. Every animation,
every sound, every proactive whisper is a word in that contract.

---

*End of Interaction Model. This document defines the behavioral layer.
Implementation follows in the codebase under `jarvis_frontend/src/orb/`
and `jarvis_frontend/src/panel/`.*
