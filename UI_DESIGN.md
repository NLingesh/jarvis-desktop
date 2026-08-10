# JARVIS — Desktop AI Assistant
## UI/UX Design System · v1.0

> A premium, minimal, futuristic interface for a voice-first personal AI operating system.
> Inspired by the discipline of Apple, the product-thinking of OpenAI, the craft of Arc/Raycast, and the clarity of Fluent Design — **not** a copy of any movie HUD.

---

## 1. Design Principles

1. **Calm intelligence.** The system is confident and quiet. Nothing shouts. Glow is used as punctuation, never decoration.
2. **Voice-first, interface-last.** JARVIS is an ambient presence. The deepest, most immersive surface (Voice) is one word or one tap away; every other surface exists to make the voice loop sharper.
3. **Three depths, one system.**
   - **Ambient** — the bubble. A 96px floating presence that lives above all windows.
   - **Focus** — Voice mode. Full-screen, edge-to-edge, single idea at a time.
   - **Workspace** — Chat / Memory / Files / Models / Plugins / Settings. Precision tools on glass.
4. **Zero visual clutter.** Every element must earn its place. If it can be implied, don't render it. If it can collapse, collapse it.
5. **Motion is meaning.** Animated state *is* the status. The orb, the mic, and the voice ripples communicate state faster than any label — and always sit below the threshold of attention.
6. **Legibility over novelty.** White text, generous spacing, 4px rhythm, real hierarchy. The future is calm, not noisy.

---

## 2. Design Tokens

### 2.1 Color

| Role            | Token             | Value      | Usage |
|-----------------|-------------------|------------|-------|
| Background      | `bg-base`         | `#090B10`  | App canvas, full-screen voice |
| Surface         | `bg-surface`      | `#10141D`  | Sidebar, cards, sheets |
| Surface-2       | `bg-surface-2`    | `#151B28`  | Hover, raised cards |
| Surface-3       | `bg-surface-3`    | `#1A2233`  | Active panels, code blocks |
| Primary         | `accent-cyan`     | `#00C8FF`  | Actions, focus, orb core, live states |
| Secondary       | `accent-blue`     | `#38BDF8`  | Links, secondary focus, gradients |
| Success         | `status-ok`       | `#22C55E`  | Connected, saved, done |
| Warning         | `status-warn`     | `#FACC15`  | Attention, low storage, waiting |
| Error           | `status-error`    | `#EF4444`  | Offline, failed, denied |
| Text primary    | `text-1`          | `rgba(255,255,255,.92)` | Headlines, bodies |
| Text secondary  | `text-2`          | `rgba(255,255,255,.62)` | Labels, meta |
| Text muted      | `text-3`          | `rgba(255,255,255,.38)` | Placeholders, hints |
| Border          | `stroke`          | `rgba(255,255,255,.06)` | Hairlines between surfaces |
| Border strong   | `stroke-strong`   | `rgba(255,255,255,.12)` | Inputs, focus rings |
| Glass           | `glass`           | `rgba(16,20,29,.72)` + `backdrop-filter: blur(24px) saturate(140%)` | Sidebar, sheets, bottom bar |

**Gradients.** Use sparingly and always anchored on the brand:
- `accent-flow`: `#00C8FF → #38BDF8` (120°) — orb core, primary CTAs, active nav.
- Never full-rainbow. Warmth comes from the user's content, not chrome.

### 2.2 Typography

**Family.** A modern variable sans — `Inter` (or `SF Pro Display` on macOS). Display weights use tight tracking; UI uses the same family for system coherence. Code uses `JetBrains Mono` / `SF Mono`.

| Style    | Weight | Size  | Line | Tracking  | Use |
|----------|--------|-------|------|-----------|-----|
| Display  | 700    | 56    | 1.05 | -0.03em  | Home hero, "Good evening" |
| Title    | 650    | 28    | 1.2  | -0.02em  | Screen headers |
| Heading  | 600    | 20    | 1.3  | -0.015em | Card titles, sections |
| Subhead  | 500    | 15    | 1.4  | -0.01em | Message meta, list titles |
| Body     | 450    | 14    | 1.55 | 0        | Messages, bodies |
| Caption  | 450    | 12    | 1.4  | +0.01em | Status bar, timestamps |
| Micro    | 500    | 11    | 1.3  | +0.08em | Uppercase labels, badges |
| Code     | 450    | 13    | 1.5  | 0        | Code blocks |

