# JARVIS — Implementation Roadmap (Phases 9-13)

> Continues from Phase 1-8 roadmap. Assumes Phases 1-8 are complete.

---

## PHASE 9: AUTOMATION
**Goal:** Scheduled tasks, reminders, rules, workflows, background jobs, daily summaries.

### 9.1 Current State
- `ProactiveMonitor`: calendar + email checks every 5 minutes
- No task scheduling
- No reminders
- No workflows
- No background jobs
- `tasks` table exists in SQLite but is unused for scheduling

### 9.2 Folder Structure
```
jarvis_backend/
  managers/
    task_manager.py       # NEW: scheduled tasks, reminders, jobs
    workflow_manager.py    # NEW: rule-based automation
  modules/
    proactive.py          # DEPRECATE: move logic into TaskManager
jarvis_frontend/src/
  panel/views/
    TasksView.tsx         # NEW: task list, scheduler, workflow builder
```

### 9.3 New Modules
| Module | Responsibility |
|---|---|
| `TaskManager` | Scheduled tasks, reminders, one-shot + recurring, persistence, execution, retry |
| `WorkflowManager` | Rule-based triggers → actions, if/then logic, user-defined workflows |

### 9.4 Existing Files To Modify
| File | Changes |
|---|---|
| `modules/proactive.py` | Deprecate; migrate calendar/email checks into `TaskManager` |
| `routes/state.py` | Add task execution in voice pipeline ("remind me to...") |
| `MemoryManager` | Extend `tasks` table with scheduling fields (cron, next_run, enabled) |
| `panel/views/ToolsView.tsx` | Add automation section linking to TasksView |

### 9.5 Dependencies
```
# Backend additions
apscheduler==3.10.4
croniter==2.0.5
```

### 9.6 API Changes
- `GET /api/tasks` — list tasks/reminders
- `POST /api/tasks` — create task/reminder
- `POST /api/tasks/{id}/complete` — mark complete
- `DELETE /api/tasks/{id}` — delete task
- `GET /api/workflows` — list workflows
- `POST /api/workflows` — create workflow
- `POST /api/workflows/{id}/execute` — execute workflow manually
- `POST /api/automation/daily-summary` — trigger daily summary generation

### 9.7 React Changes
- `TasksView.tsx`: Task list with create/edit/delete, recurrence toggle, due date picker
- `ChatView.tsx`: Show reminder cards inline
- Orb: Pulse when reminder is due

### 9.8 Electron Changes
- Add IPC for native notification permissions (if not already granted)
- Add IPC for background task execution when app is hidden

### 9.9 Backend Changes
1. Implement `TaskManager` with APScheduler
2. Implement `WorkflowManager` with rule engine
3. Migrate `ProactiveMonitor` logic into `TaskManager`
4. Extend `tasks` table schema
5. Add API routes
6. Wire task execution into voice pipeline

### 9.10 Testing Strategy
- Backend: Task CRUD, scheduling, execution
- Backend: Workflow creation and execution
- Backend: Daily summary generation
- Frontend: TasksView rendering and interaction

### 9.11 Risks
| Risk | Mitigation |
|---|---|
| Scheduler drift over long uptimes | Persist next_run to DB; resync on startup |
| Missed reminders when app closed | Use system cron as fallback for critical reminders |
| Workflow complexity | Keep rule engine simple (if/then/else); avoid full programming language |

### 9.12 Expected Result
- "Remind me to call mom at 3pm" → creates reminder, orb pulses at 3pm
- Daily summary delivered at user's preferred time
- Workflows: "If calendar event starts in 15 min, show notification"
- Background jobs for vault reindex, memory cleanup

### 9.13 Checklist
- [ ] `TaskManager` implemented with APScheduler
- [ ] `WorkflowManager` implemented
- [ ] `ProactiveMonitor` migrated
- [ ] Tasks table extended
- [ ] API routes added
- [ ] TasksView UI complete
- [ ] All tests pass

### 9.14 Estimated Complexity
**Medium-High.** Scheduling + workflow engine + UI. Estimated 7-9 engineering days.

### 9.15 Recommended Commit Message
```
feat: automation with scheduled tasks, reminders, and workflows

- Add TaskManager with APScheduler for reminders and recurring tasks
- Add WorkflowManager with rule-based if/then automation
- Migrate ProactiveMonitor into TaskManager
- Extend tasks table with scheduling fields
- Add /api/tasks and /api/workflows endpoints
- Add TasksView with create/edit/delete and daily summary
```

---

