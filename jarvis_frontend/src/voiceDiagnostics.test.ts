import { describe, it, expect, vi } from 'vitest';
import {
  describeMicError,
  describeNetworkError,
  toBaseUrl,
  withTimeout,
  classifyError,
  VoiceError,
  retryWithBackoff,
} from './voiceDiagnostics';

describe('describeMicError', () => {
  it('maps NotAllowedError to a permission message', () => {
    const err = new DOMException('Permission denied', 'NotAllowedError');
    expect(describeMicError(err)).toMatch(/permission was denied/i);
  });

  it('maps NotFoundError to a no-microphone message', () => {
    const err = new DOMException('No device', 'NotFoundError');
    expect(describeMicError(err)).toMatch(/no microphone was found/i);
  });

  it('maps NotReadableError to an in-use message', () => {
    const err = new DOMException('Device busy', 'NotReadableError');
    expect(describeMicError(err)).toMatch(/in use by another application/i);
  });

  it('maps OverconstrainedError to a constraints message', () => {
    const err = new DOMException('Constraints could not be satisfied', 'OverconstrainedError');
    expect(describeMicError(err)).toMatch(/echo cancellation/i);
  });

  it('falls back to a specific message for unknown errors', () => {
    const err = new Error('boom');
    expect(describeMicError(err)).toMatch(/Microphone could not be started/);
    expect(describeMicError(err)).toContain('boom');
  });
});

describe('describeNetworkError', () => {
  it('maps the browser collapsed "Failed to fetch" to an actionable message', () => {
    const err = new TypeError('Failed to fetch');
    expect(describeNetworkError(err)).toMatch(/could not reach the JARVIS server/i);
  });

  it('mentions the url when provided', () => {
    const err = new TypeError('Failed to fetch');
    expect(describeNetworkError(err, 'http://localhost:8000/health')).toContain(
      'http://localhost:8000/health',
    );
  });

  it('maps timeouts separately', () => {
    const err = new Error('timed out');
    expect(describeNetworkError(err)).toMatch(/timed out/i);
  });
});

describe('classifyError', () => {
  it('returns a VoiceError with stage, code and message', () => {
    const err = new DOMException('blocked', 'NotAllowedError');
    const classified = classifyError('mic', err);
    expect(classified).toBeInstanceOf(VoiceError);
    expect(classified.stage).toBe('mic');
    expect(classified.code).toBe('NotAllowedError');
    expect(classified.message).toMatch(/permission was denied/i);
  });

  it('maps ws/fetch/health stages through describeNetworkError', () => {
    const classified = classifyError('ws', new TypeError('Failed to fetch'));
    expect(classified.code).toBe('network_error');
    expect(classified.message).toMatch(/could not reach the JARVIS server/i);
  });

  it('keeps the raw message for unknown stages', () => {
    const classified = classifyError('tts', new Error('voice not found'));
    expect(classified.message).toContain('voice not found');
  });
});

describe('toBaseUrl', () => {
  it('adds http scheme when missing', () => {
    expect(toBaseUrl('localhost:8000')).toBe('http://localhost:8000');
  });

  it('preserves an explicit scheme', () => {
    expect(toBaseUrl('https://jarvis.local')).toBe('https://jarvis.local');
  });

  it('strips trailing slashes', () => {
    expect(toBaseUrl('localhost:8000///')).toBe('http://localhost:8000');
  });

  it('defaults to loopback', () => {
    expect(toBaseUrl('')).toBe('http://127.0.0.1:8000');
  });
});

describe('withTimeout', () => {
  it('resolves when the promise resolves first', async () => {
    const value = await withTimeout(Promise.resolve('ok'), 100, 'timeout');
    expect(value).toBe('ok');
  });

  it('rejects with the given message on expiry', async () => {
    const never = new Promise<string>((resolve) => {
      setTimeout(resolve, 1000);
    });
    await expect(withTimeout(never, 20, 'timed out')).rejects.toThrow('timed out');
  });

  it('propagates the original rejection', async () => {
    const failing = Promise.reject(new Error('original'));
    await expect(withTimeout(failing, 100, 'timeout')).rejects.toThrow('original');
  });
});

describe('retryWithBackoff', () => {
  it('succeeds on the first attempt', async () => {
    const fn = vi.fn().mockResolvedValue(42);
    const result = await retryWithBackoff(fn, 2, 5, 20, 'test');
    expect(result).toBe(42);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('retries then succeeds', async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error('first'))
      .mockRejectedValueOnce(new Error('second'))
      .mockResolvedValue('recovered');
    const result = await retryWithBackoff(fn, 3, 5, 20, 'test');
    expect(result).toBe('recovered');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('throws the last error after exhausting retries', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('always fails'));
    await expect(retryWithBackoff(fn, 2, 5, 20, 'test')).rejects.toThrow('always fails');
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it('does not retry when retries is zero', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('no retries'));
    await expect(retryWithBackoff(fn, 0, 5, 20, 'test')).rejects.toThrow('no retries');
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