**Hierarchy rules.** Max 3 visible text sizes per surface. Uppercase micro-labels get `+0.08em` tracking and `text-3` — they are the quiet connective tissue of the UI.

### 2.3 Spacing (4px grid)

`4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 48 · 64 · 96`

- Cards: 24px padding. Screen gutters: 32px (workspace), 48px (voice).
- Lists: 8px row gap, 40px section gap.
- Never center text in full-bleed layouts; voice surfaces left-align.

### 2.4 Radius & Elevation

| Token       | Value |
|-------------|-------|
| `r-sm`      | 8px  |
| `r-md`      | 12px |
| `r-lg`      | 16px |
| `r-xl`      | 24px |
| `r-full`    | 999px |

- Sidebar: 0 (edge-to-edge). Cards: 16px. Sheets/bottom bar: 20px top corners. Mic button: full.
- Elevation = soft ambient shadow + hairline. `0 8px 32px rgba(0,0,0,.45)` for floating panels; `0 1px 0 rgba(255,255,255,.03) inset` for depth. Glass panels get no heavy shadow — blur is the depth.

### 2.5 Iconography

- **Lucide-style**: 24px grid, 1.6px stroke, rounded caps. Never filled except active state (filled = focused/selected).
- Active nav item: filled icon + cyan tint + 2px left indicator.
- Keep icon + label together in the sidebar; tooltips only in dense contexts (status bar).

---

## 3. Application Shell

### 3.1 Frame
- Native window chrome replaced by an in-app 44px title bar (draggable, glass).
- Title bar contents: window controls (left on macOS, right on Windows/Linux), centered "JARVIS" wordmark in Micro caps, right-aligned global status dot.
- Resize to any width; the shell is responsive. Below 760px the sidebar collapses to 72px icons-only.

### 3.2 Left Sidebar (72px · 232px expanded)
Glass surface, full height, 1px right hairline.

| Item     | Icon | Behavior |
|----------|------|----------|
| Chat      | message-square | Default surface on launch |
| Voice     | mic            | Full-screen immersive mode |
| Memory    | book-open      | Vault explorer |
| Files     | folder         | Document workspace |
| Models    | cpu / sparkles | Model manager |
| Plugins   | puzzle         | Plugin manager |
| Settings  | sliders-horizontal | Settings (pinned to bottom) |

- Collapse toggle at sidebar top; expands/collapses with a 240ms ease-out.
- Active item: cyan filled icon + 2px left indicator + `accent-cyan@12%` wash.
- A status avatar (user) lives at the sidebar base, above Settings.

### 3.3 Bottom Status Bar (44px)
Glass, full width, hairline top.

| Segment (left→right) | Content |
|----------------------|---------|
| Microphone | Mic glyph + state dot (`idle`/`live`) — clicking starts a voice session from anywhere |
| Connection | "Online · 127.0.0.1" or "Offline" in `status-error` |
| Model | Active model chip, e.g. `mistral-nemotron` |
| Memory | `2.1 GB / 8.4 GB` + small progress hairline (replaces "Memory Status") |
| GPU | Load % + tiny sparkline, cyan when idle, amber when heavy |

---

## 4. The Arc Reactor (Core Visual Language)

**Do not render an Iron Man circle.** The Reactor is a reductive, abstract instrument:

- **Center core** — a 20px disc, `accent-flow` gradient, soft bloom (`box-shadow: 0 0 40px 8px rgba(0,200,255,.35)`).
- **Two concentric rings** (thin 1px, `accent-cyan@28%`), orbiting the core at differing radii.
- **One radial tick ring** — 12 hairline ticks, only the "front" tick is fully opaque; they act as a compass of attention.
- Everything monochrome-cyan. Motion is constant but slow; state changes alter *speed and bloom*, never shape.

