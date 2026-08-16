/**
 * Voice pipeline diagnostics helpers.
 *
 * Every stage of the voice pipeline should route its outcome through
 * `logVoice` and user-facing failures through `describeMicError` /
 * `describeNetworkError` so the app surfaces specific, actionable messages
 * instead of opaque browser errors like "Failed to fetch" or "Couldn't
 * listen".
 */

export type VoiceStage =
  | 'idle'
  | 'ws_connecting'
  | 'ws_ready'
  | 'mic_probing'
  | 'mic_open'
  | 'capturing'
  | 'flushing'
  | 'transcribing'
  | 'processing'
  | 'speaking'
  | 'complete'
  | 'error'
  | 'mic'
  | 'ws'
  | 'fetch'
  | 'health'
  | 'tts'
  | 'audio_context'
  | 'llm';

export type VoiceLogMeta = Record<string, unknown>;

/**
 * Structured pipeline log: prints a JSON line to the console and forwards it
 * to the Electron main process (which writes it to the app log) when the
 * preload bridge exposes `logVoice`.
 */
export function logVoice(stage: VoiceStage | string, meta: VoiceLogMeta = {}): void {
  const payload = { t: new Date().toISOString(), stage, ...meta };
  const line = `[voice] ${JSON.stringify(payload)}`;
  if (meta.level === 'error' || stage === 'error') {
    console.error(line);
  } else {
    console.info(line);
  }
  try {
    const api = (window as any).electronAPI;
    if (api && typeof api.logVoice === 'function') {
      api.logVoice(payload).catch(() => {});
    }
  } catch {
    // Diagnostics must never break the pipeline.
  }
}

/**
 * Map a `getUserMedia` rejection to a specific, actionable message.
 * Chromium rejects with well-known error names; the app previously collapsed
 * all of them into a single generic "Couldn't listen" style message.
 */
export function describeMicError(err: unknown): string {
  const name = (err as any)?.name || '';
  const message = (err as Error)?.message || String(err);
  const full = `${name}: ${message}`;
  switch (name) {
    case 'NotAllowedError':
      return 'Microphone permission was denied. Click the mic icon in the address bar (or Settings → Privacy → Microphone) and allow JARVIS to use the microphone, then try again.';
    case 'NotFoundError':
      return 'No microphone was found. Connect a microphone and confirm it is not disabled in your system sound settings.';
    case 'NotReadableError':
      return 'The microphone is in use by another application or cannot be accessed. Close other apps using the mic and try again.';
    case 'OverconstrainedError':
      return 'No microphone matches the requested audio settings (echo cancellation / noise suppression). Try disabling those in system sound settings.';
    case 'SecurityError':
    case 'TypeError':
      return 'Microphone access was blocked by the browser security policy. Make sure the app is running from localhost over http(s).';
    case 'AbortError':
      return 'Microphone capture was aborted by the browser. Try again.';
    case 'TimeoutError':
      return 'Timed out while opening the microphone. The device may be busy, unplugged, or not supported.';
    case 'NotSupportedError':
      return 'Audio capture is not supported in this environment. Check your sound driver / PipeWire configuration.';
    default:
      if (/timed out/i.test(message)) {
        return 'Timed out while opening the microphone. The device may be busy, unplugged, or not supported.';
      }
      return `Microphone could not be started (${full}). Check that a microphone is connected and JARVIS has permission to use it.`;
  }
}

/**
 * Map a network/fetch rejection to a specific, actionable message.
 * Browsers collapse most network failures into `TypeError: Failed to fetch`.
 */
