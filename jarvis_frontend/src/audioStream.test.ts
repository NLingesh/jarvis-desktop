import { describe, expect, it } from 'vitest';
import { createPcm16Resampler, decodePcm16Le, uint8ToBase64 } from './audioStream';

describe('createPcm16Resampler', () => {
  it('outputs 16 kHz PCM16 for a 48 kHz input', () => {
    const inputRate = 48000;
    const targetRate = 16000;
    const resampler = createPcm16Resampler(targetRate, inputRate);
    const input = new Float32Array(inputRate); // 1 second of silence
    const out = resampler.process(input);
    const tail = resampler.finish();
    const merged = new Uint8Array(out.length + tail.length);
    merged.set(out, 0);
    merged.set(tail, out.length);
    const samples = decodePcm16Le(merged);
    // Downsampling by 3: expect ~16000 output samples (within a couple).
    expect(samples.length).toBeGreaterThan(15990);
    expect(samples.length).toBeLessThan(16010);
    expect(samples.every((s) => s === 0)).toBe(true);
  });

  it('streams across chunk boundaries without gaps or overlap', () => {
    const resampler = createPcm16Resampler(16000, 16000);
    // A full 1 kHz sine wave at 16 kHz = 16 samples per period, 1 second long.
    const total = new Float32Array(16000);
    for (let i = 0; i < total.length; i++) {
      total[i] = Math.sin((2 * Math.PI * 1000 * i) / 16000);
    }
    let bytes = new Uint8Array(0);
    for (let offset = 0; offset < total.length; offset += 1000) {
      const chunk = total.subarray(offset, offset + 1000);
      const part = resampler.process(chunk);
      const merged = new Uint8Array(bytes.length + part.length);
      merged.set(bytes, 0);
      merged.set(part, bytes.length);
      bytes = merged;
    }
    const tail = resampler.finish();
    const merged = new Uint8Array(bytes.length + tail.length);
    merged.set(bytes, 0);
    merged.set(tail, bytes.length);
    bytes = merged;
    const samples = decodePcm16Le(bytes);
    expect(samples.length).toBe(total.length);
    // Compare against the expected sine quantization for a fair sample.
    for (let i = 0; i < samples.length; i += 137) {
      const expected = Math.round(Math.max(-1, Math.min(1, total[i])) * 32767);
      expect(Math.abs(samples[i] - expected)).toBeLessThanOrEqual(1);
    }
  });

  it('finish flushes the deferred boundary sample at 1:1 rate', () => {
    const resampler = createPcm16Resampler(16000, 16000);
    const input = new Float32Array(100).fill(0.5);
    const out = resampler.process(input);
    const tail = resampler.finish();
    expect(decodePcm16Le(out).length).toBe(99);
    expect(decodePcm16Le(tail).length).toBe(1);
  });

  it('clamps samples to the PCM16 range', () => {
    const resampler = createPcm16Resampler(16000, 16000);
    const input = new Float32Array(100).fill(2.0);
    const out = decodePcm16Le(resampler.process(input));
    expect(out.every((s) => s === 32767)).toBe(true);
  });
});

describe('uint8ToBase64', () => {
  it('round-trips bytes through atob', () => {
    const bytes = new Uint8Array([1, 2, 3, 255, 0, 128]);
    const b64 = uint8ToBase64(bytes);
    const decoded = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    expect(decoded).toEqual(bytes);
  });
});