### State → Motion map (Voice mode & bubble share this grammar)

| State     | Core   | Ring A (outer) | Ring B (inner) | Bloom    | Duration |
|-----------|--------|----------------|----------------|----------|----------|
| **Idle**  | steady | 24s/turn       | 40s/turn       | 0.35 low | —        |
| **Listening** | pulse 1.2s ease-in-out (1→1.15 scale), 8% brightness wobble | 6s/turn | still | 0.45 | pulse = 1200ms |
| **Thinking**  | 0.9s wobble, core dims 20% | **fast** 1.6s/turn | counter-rotate 2.2s | 0.3 low | rotate 1600ms |
| **Speaking**  | 180° wave — ring amplitude oscillates (2.4s) | 4s/turn | 3s/turn | 0.5 | wave 2400ms |
| **Offline**   | static, no bloom, 60% opacity | still | still | 0 | — |
| **Error**     | 2 quick fades (0.4s) into dim static, amber-red tint | still | still | 0.1 | 400ms |

Rules: transitions between states ease over 300ms `cubic-bezier(.22,1,.36,1)` (no cuts). Never animate faster than the user can parse. Reduced-motion users get the Idle state with a 1px status label instead.

---

## 5. Screens

### 5.1 Home
A welcome surface, not a dashboard.

- **Hero (top-left aligned)**
  - Greeting (Display): "Good evening." + time-aware microline "It's 21:42. 14 minutes until tomorrow's first meeting."
  - Subline (Body, `text-2`): one generated suggestion — "You have 3 unread emails. Want me to summarize them?"
  - **The Reactor** floats center-right at 168px as a presence, not a decorative badge.
- **Recent chats** — horizontal scroll cards (glass, 16px radius): title, last snippet (1 line), time. 4 shown.
- **Suggested actions** — 3 ghost buttons: `Summarize unread mail`, `Start voice session`, `Add a memory note`.
- **Quick commands** — a compact Raycast-style input with `⌘K` hint; typing triggers a command palette (actions, files, models).
- **Recent projects** — 2×2 glass grid: folder icon, name, modified time, hover reveals "Open" affordance.
- Empty states are intentional: when there's no data, the hero greeting expands and the rest collapses — never render empty shells.

### 5.2 Chat
Claude-meets-ChatGPT, tighter.

- **Canvas**: `bg-base`, content column max 760px, 32px gutters.
- **Message bubbles**: user = `bg-surface-3` 16px radius, right-aligned, 90% max width, white text. Assistant = no bubble — flush text on `bg-base` with an inline Reactor dot (12px) at the left of the first line. This asymmetry (user boxed, assistant open) is the Claude/Apple signature.
- **Streaming**: caret pulse after the last partial token; the Reactor dot shrinks to 8px while tokens flow.
- **Markdown**: headings sized to the Body scale, tables with hairline strokes, inline code on `bg-surface-3`, lists with 8px gaps.
- **Code blocks**: `bg-surface-3` card, 12px radius, header row with filename + copy button, mono 13px, 16px padding. Language chip in Micro caps.
- **Image previews**: rounded 12px, max 320px, click to open native lightbox.
- **Message actions (hover)**: Copy, Regenerate, thumbs. Fade in at 120ms, appear above the bubble on the outside edge.
- **Composer**: glass pill, 12px radius, send button = 32px Reactor-core disc. `Enter` sends, `Shift+Enter` newline. Mic icon on the left edge opens Voice.
- **Typing indicator**: 3 dots, 6px, staggered 300ms, `accent-cyan`.

### 5.3 Voice (Full-Screen Immersive)
The hero of the product.