export function describeNetworkError(err: unknown, url?: string): string {
  const name = (err as any)?.name || '';
  const message = (err as Error)?.message || String(err);
  const where = url ? ` at ${url}` : '';
  if (name === 'AbortError' || /timed out/i.test(message)) {
    return `Request${where} timed out. The server may be slow or unreachable.`;
  }
  if (name === 'TypeError' || /failed to fetch/i.test(message) || /load failed/i.test(message)) {
    return `Could not reach the JARVIS server${where}. Make sure the backend is running and the address in Settings is correct.`;
  }
  if (name === 'SecurityError') {
    return `The request${where} was blocked by a security policy. Check the server address (http/https) in Settings.`;
  }
  return `Network error${where}: ${message}`;
}

/** Wrap a promise with a timeout; rejects with `message` on expiry. */
export async function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

/** Normalize a user-provided server address into a base URL (http scheme). */
export function toBaseUrl(server: string): string {
  if (typeof window !== 'undefined' && (window as any).electronAPI) {
    return window.location.origin;
  }
  const trimmed = (server || '').trim().replace(/\/*$/, '');
  if (!trimmed) return 'http://127.0.0.1:8000';
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `http://${trimmed}`;
}

/**
 * Classify a pipeline failure into a structured error with a stable `stage`,
 * `code`, and an actionable `message`. Replaces the opaque browser errors
 * ("Failed to fetch", "NotReadableError", ...) the user was previously seeing.
 */
export class VoiceError extends Error {
  stage: VoiceStage;
  code: string;

  constructor(stage: VoiceStage, code: string, message: string) {
    super(message);
    this.name = 'VoiceError';
    this.stage = stage;
    this.code = code;
  }
}

export function classifyError(stage: VoiceStage, err: unknown): VoiceError {
  const name = (err as any)?.name || 'unknown';
  if (stage === 'mic') {
    return new VoiceError(stage, name, describeMicError(err));
  }
  if (stage === 'ws' || stage === 'fetch' || stage === 'health') {
    return new VoiceError(stage, 'network_error', describeNetworkError(err));
  }
  const message = (err as Error)?.message || String(err);
  return new VoiceError(stage, name, message);
}

/**
 * Retry `fn` with exponential backoff (`baseMs`, doubling up to `maxMs`) and a
 * structured log line for every failed attempt. Rejects with the last error
 * after all attempts are exhausted.
 */
export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  retries: number,
  baseMs: number,
  maxMs: number,
  label: string,
): Promise<T> {
  let delay = baseMs;
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      if (attempt >= retries) break;
      logVoice('retry', {
        level: 'warn',
        label,
        attempt: attempt + 1,
        retries,
        error: String(err),
        delayMs: delay,
      });
      await new Promise<void>((resolve) => setTimeout(resolve, delay));
      delay = Math.min(delay * 2, maxMs);
    }
  }
  throw lastErr;
}

/**
 * Probe the backend `/health` endpoint. Returns a structured result that
 * callers can log and surface as a specific message (instead of a generic
 * `TypeError: Failed to fetch`).
 */
export async function checkBackendHealth(
  server: string,
  timeoutMs = 5000,
): Promise<{
  ok: boolean;
  url: string;
  status?: number;
  body?: Record<string, unknown>;
  error?: string;
}> {
  const url = `${toBaseUrl(server)}/health`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res: Response;
    try {
      res = await fetch(url, { signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      return {
        ok: false,
        url,
        status: res.status,
        error: `Backend responded with HTTP ${res.status} (${res.statusText}).`,
      };
    }
    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return { ok: body.status === 'healthy', url, status: res.status, body };
  } catch (err) {
    return { ok: false, url, error: describeNetworkError(err, url) };
  }
}

/**
 * Fetch the structured pipeline health (STT, TTS, LLM, WS count). Never
 * throws; returns `null` on failure so callers can log and degrade.
 */
export async function checkVoiceDiagnostics(
  server: string,
  timeoutMs = 5000,
): Promise<Record<string, unknown> | null> {
  const url = `${toBaseUrl(server)}/api/voice/diagnostics`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    let res: Response;
    try {
      res = await fetch(url, { signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) return null;
    return (await res.json()) as Record<string, unknown>;
  } catch {
    return null;
  }
}