## PHASE 10: DEVELOPER MODE
**Goal:** VS Code integration, Git integration, project analysis, code explanation, terminal assistant, documentation search.

### 10.1 Current State
- `SystemActions` can open apps and run allowlisted commands
- No project awareness
- No Git integration
- No code analysis
- No terminal assistant mode

### 10.2 Folder Structure
```
jarvis_backend/
  managers/
    project_manager.py     # NEW: project detection, analysis, tech stack
    git_manager.py         # NEW: Git operations, status, diff, commit
    code_manager.py        # NEW: code search, explanation, documentation
  modules/
    documents_module.py    # ENHANCE: code file parsing
jarvis_frontend/src/
  panel/views/
    ProjectsView.tsx       # NEW: project dashboard
    CodeView.tsx           # NEW: code search and explanation
```

### 10.3 New Modules
| Module | Responsibility |
|---|---|
| `ProjectManager` | Detect projects (Git repos, package.json, Cargo.toml, etc.), analyze tech stack, track recent files |
| `GitManager` | Git status, diff, log, commit, branch, PR creation (via GitHub CLI or API) |
| `CodeManager` | Code search (ripgrep), explanation (LLM), documentation lookup |

### 10.4 Existing Files To Modify
| File | Changes |
|---|---|
| `modules/documents_module.py` | Add code file parsing (AST extraction for Python, JS, TS) |
| `routes/tools.py` | Add project-aware file search |
| `MemoryManager` | Add `projects` table enhancements (already exists) |

### 10.5 Dependencies
```
# Backend additions
tree-sitter==0.21.0
ripgrep==0.1.0  # or call `rg` binary
```

### 10.6 API Changes
- `GET /api/projects` — list detected projects
- `GET /api/projects/{id}/analysis` — tech stack, recent activity
- `POST /api/projects/{id}/analyze` — deep analysis
- `GET /api/git/status` — Git status for project
- `POST /api/git/commit` — create commit (with confirmation)
- `POST /api/code/explain` — explain code snippet/file
- `GET /api/code/search` — search codebase

### 10.7 React Changes
- `ProjectsView.tsx`: Project cards with tech stack badges, recent activity, quick actions
- `CodeView.tsx`: Code search, explanation panel, documentation links

### 10.8 Electron Changes
- Add IPC for opening VS Code with specific file/line
- Add IPC for terminal execution in project directory

### 10.9 Backend Changes
1. Implement `ProjectManager`
2. Implement `GitManager`
3. Implement `CodeManager`
4. Add API routes
5. Integrate into skill/plugin system

### 10.10 Testing Strategy
- Backend: Project detection, Git operations, code search
- Frontend: ProjectsView and CodeView rendering

### 10.11 Risks
| Risk | Mitigation |
|---|---|
| Large codebase search performance | Use `rg` binary; cache results; limit scope |
| Git operation safety | All writes require confirmation; dry-run mode |
| Multi-language support | Start with Python + TypeScript; add others via tree-sitter |

### 10.12 Expected Result
- "Analyze my project" → JARVIS describes tech stack, recent changes, suggestions
- "Explain this function" → JARVIS explains selected code
- "Commit my changes" → JARVIS creates Git commit with generated message
- Project-aware file search and documentation lookup

### 10.13 Checklist
- [ ] `ProjectManager` implemented
- [ ] `GitManager` implemented
- [ ] `CodeManager` implemented
- [ ] API routes added
- [ ] ProjectsView and CodeView UI complete
- [ ] All tests pass

### 10.14 Estimated Complexity
**Medium-High.** Multi-language code analysis + Git integration. Estimated 8-10 engineering days.

### 10.15 Recommended Commit Message
```
feat: developer mode with project analysis, Git integration, and code explanation

- Add ProjectManager for project detection and tech stack analysis
- Add GitManager for status, diff, commit, and PR operations
- Add CodeManager for code search and LLM-powered explanation
- Add /api/projects, /api/git, /api/code endpoints
- Add ProjectsView and CodeView to panel
```

---

## PHASE 11: UI / UX POLISH
**Goal:** Animations, glassmorphism, transitions, loading states, notifications, voice visualization, accessibility, performance.

### 11.1 Current State
- Orb has basic animations (breathing, drift, state colors)
- Panel has basic CSS transitions
- No glassmorphism system
- Loading states are minimal
- Notifications use Electron Notification API
- Accessibility is partial (aria labels exist, but no reduced-motion system)

