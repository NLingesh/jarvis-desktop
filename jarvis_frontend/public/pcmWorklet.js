// AudioWorkletProcessor: resample mono float audio to 16 kHz PCM16 LE and post
// it to the main thread in ~64 ms chunks. Runs on the audio render thread.
// Loaded with `audioContext.audioWorklet.addModule()` — must stay import-free.
//
// Protocol (main thread <-> worklet):
//   main -> worklet:  { type: 'flush' }      finish the stream
//   worklet -> main:  { type: 'pcm', pcm: ArrayBuffer, final: boolean }

const TARGET_RATE = 16000;
// ~64 ms of 16 kHz audio; keeps the main thread message rate low.
const POST_SAMPLES = 1024;

class Pcm16CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const inputRate =
      (options && options.processorOptions && options.processorOptions.sampleRate) || sampleRate;
    this._ratio = inputRate / TARGET_RATE;
    this._posAbs = 0;
    this._chunkStart = 0;
    this._prev = 0;
    this._lastN = 0;
    this._flushed = false;
    this._out = new Int16Array(16384);
    this._outLen = 0;

    this.port.onmessage = (event) => {
      if (event.data && event.data.type === 'flush') {
        this._flushTail();
      }
    };
  }

  _emit(value) {
    const v = Math.max(-1, Math.min(1, value));
    this._out[this._outLen++] = v < 0 ? (v * 0x8000) | 0 : (v * 0x7fff) | 0;
  }

  _drain(final) {
    if (this._outLen === 0) {
      if (final) {
        this.port.postMessage({ type: 'pcm', pcm: new ArrayBuffer(0), final: true });
      }
      return;
    }
    const bytes = new Uint8Array(this._outLen * 2);
    for (let i = 0; i < this._outLen; i++) {
      bytes[i * 2] = this._out[i] & 0xff;
      bytes[i * 2 + 1] = (this._out[i] >> 8) & 0xff;
    }
    this._outLen = 0;
    this.port.postMessage({ type: 'pcm', pcm: bytes.buffer, final: !!final }, [bytes.buffer]);
  }

  _flushTail() {
    if (this._flushed) return;
    this._flushed = true;
    const rel = this._posAbs - this._chunkStart;
    if (rel < 0 && this._lastN > 0) {
      this._emit(this._prev);
      this._posAbs += this._ratio;
    }
    this._drain(true);
  }

  process(inputs) {
    if (this._flushed) return true;
    const input = inputs[0] && inputs[0][0];
    if (input) {
      const n = input.length;
      while (true) {
        const rel = this._posAbs - this._chunkStart;
        if (rel < 0) {
          const frac = rel + 1;
          this._emit(this._prev * (1 - frac) + input[0] * frac);
        } else {
          if (rel >= n - 1) break;
          const base = Math.floor(rel);
          const frac = rel - base;
          this._emit(input[base] * (1 - frac) + input[base + 1] * frac);
        }
        this._posAbs += this._ratio;
      }
      this._chunkStart += n;
      this._prev = input[n - 1];
      this._lastN = n;
    }
    if (this._outLen >= POST_SAMPLES) {
      this._drain(false);
    }
    return true;
  }
}

registerProcessor('pcm16-capture', Pcm16CaptureProcessor);
