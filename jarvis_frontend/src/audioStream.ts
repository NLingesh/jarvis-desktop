export type Resampler = {
  process(input: Float32Array): Uint8Array;
  finish(): Uint8Array;
};

export const uint8ToBase64 = (bytes: Uint8Array): string => {
  let binary = '';
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
};

/**
 * Streaming linear-interpolation resampler that converts arbitrary-rate mono
 * float audio into 16 kHz PCM16 little-endian byte chunks.
 */
export const createPcm16Resampler = (targetRate: number, inputRate: number): Resampler => {
  const ratio = inputRate / targetRate;
  let posAbs = 0;
  let chunkStart = 0;
  let prev = 0;
  const out = new Int16Array(16384);
  let outLen = 0;

  const emit = (s: number) => {
    const v = Math.max(-1, Math.min(1, s));
    out[outLen++] = v < 0 ? (v * 0x8000) | 0 : (v * 0x7fff) | 0;
  };

  const flush = (): Uint8Array => {
    if (outLen === 0) return new Uint8Array(0);
    const bytes = new Uint8Array(outLen * 2);
    for (let i = 0; i < outLen; i++) {
      bytes[i * 2] = out[i] & 0xff;
      bytes[i * 2 + 1] = (out[i] >> 8) & 0xff;
    }
    outLen = 0;
    return bytes;
  };

  let lastN = 0;
  const process = (input: Float32Array): Uint8Array => {
    const n = input.length;
    while (true) {
      const rel = posAbs - chunkStart;
      if (rel < 0) {
        const frac = rel + 1;
        emit(prev * (1 - frac) + input[0] * frac);
      } else {
        if (rel >= n - 1) break;
        const base = Math.floor(rel);
        const frac = rel - base;
        emit(input[base] * (1 - frac) + input[base + 1] * frac);
      }
      posAbs += ratio;
    }
    chunkStart += n;
    prev = input[n - 1];
    lastN = n;
    return flush();
  };

  const finish = (): Uint8Array => {
    // One output sample is deferred at every chunk boundary because it needs
    // lookahead into the next chunk. At stream end, emit it with the last
    // available sample.
    const rel = posAbs - chunkStart;
    if (rel < 0 && lastN > 0) {
      emit(prev);
      posAbs += ratio;
    }
    return flush();
  };

  return { process, finish };
};

export const decodePcm16Le = (bytes: Uint8Array): number[] => {
  const out = new Array<number>(bytes.length / 2);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  for (let i = 0; i < out.length; i++) {
    out[i] = view.getInt16(i * 2, true);
  }
  return out;
};

/**
 * Root-mean-square energy of a PCM16 little-endian byte buffer, scaled to the
 * Int16 full range (0..~32768). Used for silence/endpoint detection.
 */
export const computeRms = (pcm: Uint8Array): number => {
  const view = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
  const count = Math.floor(pcm.byteLength / 2);
  if (count === 0) return 0;
  let sum = 0;
  for (let i = 0; i < count; i++) {
    const s = view.getInt16(i * 2, true);
    sum += s * s;
  }
  return Math.sqrt(sum / count);
};