### 11.2 Folder Structure
```
jarvis_frontend/src/
  tokens.css             # EXISTING: enhance with motion tokens
  orb/
    OrbEngine.tsx        # ENHANCE: smoother animations
    OrbEngine.css        # ENHANCE: glassmorphism, shadows
  panel/
    Panel.tsx            # ENHANCE: transitions, loading states
    Panel.css            # ENHANCE: glassmorphism
  components/
    LoadingSpinner.tsx   # NEW
    NotificationToast.tsx # NEW
  hooks/
    useReducedMotion.ts  # NEW
    useAccessibility.ts  # NEW
```

### 11.3 New Modules
| Module | Responsibility |
|---|---|
| `tokens.css` | Design tokens: colors, spacing, radii, motion curves, glass presets |
| `LoadingSpinner.tsx` | Consistent loading indicator for all views |
| `NotificationToast.tsx` | Toast notifications for actions, errors, confirmations |
| `useReducedMotion.ts` | Hook for `prefers-reduced-motion` |
| `useAccessibility.ts` | Hook for screen reader announcements, focus management |

### 11.4 Existing Files To Modify
| File | Changes |
|---|---|
| `tokens.css` | Add motion tokens, glass presets, animation curves |
| `OrbEngine.css` | Glassmorphism core, smoother shadows, blur layers |
| `Panel.css` | Glass sheet, smooth transitions, loading states |
| `ChatView.tsx` | Streaming caret, loading dots, regenerate button |
| `App.tsx` | Toast container, error banner improvements |

### 11.5 Dependencies
- No new npm packages

### 11.6 API Changes
- None

### 11.7 React Changes
- `OrbEngine.tsx`: Smoother state transitions, particle trails, shockwave animation
- `Panel.tsx`: Cross-fade view transitions (120ms), loading skeletons
- `ChatView.tsx`: Streaming caret pulse, typing indicator dots, regenerate action
- Add `NotificationToast` system for all user-facing actions

### 11.8 Electron Changes
- None

### 11.9 Backend Changes
- None

### 11.10 Testing Strategy
- Frontend: Visual regression tests for key states
- Frontend: Accessibility audit (axe-core)
- Frontend: Performance profiling (FPS, memory)

### 11.11 Risks
| Risk | Mitigation |
|---|---|
| Animation performance on low-end GPUs | Reduce particle count; detect GPU capability; fallback to CSS animations |
| Glassmorphism on X11 | Test transparency; fallback to solid backgrounds |
| Accessibility regressions | Run axe-core in CI; manual screen reader testing |

### 11.12 Expected Result
- Orb animations are smooth at 60fps on modern hardware
- Panel transitions are polished (220ms ease-out)
- Loading states are consistent across all views
- Toasts replace all alert/confirm dialogs
- Full keyboard navigation and screen reader support
- `prefers-reduced-motion` respected everywhere

### 11.13 Checklist
- [ ] Design tokens documented and applied
- [ ] Orb animations polished (trails, shockwave, shadow breathing)
- [ ] Panel transitions smooth (cross-fade, expand/collapse)
- [ ] Loading states consistent
- [ ] Toast notification system complete
- [ ] Accessibility audit passed
- [ ] Performance profiling shows <1% CPU idle
- [ ] All tests pass

### 11.14 Estimated Complexity
**Medium.** Frontend polish work. Estimated 4-6 engineering days.

### 11.15 Recommended Commit Message
```
feat: UI/UX polish with glassmorphism, animations, and accessibility

- Add design tokens for motion, glass, spacing
- Enhance OrbEngine with trails, shockwave, shadow breathing
- Smooth panel transitions and loading states
- Add toast notification system
- Add reduced-motion and accessibility hooks
- Pass axe-core accessibility audit
```

---

## PHASE 12: OPTIMIZATION
**Goal:** Memory, CPU, GPU, rendering, backend, voice latency, startup time, Electron, bundle size.

### 12.1 Current State
- Orb uses 600 Three.js particles (was 1000, reduced in Phase 2)
- Backend spawns as child process
- Frontend bundle size unknown
- No lazy loading of panel views
- Voice latency ~8s p95

### 12.2 Folder Structure
```
jarvis_frontend/src/
  lazy/
    ChatView.tsx         # LAZY: already lazy-loaded in App.tsx
    MemoryView.tsx       # LAZY
    ...
  utils/
    bundleAnalyzer.ts    # NEW: analyze bundle size
jarvis_backend/
  managers/
    startup_manager.py   # NEW: optimized startup sequence
```

### 12.3 New Modules
| Module | Responsibility |
|---|---|
| `StartupManager` | Parallelized backend startup, lazy module loading, warmup sequence |

