# JARVIS Security & Authorization Audit - Findings Report

Scope: the typed-orchestrator / capability-authorization / hardened-tools changes
(capability.py, path_policy.py, session_context.py, orchestrator.py, routes/state.py,
main.py, tools/*). Pre-existing code was inspected and reported out-of-diff.
Method: source review, empirical exploits, negative bypass tests, full test suites.
Date: 2026-08-15

## 1. Verdict per required property

| # | Property | Status | Evidence |
|---|----------|--------|----------|
| 1 | One centralized authz path for privileged tools | PARTIAL | Orchestrator run() enforces CapabilityPolicy (orchestrator.py:110-122); direct ToolRegistry.execute_tool and legacy paths rely on per-tool confirm gates (defense-in-depth, not centralized). See F9 |
| 2 | Confirmations bound to exact normalized action/target | PASS | capability.py canonicalizes args (drops confirm), binds approval to session+tool+args hash. Tests: test_capability.py, test_approval_cannot_be_replayed_after_tamper |
| 3 | Single-use + safe expiry | PASS | consume_approval removes; TTL 120s, MAX_PENDING_APPROVALS=20. Tests: test_capability.py |
| 4 | No replay for different command/path/args | PASS | args-hash binding; tampering is refused and the approval is consumed anyway. test_approval_cannot_be_replayed_after_tamper |
| 5 | Tool output / retrieved content = untrusted data | PASS | JARVIS_SYSTEM_PROMPT injection guard; tool logs truncated ([:500]); redact_content on reads. test_read_document_redacts_secrets_within_root |
| 6 | Canonicalized paths, no traversal/symlink escape | PASS | path_policy resolve() + os.path.commonpath; ReadDocumentTool confined; SPA fallback fixed. test_security_bypass.py |
| 7 | Shell cannot become arbitrary execution via NL | PASS | execute_shell allowlist + metachar + sensitive-arg checks; OpenTerminalTool no longer executes commands. test_security_bypass.py |
| 8 | Size/time limits on subprocess/search/upload/WS/audio/model | PARTIAL | WS audio capped (main.py:350-351,495,536); shell output 64KB/timeout 30s; out-of-diff gaps: SystemActions.execute_command, /terminal/execute, ocr_image unbounded. See F13 |
| 9 | Secrets/keys/tokens/screenshots/raw transcripts not logged/in memory | PASS (transcripts fixed) | Raw voice transcripts no longer logged (main.py:522,562,695 - char count only). llm_provider never logs keys. See F5 |
| 10 | localhost binding default | PASS | uvicorn.run(host=host) - host from JARVIS_HOST default 127.0.0.1 (main.py:852-854); CORS allowlist = localhost origins |

## 2. Findings (severity / file / line / exploit / fix / test evidence)

### Fixed in this audit

**F1 - HIGH - ReadDocumentTool arbitrary file read, no path policy**
- File/line: tools/document_tools.py:16-52 (was a bare open(path)).
- Exploit: read_document with path=/etc/shadow or path=~/.ssh/id_rsa returned file
  contents; risk_level="read_only" meant no approval was ever requested. Symlinks and
  ../ were unresolvable escapes.
- Fix: resolve via resolve_within_roots (rejects outside approved roots + symlink
  escapes), refuse is_sensitive_path, redact_content before return, cap
  MAX_READ_CHARS=64KB regardless of requested max_chars.
- Tests: test_read_document_refuses_etc_shadow, _refuses_sensitive_path,
  _refuses_ssh_key_within_root, _blocks_traversal_outside_roots, _symlink_escape_blocked,
  _redacts_secrets_within_root, _max_chars_is_capped.

**F2 - HIGH - OpenTerminalTool = arbitrary shell execution**
- File/line: tools/app_tools.py:44-52 (was subprocess.Popen([chosen, "-e", "bash", "-lc", command])).
- Exploit: open_terminal with command="rm -rf ~" runs it with NO approval -
  risk_level="reversible", not in ALWAYS_CONFIRM, fully bypassing the execute_shell
  allowlist.
- Fix: command execution removed; tool only opens an interactive terminal; a command
  argument is ignored (logged). _which still uses bash -lc "command -v <fixed-literal>"
  against a hard-coded name (no injection).
- Tests: test_open_terminal_does_not_execute_command.

**F3 - MEDIUM - orchestrator reported unexecuted overwrite as verified success**
- File/line: modules/orchestrator.py:126-141 (new); respond_to_confirmed:181-182.
- Exploit: move_file/copy_file overwrite gate returns success=True +
  requires_confirmation=True without moving anything; orchestrator recorded it as a
  verified tool result -> false "Done." to the user, and the overwrite-confirm flow was
  dead in the orchestrator path.
- Fix: requires_confirmation results are surfaced as a real single-use confirm Decision;
  respond_to_confirmed re-checks and refuses if still unconfirmed; unexecuted actions are
  never recorded as success.
- Tests: test_overwrite_gate_is_surfaced_as_confirm, _consumes_and_executes,
  test_direct_tool_execution_does_not_bypass_overwrite_gate.

**F4 - MEDIUM - shell cat/echo exfiltration of secrets**
- File/line: tools/shell_tools.py:18,24-37,78.
- Exploit: allowlist checked only argv[0]; cat /etc/shadow, cat ~/.ssh/id_rsa,
  cat <root>/.env returned secret contents (paths under $HOME are inside the approved
  roots).
- Fix: _reject_sensitive_args refuses any path-reading argument outside the approved
  roots or on the sensitive-path denylist.
- Tests: test_shell_cat_secret_exfiltration_blocked, test_shell_cat_outside_roots_blocked.

**F5 - MEDIUM - raw voice transcripts written to rotating log**
- File/line: main.py:522,562,695.
- Exploit: anything the user says (passwords, medical info, secrets) persisted to
  jarvis.log (5MB x 3 backups).
- Fix: log character count only ("User (voice) %d chars").
- Tests: code review; grep of log format.

**F6 - MEDIUM - unbounded WebSocket audio (memory DoS)**
- File/line: main.py:350-351,495,536; modules/stt.py:219,233 (_pcm_all bytearray).
- Exploit: a client can stream audio_chunk indefinitely (each message resets the 90s idle
  timer) growing _pcm_all unboundedly. Browser /ws/voice path had NO VAD 20s cap (only the
  native path had one).
- Fix: MAX_AUDIO_CHUNK_BYTES=8MB per chunk, MAX_UTTERANCE_BYTES=16MB per utterance, plus a
  base64-length cap on the legacy audio blob (main.py:536).
- Tests: constants asserted by import; end-to-end WS test impractical in unit suite (documented).

**F7 - MEDIUM - create_file silently overwrote existing files**
- File/line: tools/file_tools.py:348-377.
- Exploit: create_file over an existing file clobbered it with no confirmation.
- Fix: overwrite requires a requires_confirmation gate (consistent with move/copy).
- Tests: test_create_file_no_overwrite_without_confirm, test_create_file_write_after_confirm.

**F8 - MEDIUM - SPA fallback path traversal served .env (empirically verified)**
- File/line: main.py:830-842.
- Exploit (verified before fix): GET /..%2f..%2fjarvis_backend%2f.env returned
  MISTRAL_API_KEY=... over HTTP. No session token required on the SPA route.
- Fix: abspath + prefix check confines serving to the dist tree; any escape returns
  index.html. Verified after fix via TestClient (returns index.html, not .env).
- Tests: manual TestClient reproduction; logic mirrors vault traversal tests.

### Pre-existing / out-of-diff (reported, not modified)

**F9 - MEDIUM - CapabilityPolicy not enforced inside ToolRegistry.execute_tool**
- File/line: tools/__init__.py:143-159.
- Exploit: legacy paths (process_command keyword fallback routes/state.py:517,
  _route_tools routes/state.py:747, WS legacy confirm setting confirm=True, HTTP
  /api/tools) never touch CapabilityPolicy - two parallel auth systems.
- Mitigation: file/shell tools carry their own confirm gates (defense-in-depth);
  orchestrator + handle_ws_confirm route through policy. Recommend enforcing policy in
  execute_tool for a single chokepoint.

**F10 - MEDIUM - handle_ws_confirm does not verify approval_id**
- File/line: routes/state.py:1010-1045.
- Exploit: confirmation is bound by tool name + current session_ctx.pending_args only. If
  a new request overwrote pending_args with identical tool+args, a stale dialog could
  authorize the newer (identical) action. Arg-hash binding + single-use + 120s TTL
  mitigate; recommendation: pass approval_id through the WS message and require it.

**F11 - MEDIUM - /terminal/execute uses create_subprocess_shell, client-side confirm**
- File/line: routes/tools.py (pre-existing).
- Exploit: arbitrary shell string executed when client sends confirm=true (a client-side
  boolean, not server policy).

**F12 - MEDIUM - _safe_path uses startswith prefix matching**
- File/line: routes/tools.py (pre-existing). Prefix-match bug: root /home/user also
  matches /home/user2. path_policy's commonpath approach is the correct pattern.

**F13 - MEDIUM - unbounded output on SystemActions.execute_command and ocr_image**
- File/line: modules/system_actions.py; routes/tools.py ocr_image (pre-existing).
- Exploit: execute_command buffers all output (no 64KB cap like ExecuteShellTool);
  ocr_image decodes arbitrarily large images. shell_tools.cap (64KB / 30s) is the fix
  pattern.

**F14 - LOW - auth disabled by default**
- File/line: modules/auth.py; main.py.
- JARVIS_AUTH_ENABLED defaults to false. Loopback-only binding and localhost CORS
  mitigate; enable before any network exposure.

**F15 - INFO - residual hardening**
- open_terminal logs the ignored command argument (benign, keeps a trace if the LLM tries).
- Browser /ws/voice has no VAD endcap (unlike native path); the byte caps bound memory but
  a 20s utterance cap would match native behavior.

## 3. Test evidence

- New negative bypass suite: tests/test_security_bypass.py - 20 tests, all pass.
- New approval/session/orchestrator suites: test_capability.py, test_path_policy.py,
  test_session_context.py, test_orchestrator.py (33 tests, incl. failure-path + tamper).
- Backend full suite: 300 passed (was 247 baseline) exit 0.
- Frontend: npx tsc --noEmit clean; 63 vitest passed.
- Empirical traversal: F8 confirmed pre-fix, confirmed blocked post-fix via TestClient.
- Known env limitation: ruff/black are not installed in this environment (AGENTS.md lists
  them but they are unavailable); one native-audio segfault observed once in a full run,
  clean on rerun (torch/webrtcvad flake).

## 4. Phase-2 hardening (full-surface audit)

Additional audit pass across routes/tools.py, managers/system_manager.py, Electron
main/preload, and the frontend HTTP layer. New properties verified: Electron sandboxing/
navigation (#12), honest tool failures (#13), cancellation/disconnect cleanup (#14).

### Fixed in phase 2

**F16 - MEDIUM - HTTP path checks used prefix matching (`startswith`)**
- File/line: routes/tools.py `_safe_path`; managers/system_manager.py delete_file,
  rename_file, create_folder.
- Exploit: base `/home/user` also matched `/home/user2`, allowing escapes past the
  approved base when a sibling dir shared the prefix.
- Fix: `_within()` uses `os.path.commonpath` (same pattern as path_policy).
- Tests: test_system_delete_prefix_confusion_blocked, test_system_delete_outside_base_blocked.

**F17 - HIGH - close_application could SIGKILL self or pid 1**
- File/line: managers/system_manager.py close_application.
- Exploit: a spoofed pid (0, 1, or the backend's own pid) was passed to `os.kill(pid, 9)`.
- Fix: refuse `pid <= 1` and `pid == os.getpid()` ("Refusing to kill a protected process").
- Tests: test_system_kill_refuses_self_and_pid_one.

**F18 - MEDIUM - Electron window could navigate away and leak preload surface**
- File/line: electron/main.js (will-navigate, setWindowOpenHandler, will-attach-webview).
- Exploit: preload exposes `getSessionToken`/`retrieveApiKey`; a navigation to an
  untrusted origin would hand a page the session token and keychain-read API.
- Fix: navigation/`window.open`/webview-attach are restricted to the backend origin
  `http://127.0.0.1:PORT`. Syntax-checked (`node -c`); runtime behavior BLOCKED in this
  environment (no display). Global `--no-sandbox` remains (F-R5).

**F19 - MEDIUM - /terminal/execute: arbitrary shell + unbounded runtime/output**
- File/line: routes/tools.py terminal_execute.
- Exploit: any shell string executed on `confirm=true`; a silent/hanging command ran
  forever and buffered unbounded output.
- Fix: server-side allowlist (`TERMINAL_ALLOWLIST`, extendable via
  `TERMINAL_ALLOWLIST_EXTRA`), metacharacter rejection (no pipes/redirection/subshells/
  `$()`), no leading-option commands, wall-clock TTL (default 60s,
  `TERMINAL_EXEC_TIMEOUT`) that killpg's the process group, and a 1MB output cap.
- Tests: test_terminal_allowlist_* (5), test_terminal_route_*, test_terminal_execution_ttl_kills_runaway.

**F20 - MEDIUM - unbounded /ocr image and /files/create payloads**
- File/line: routes/tools.py ocr_image, create_file; modules/limits.py.
- Exploit: arbitrarily large base64 images (decompression bombs) and multi-GB file writes.
- Fix: `MAX_OCR_B64_CHARS` (~8MB decoded) + PIL `MAX_IMAGE_PIXELS`, `MAX_CREATE_FILE_BYTES`
  1MB, both centralized in modules/limits.py.
- Tests: test_ocr_oversized_image_rejected, test_create_file_oversized_content_rejected.

**F21 - MEDIUM - frontend never authenticated HTTP API calls**
- File/line: jarvis_frontend/src/api/* (12 modules); jarvis_frontend/src/api/baseUrl.ts.
- Exploit: in packaged mode the backend enforces `X-Jarvis-Token`, but the frontend never
  sent it, so every HTTP API call would 401 (and dev mode's check is a no-op).
- Fix: consolidated the duplicated fetch helpers into `baseUrl.request()` which attaches
  `X-Jarvis-Token` from Electron IPC (`getSessionToken`) when present; dev/browser mode
  (no electronAPI) sends no header and is unchanged.
- Tests: `tsc --noEmit` clean; 63 vitest passed.

### Reported in phase 2 (not changed)

**F-R1 - HIGH - client-trusted `confirm` booleans on the HTTP tool surface**
routes/tools.py system/command, apps/open, apps/close, files/delete, files/rename,
files/folder, clipboard/write, terminal/execute accept a client-sent `confirm` flag with no
server-side approval record. All frontend calls default to `confirm=true`. Fix requires a
server-issued approval + UI round-trip (like handle_ws_confirm). Loopback + token mitigate.
**FIXED - see F22.**

**F-R2 - MEDIUM - Electron global `--no-sandbox`**
electron/main.js:31 and the autostart entry disable the Chromium sandbox for every window.
Runtime verification impossible here (no display); change deferred.
**BLOCKED - see F-R7.**

**F-R3 - LOW - unauthenticated `GET /api/session-token`**
main.py:312. Loopback-only + CORS-restricted; left as-is so the dev-mode Electron WS
handshake keeps working.
**FIXED - see F23.**

**F-R4 - LOW - dev-mode session-token check is a no-op**
routes/state.py require_session_token returns early when `SESSION_TOKEN_PATH` is unset, so
all dev-mode HTTP/WS traffic is unauthenticated by design (loopback + single user).

**F-R5 - LOW - WS disconnect does not cancel in-flight tool calls**
Bounded by per-tool timeouts; full cancellation would require task handles per connection.

**F-R6 - LOW - audit log records full terminal commands**
By design (local single-user); enables replay/forensics.

### Phase-2 test evidence
- test_security_bypass.py: 39 tests (was 20) all pass, incl. terminal allowlist/TTL,
  payload caps, prefix-confusion, self-kill guard, honest-failure framing.
- Backend full suite: 310 passed.
- Frontend: `tsc --noEmit` clean, 63 vitest passed; eslint 0 errors (111 pre-existing
  `any` warnings); prettier flags 14 pre-existing files (none touched by this phase).
- `git diff --check`: clean.

## 5. Phase-3 hardening (remaining reported findings)

Closes the three remaining reported findings from phase 2 (F-R1, F-R3, F-R2).

### Fixed in phase 3

**F22 - HIGH (F-R1) - client-trusted `confirm` booleans replaced with server approvals**
- File/line: routes/tools.py `_http_session_id`, `_consume_or_issue_approval`; reused
  `capability_policy` from routes/state.py (TTL 120s, args-hash binding, single-use,
  SOURCE_USER).
- Exploit: a client could send `confirm=true` and skip every server-side gate; the flag
  was trusted wholesale.
- Fix: two-phase flow. First POST (no `approval_id`) returns
  `{"approval_required": true, "approval_id", "tool", "expires_in"}` and does NOT execute.
  A second POST carrying the exact same normalized args + `approval_id` consumes the
  pending approval (exact match on session + tool + args hash); any mismatch — altered
  args, replay, expiry, wrong session, wrong tool — is refused with 401. The `confirm`
  boolean is dropped from canonicalization and ignored. Applied to system/command,
  apps/open, apps/close, files/delete, files/rename, files/folder, clipboard/write,
  screenshot, terminal/execute (allowlist still enforced before the gate), audit/clear.
- Frontend: `baseUrl.request()` auto-retries once when the response carries
  `approval_required` + `approval_id`, re-posting the same body with the approval id.
- Tests: test_security_bypass.py — test_http_confirm_boolean_does_not_execute,
  test_http_approval_matching_consumed_and_executes, test_http_approval_altered_args_rejected,
  test_http_approval_replay_rejected, test_http_approval_expired_rejected,
  test_http_approval_wrong_session_rejected, test_http_approval_wrong_tool_rejected,
  test_terminal_allowlist_still_enforced_after_approval.

**F23 - LOW (F-R3) - `/api/session-token` now fails closed outside the local dev context**
- File/line: routes/state.py `session_token_available`, `get_dev_session_token`
  (DEV_WEB_ORIGINS); main.py endpoint returns 403 unless allowed.
- Fix: the endpoint only issues a token when: no `SESSION_TOKEN_PATH` is configured
  (dev mode) AND the server is bound to a loopback host AND the client Host header is
  loopback AND the Origin (when present) is a known local dev origin
  (http://localhost:5173/8000, http://127.0.0.1:5173/8000). In packaged mode
  (`SESSION_TOKEN_PATH` set) the endpoint returns 403 and every API call must present the
  exact `X-Jarvis-Token`.
- Tests: test_session_token_flow.py (10) — dev loopback token OK; non-loopback client
  Host / unknown Origin / non-loopback SERVER_HOST denied; known dev Origin allowed;
  packaged mode: endpoint denied, missing/invalid token -> 401, valid token -> 200.

**F24 - incidental - rate-limit 429 raised as HTTPException inside BaseHTTPMiddleware**
- File/line: main.py RateLimitMiddleware.dispatch (pre-existing).
- Exploit observed: once the 60-request/60s window was exhausted, raising HTTPException
  inside the nested BaseHTTPMiddleware stack surfaced as `anyio.EndOfStream` (Starlette
  bug) instead of a clean 429.
- Fix: return `JSONResponse(status_code=429, ...)` instead of raising. Behavior preserved.
- Tests: full-suite green (was intermittently failing once request volume crossed 60).

### Blocked in phase 3 (preserved, not changed)

**F-R7 - MEDIUM (F-R2) - Electron global `--no-sandbox` — BLOCKED**
- File/line: electron/main.js:31, npm `electron` script, autostart entry.
- Attempted fix: re-verified with a real runtime test on this machine (DISPLAY=:0).
- Result (empirically FAILED): with sandbox enabled the app exits 133.
  1. With the SUID helper present (chrome-sandbox, not setuid):
     `FATAL:setuid_sandbox_host.cc(158)] The SUID sandbox helper binary was found, but is
     not configured correctly. ... chrome-sandbox is owned by root and has mode 4755`.
  2. With the helper renamed aside (userns fallback, unprivileged_userns_clone=1):
     `FATAL:zygote_host_impl_linux.cc(126)] No usable sandbox! ... try using --no-sandbox`
     — consistent with the Ubuntu AppArmor user-namespace restriction.
- Decision per directive: `--no-sandbox` is preserved and the finding remains open.
  Re-test on any Linux host with `npm run sandbox:check` (scripts/sandbox-smoke.js, added
  this phase) once the platform allows an unprivileged user namespace or a properly setuid
  chrome-sandbox (root-owned, mode 4755).

### Phase-3 test evidence
- test_security_bypass.py + test_session_token_flow.py: 56 tests, all pass (incl. 8 new
  HTTP-approval negatives + 10 session-token flow tests).
- Backend full suite: 336 passed, exit 0 (was 310; +26 from F22/F23/F24 coverage).
- Frontend: `tsc --noEmit` clean; 63 vitest passed; eslint 0 errors on changed file
  baseUrl.ts (pre-existing warnings only); prettier clean on baseUrl.ts (App.tsx/Panel.tsx
  warnings pre-existing).
- `py_compile` clean on all changed modules; `node -c` clean on electron/main.js and
  preload.js; `git diff --check` clean.
- Known env limitation: ruff/black are not installed in this environment (AGENTS.md lists
  them but they are unavailable); backend lint not run.