- **Canvas**: `bg-base` fading to `rgba(0,200,255,.03)` at the vertical center. No sidebar, no status bar — the surface owns the frame.
- **The Reactor** is centered at **240px** — the largest, slowest, most beautiful object in the product.
- **Transcript line** (Body, 20px, `text-1`, centered under the core): live STT captions update in place (no flicker — replace text, never re-render the line).
- **Reply line** (Body, 16px, `text-2`): the assistant's last spoken sentence fades in as it speaks.
- **Meta strip** (Micro caps, `text-3`): current state label only — `LISTENING` · `THINKING` · `SPEAKING` · `OFFLINE` · `ERROR: COULD NOT HEAR ANYTHING`.
- **Mic affordance**: a 96px floating glass disc at the bottom-center. Idle: hairline ring. Live: filled `accent-flow`, continuous ripple (see §6).
- **Exit**: ESC fades the surface out 240ms back to the previous mode. A minuscule "×" ghost button top-right for mouse users.
- Offline/Error states: Reactor dims, meta strip shows the cause, mic shows a 1px `status-error` ring — never a modal, never a crash dialog.

### 5.4 Memory (Obsidian-Inspired Vault)
Three-pane, glass.

- **Pane 1 · Tree (240px)** — folders (People, Projects, Ideas) + tag list (`#work`, `#reminders`). Folders expand/collapse with 160ms ease.
- **Pane 2 · List (280px)** — search input (glass pill) at top; results: title, 1-line preview, tags, timestamp. Sort tabs: `Recent · Files · Tags`.
- **Pane 3 · Preview (flex)** — markdown-rendered note with live edit toggle. Header: title, tag chips, `Edit`/`Done` ghost buttons.
- **Profile note** (`People/me.md`) is pinned at the top of the tree with a "you" glyph — the system's memory of the user, always one click away.
- Empty folder state: one line, "Nothing here yet. Ask JARVIS to remember something."

### 5.5 Files
- Workspace grid of document cards: type glyph, name, modified, size. Hover: Open / Copy path.
- **New document** flow starts from voice or command palette, not a button maze.
- Search across documents + notes together (single index).

### 5.6 Models / Model Manager
- **Top bar**: storage usage (progress hairline), `Download model` primary CTA.
- **Installed list**: glass cards — name, size, status chip (`Ready` = `status-ok`, `Downloading 42%` = `status-warn` with progress), **RAM** and **GPU** requirement chips, expand for details (context length, latency class, quantization).
- **Download drawer**: model catalog with size + RAM/GPU requirement badges; disabled rows show *"Insufficient VRAM (8 GB required)"* in `status-warn`.
- Sort by: Latency · Quality · Size.

### 5.7 Plugins
- Grid of plugin cards: icon, name, 1-line description, enabled toggle.
- Categories as chips: `Productivity · Media · Dev · Custom`.
- A plugin's card expands to show permissions ("Reads calendar, writes notes") — transparency is a feature, styled as quiet meta, not a warning wall.

### 5.8 Settings
Sidebar-of-sections pattern (like macOS System Settings) — list on the left, content on the right. Sections:

1. **General** — launch at login, language, time/date format.
2. **Appearance** — theme (Dark / System / Light for the light-theme minority), accent (Cyan default), density.
3. **Voice** — wake word on/off, always-on listening, bubble behavior, TTS voice + speed + volume.
4. **Speech Recognition** — model status, device, sensitivity (endpointing), language.
5. **AI Models** — active model, provider keys (masked), fallback order.
6. **Memory** — vault path, storage, "forget everything" (two-step confirm, red).
7. **Plugins** — enable/disable, permissions summary.
8. **Developer** — log level, WebSocket URL, port, copy diagnostics.
9. **Advanced** — proxy, GPU toggle, reset.

Settings values save instantly (no Save button); a subtle "Saved" toast (2s, `status-ok`) confirms.

---

## 6. The Microphone Button

The single most-used control. Rules:

- **Resting**: 56px glass disc, hairline ring, mic glyph `text-1`.
- **Hover**: ring fills to `accent-cyan@18%`, 1px `accent-cyan` ring, 120ms.
- **Pressed/Recording**: disc fills `accent-flow`, glyph inverts, **ripple** = two expanding rings (1px → 60px, opacity .35 → 0, 1.4s, staggered 700ms). The ripple loop is the "recording" animation.
- **Listening indicator**: a 3px arc sweeps the ring (2.4s) + micro label `LISTENING` appears above.
- **Trigger from anywhere**: the status-bar mic (44px, same visual grammar, compact ripple).