### 12.4 Existing Files To Modify
| File | Changes |
|---|---|
| `App.tsx` | Lazy-load all panel views (already partially done) |
| `VoiceOrb.tsx` | Reduce to 400 particles; add occlusion-based pause |
| `electron/main.js` | Parallelize backend health check; show splash earlier |
| `main.py` | Lazy-load heavy modules (Vosk, Vault) after health endpoint returns |

### 12.5 Dependencies
- No new dependencies
- Add build plugin: `rollup-plugin-visualizer` for bundle analysis

### 12.6 API Changes
- None

### 12.7 React Changes
- Lazy-load all panel views with Suspense boundaries
- Reduce orb particle count to 400
- Add `requestIdleCallback` for non-critical UI updates
- Code-split Three.js import (dynamic import)

### 12.8 Electron Changes
- Show bubble immediately, load main window lazily
- Parallelize backend spawn + health check
- Use `app.commandLine.appendSwitch('disable-gpu-vsync')` for smoother animations

### 12.9 Backend Changes
1. Implement `StartupManager`
2. Lazy-load Vosk model after `/health` returns 200
3. Lazy-init VaultManager on first vault request
4. Use `asyncio.to_thread` for CPU-bound work

### 12.10 Testing Strategy
- Measure: Orb idle CPU, panel FPS, voice round-trip latency, bundle size, startup time
- Profile with `py-spy`, Chrome DevTools, Electron DevTools

### 12.11 Risks
| Risk | Mitigation |
|---|---|
| Lazy loading breaks assumptions | Ensure all lazy modules have proper error boundaries |
| GPU differences | Test on integrated + discrete GPUs; fallback to 2D canvas if WebGL fails |

### 12.12 Expected Result
- Orb idle CPU < 1%
- Bundle size < 500KB gzipped
- Voice round-trip ≤ 10s p95
- Startup to orb visible < 2s
- Startup to fully functional < 5s

### 12.13 Checklist
- [ ] All panel views lazy-loaded
- [ ] Orb particles reduced to 400
- [ ] Backend lazy-init implemented
- [ ] Bundle size analyzed and optimized
- [ ] Startup time measured and improved
- [ ] Voice latency profiled and optimized
- [ ] All tests pass

### 12.14 Estimated Complexity
**Medium.** Profiling + incremental optimization. Estimated 3-5 engineering days.

### 12.15 Recommended Commit Message
```
feat: performance optimization across frontend, backend, and Electron

- Lazy-load all panel views with Suspense
- Reduce orb particles to 400 with occlusion-based pause
- Lazy-init Vosk model and VaultManager in backend
- Add StartupManager for parallelized startup
- Analyze and optimize bundle size
- Measure and improve voice latency, startup time, CPU usage
```

---

## PHASE 13: PRODUCTION HARDENING
**Goal:** Crash recovery, logging, diagnostics, recovery mode, health monitor, configuration validation, automatic backups, safe mode.

### 13.1 Current State
- Backend has rotating file handler (5MB x 3)
- Backend has `/health` endpoint
- Electron has auto-updater
- No crash recovery
- No safe mode
- No configuration validation
- No automatic backups

### 13.2 Folder Structure
```
jarvis_backend/
  managers/
    health_manager.py     # NEW: comprehensive health checks
    backup_manager.py     # NEW: automatic DB + vault backups
    recovery_manager.py   # NEW: crash recovery, safe mode
jarvis_frontend/src/
  components/
    DiagnosticsView.tsx   # NEW: system diagnostics, logs, crash reports
  utils/
    errorReporter.ts      # NEW: frontend error reporting
electron/
  crashHandler.js         # NEW: process crash detection
```

### 13.3 New Modules
| Module | Responsibility |
|---|---|
| `HealthManager` | Deep health checks (DB, vault, models, providers, disk, memory) |
| `BackupManager` | Automatic backups of DB + vault, retention policy, restore |
| `RecoveryManager` | Crash recovery, safe mode, configuration reset, migration |
| `errorReporter.ts` | Frontend error boundary with reporting |
| `crashHandler.js` | Electron crash detection, restart, recovery |

### 13.4 Existing Files To Modify
| File | Changes |
|---|---|
| `main.py` | Add crash handler, recovery mode, configuration validation on startup |
| `electron/main.js` | Add crash handler, safe mode detection, recovery UI |
| `App.tsx` | Add `ErrorBoundary` with recovery options |
| `routes/state.py` | Add `/health/deep` endpoint |

