# JARVIS Source Code - File Manifest

Generated: August 9, 2026  
Backend: ~15,000 Python LOC · 104 files (81 source + 22 test files + conftest)  
Frontend: ~14,300 TS/TSX/CSS LOC · 6 test files  
Electron: 2 files (~1,030 LOC)

## Project Structure

### Backend (`jarvis_backend/`)

**Entry point**
- `main.py` (588 lines) - FastAPI app: 25 routers, WS `/ws/voice` streaming pipeline, security middlewares (CSP, rate-limit, perf), SPA static hosting

**Route modules** (`routes/` - REST + WS endpoints)
- `state.py` (755) - shared singletons, command processing, skill registry, profile notes, TTS streaming helpers
- `deps.py` (71) - backward-compatible re-exports of singletons/helpers
- `auth.py` · `system.py` · `stt.py` · `settings.py` · `vision.py` · `vault.py` · `tools.py` · `search.py` · `voice.py` · `llm.py` · `mail.py` · `notes.py` · `calendar.py` · `memory.py` (310) · `tasks.py` · `automation.py` · `adaptive.py` · `proactive_ai.py` · `security.py` · `performance.py` · `projects.py` · `git_routes.py` · `code_routes.py` · `models.py` · `plugins.py`

**Manager layer** (`managers/` - domain services)
- `memory_manager.py` (999) · `conversation_manager.py` · `system_manager.py` · `stt_manager.py` · `tts_manager.py` · `voice_manager.py` · `audio_manager.py` · `vision_manager.py` · `model_manager.py` · `security_manager.py` · `performance_manager.py` · `project_manager.py` · `git_manager.py` · `code_manager.py` · `task_manager.py` · `workflow_manager.py` · `adaptive_intelligence.py` · `proactive_ai.py`

**Modules** (`modules/` - core capabilities)
- `llm_provider.py` (393) - Mistral/Anthropic/Ollama providers + NVIDIA rerank
- `stt.py` (340) - Vosk offline STT + streaming recognizer + wake-word spotter
- `tts.py` (253) - ElevenLabs → Edge TTS → local engine fallback chain
- `mail_module.py` (301) · `calendar_module.py` · `notes_module.py` · `documents_module.py` · `web_browse.py` · `system_actions.py` (245) · `auth.py` · `audit.py` · `proactive.py` (193) · `settings.py` · `skill_registry.py` · `vision_module.py` · `claude_api.py`
- `vault/` - markdown vault: `manager.py` (513), `search.py`, `store.py`, `codec.py`, `templates.py`

**Plugin system** (`plugins/`)
- `base.py` · `registry.py` · `loader.py` · `permissions.py` · `builtin/skills.py` (calendar/email/web/weather/translate/system/notes)

**Tests** (`tests/` - 22 files)
- Cover auth, memory, STT/TTS, vault, vision, WS voice, new routes, plugin skills, calendar/mail/notes/documents modules

### Frontend (`jarvis_frontend/src/`)

- `App.tsx` (918) - main panel: WS lifecycle, recording, endpointing, TTS queue, error classification
- `bubble.tsx` (911) - floating orb: wake-word listener, PTT, hands-free command capture, reply + TTS playback
- `audioStream.ts` · `voiceStateMachine.ts` · `voiceDiagnostics.ts` · `bubbleMain.tsx` · `main.tsx`
- `components/` - `VoiceOrb.tsx` (Three.js particles), `MemoryPage.tsx`, `Settings.tsx`, `Onboarding.tsx`, `ToastProvider.tsx`, `NotificationToast.tsx`, `LoadingSpinner.tsx`
- `orb/` - `OrbEngine.tsx`, `useAutonomousBehaviors.ts`, `useMicroMovements.ts`, `useOrbWarmth.ts`, `useParticleMemory.ts`
- `panel/` - `Panel.tsx`, `usePanelChoreography.ts`, 15 views (`ChatView`, `MemoryView`, `FilesView`, `ModelsView`, `PluginsView`, `SettingsView`, `TasksView`, `ToolsView`, `ProjectsView`, `CodeView`, `AdaptiveView`, `AutomationView`, `PerformanceView`, `SecurityView`, `ProactiveView`)
- `api/` - typed API clients (memory, vault, vision, tasks, tools, plugins, security, performance, adaptive, automation, proactive, developer)
- `public/` - `pcmWorklet.js` (audio capture worklet), icons, manifest, `sw.js`

### Electron (`electron/`)
- `main.js` (971) - window/tray management, backend subprocess, keychain (keytar), auto-update, IPC
- `preload.js` (61) - contextBridge API

### Tests
- Backend: 22 test files (pytest)
- Frontend: 6 test files (Vitest: `api/vault.test.ts`, `audioStream.test.ts`, `bubble.test.tsx`, `components/VoiceOrb.test.tsx`, `voiceDiagnostics.test.ts`, `voiceStateMachine.test.ts`) + `tests/e2e/app.spec.ts` (Playwright)

## Technologies

- **Backend**: FastAPI, Uvicorn, SQLite (WAL + FTS5), aiosqlite, Vosk, edge-tts, httpx, psutil, Pillow/pytesseract
- **Frontend**: React 18, TypeScript 5, Vite, Three.js, AudioWorklet, Vitest, Testing Library
- **Desktop**: Electron 30, electron-builder, electron-updater, keytar

## DevOps

- `scripts/` - venv prep, Vosk model download, electron binary fixes
- `docker-compose.yml` · `.github/workflows/ci.yml` (ruff, black, eslint, prettier, tsc, vitest, pytest, build)

## Documentation

`AGENTS.md` · `JARVIS_README.md` · `ARCHITECTURE.md` · `DESKTOP_COMPANION_SPEC.md` · `IMPLEMENTATION_ROADMAP.md` · `INTERACTION_MODEL.md` · `UI_DESIGN.md` · `WS_PROTOCOL.md` · `VOICE_PIPELINE_PHASE2/3/4.md` · `DEPLOYMENT.md` · `QUICKSTART.md` · `FILE_MANIFEST.md`