---

## 7. The Bubble (Ambient Mode)

The always-on-top presence. Keep it tiny and quiet.

- 96px glass circle, 1px hairline, Reactor at 56px core, subtle idle rotation.
- **Hover**: expands a soft halo (radial glow), reveals a 32px PTT chevron at the bottom.
- **Wake word heard**: 1.5s chime pulse — ring expands to 120px once, then settles to Listening state.
- **Always-on listening**: a 1px cyan ring stays lit.
- Click bubble → opens the main window. Long-press (500ms) → starts a voice session directly (PTT).
- Draggable; 12px shadow; respects screen edges (snaps at 12px).

---

## 8. Motion System

**Easing.** Primary `cubic-bezier(.22,1,.36,1)` (ease-out-quint style). Entrances 240–320ms, exits 180–220ms, color 150ms, shared-element 400ms.

**Duration map**

| Motion | ms | Ease |
|--------|----|------|
| Nav swap (screen change) | 260 | ease-out |
| Sidebar collapse | 240 | ease-out |
| Card hover | 150 | ease-out |
| Bubble → window transition (shared element) | 400 | spring-ish ease |
| Orb state transition | 300 | ease-out |
| Toast | 220 in / 300 out | ease-in-out |
| Reduced motion | all → 0 (cross-fade only) | — |

**Principles.** No bounce. No overshoot. Elements animate in the direction they came from. Lists stagger 30ms/item. Never animate layout width/height if `transform` will do. All motion is optional behind `prefers-reduced-motion`.

---

## 9. States & Feedback

| Situation | Feedback |
|-----------|----------|
| Action completes | Micro toast bottom-center, 2s |
| Voice can't hear | Reactor → Error, meta shows cause, mic ring `status-error` |
| Model downloading | Card progress hairline + `status-warn` chip |
| Saving memory | 300ms "saved" tick on the note header |
| Offline | Status bar dot `status-error`, orb stops glowing (never a blocking dialog) |
| No results | One-line graceful empty state with a suggested next step |

---

## 10. Accessibility & Craft

- **Contrast**: all text ≥ 4.5:1 on its surface; `text-3` only for non-essential meta ≥ 3:1.
- **Focus**: 2px `accent-cyan` ring with 8px offset on glass (never suppressed).
- **Keyboard**: full tab order, `⌘K` palette, `Esc` dismisses all overlays, `Space` = talk (when not typing).
- **Reduced motion**: static orb + text state labels replace all animation.
- **Hit targets ≥ 40px**. Touch (Windows) gets 48px targets.
- **i18n-ready**: no text baked into visuals; greeting is time-aware and locale-aware.

---

## 11. Tone of Voice (UI Copy)

- One-line, declarative, warm: "Say something." · "Done." · "Nothing here yet."
- Errors state the cause, not the blame: "Couldn't hear anything — check your mic or speak up."
- Never use ALL CAPS except Micro labels. Never use exclamation marks.

---

## 12. Screen Map (Navigation Flow)

```
Launch ──► Home ──► [Chat] [Voice] [Memory] [Files] [Models] [Plugins] [Settings]
                 │        │        │        │        │        │         │
                 │        └────────┴────────┴────────┴────────┴─────────┘  (sidebar)
                 └─ bubble (ambient) ◄── wake word / PTT ──► Voice (full-screen)
                      │
                      └── click ──► main window (returns to last surface)
```

Voice is reachable from: sidebar, bottom-bar mic, bubble PTT, `⌘Space`, or wake word. It always returns to where you were.

---

## 13. Implementation Notes (for the existing app)

- The current `VoiceOrb`, `bubble`, `App.tsx` surfaces should be restyled to this system without changing their interaction contracts.
- Introduce tokens as a single source (`tokens.css`) before restyling any screen.
- Ship Home + Voice restyle first (the emotional core), then Chat, then the workspace tools.
- Add `Files`, `Models`, `Plugins`, and the persistent Sidebar as new surfaces; keep the existing Memory vault and Settings data contracts.