### 13.5 Dependencies
```
# Backend additions
psutil==5.9.6  # already present
```

### 13.6 API Changes
- `GET /health/deep` — comprehensive health check
- `GET /api/system/diagnostics` — logs, config, versions
- `POST /api/system/backup` — trigger backup
- `POST /api/system/restore` — restore from backup
- `POST /api/system/safe-mode` — enter safe mode
- `GET /api/system/crash-reports` — list crash reports

### 13.7 React Changes
- `DiagnosticsView.tsx`: System info, log viewer, crash reports, backup/restore
- `App.tsx`: Enhanced `ErrorBoundary` with "Safe Mode" and "Report Issue" buttons

### 13.8 Electron Changes
1. Add `crashHandler.js` for process crash detection
2. Detect startup failures; offer safe mode
3. Auto-backup DB + vault on shutdown
4. Recovery UI for corrupted state

### 13.9 Backend Changes
1. Implement `HealthManager`
2. Implement `BackupManager`
3. Implement `RecoveryManager`
4. Add crash reporting
5. Add configuration validation on startup
6. Add safe mode with minimal features

### 13.10 Testing Strategy
- Backend: Simulate crashes, verify recovery
- Backend: Backup/restore cycle
- Backend: Configuration validation
- Frontend: Error boundary recovery flow
- Electron: Crash handler + restart

### 13.11 Risks
| Risk | Mitigation |
|---|---|
| Crash loops | Safe mode with disabled features; user can reset config |
| Backup corruption | Atomic writes; verify checksums; keep 7-day retention |
| Disk full from backups | Size limit + retention policy; warn user |

### 13.12 Expected Result
- Automatic backups of DB + vault daily
- Crash recovery: app restarts into safe mode with diagnostics
- Configuration validation catches misconfigurations early
- Diagnostics view shows logs, health, crash history
- "Reset to defaults" available from safe mode

### 13.13 Checklist
- [ ] `HealthManager` implemented with deep checks
- [ ] `BackupManager` implemented with scheduled backups
- [ ] `RecoveryManager` implemented
- [ ] Crash handler in Electron
- [ ] Configuration validation on startup
- [ ] Safe mode with minimal feature set
- [ ] DiagnosticsView UI complete
- [ ] All tests pass

### 13.14 Estimated Complexity
**Medium.** Reliability infrastructure. Estimated 5-7 engineering days.

### 13.15 Recommended Commit Message
```
feat: production hardening with crash recovery, backups, and safe mode

- Add HealthManager with deep system health checks
- Add BackupManager for automatic DB + vault backups
- Add RecoveryManager for crash recovery and safe mode
- Add configuration validation on startup
- Add Electron crash handler and recovery UI
- Add DiagnosticsView for logs, health, and crash reports
```

---

## MASTER COMMIT SEQUENCE

```
Phase 1:  feat: foundation — Faster Whisper, Kokoro TTS, Ollama, managers
Phase 2:  feat: orb system — living animations, autonomous behaviors, panel choreography
Phase 3:  feat: memory — vault enhancements, conversation summaries, preferences
Phase 4:  feat: system control — confirmation gating, undo, audit trail
Phase 5:  feat: intelligence — context awareness, preference learning, smart suggestions
Phase 6:  feat: model manager — Ollama integration, provider abstraction
Phase 7:  feat: plugin architecture — dynamic loading, permissions, hot-reload
Phase 8:  feat: vision — screenshot understanding, OCR, window awareness
Phase 9:  feat: automation — scheduled tasks, reminders, workflows
Phase 10: feat: developer mode — project analysis, Git, code explanation
Phase 11: feat: UI/UX polish — glassmorphism, animations, accessibility
Phase 12: feat: optimization — performance, bundle size, startup time
Phase 13: feat: production hardening — crash recovery, backups, safe mode
```

---

## ARCHITECTURE PRINCIPLES (NON-NEGOTIABLE)

1. **Managers own state.** No module-level mutable singletons outside `routes/state.py`.
2. **Providers are swappable.** STT, TTS, LLM, Vision, Memory all have abstract base classes.
3. **Frontend never touches backend internals.** All communication via WebSocket + REST.
4. **Electron IPC is typed.** Preload bridge exposes only whitelisted channels.
5. **Tests gate commits.** Every phase must pass all existing tests + new tests.
6. **No dead code.** Deprecated modules are removed within one phase of deprecation.
7. **Security first.** All system actions require confirmation; audit log is immutable.
8. **Privacy by default.** Local-only storage; cloud features opt-in.

---

*End of Implementation Roadmap.*
