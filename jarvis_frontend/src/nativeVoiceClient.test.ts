import { describe, it, expect } from 'vitest';
import {
  NATIVE_COMMANDS,
  isNativeControlEvent,
  nativeStateToOrb,
  parseNativeEvent,
  type NativeDevice,
  type NativeLevelEvent,
} from './nativeVoiceClient';

describe('NATIVE_COMMANDS', () => {
  it('builds a connect command with optional device', () => {
    expect(NATIVE_COMMANDS.connect()).toBe('{"type":"connect"}');
    expect(NATIVE_COMMANDS.connect(3)).toBe('{"type":"connect","device":3}');
    expect(NATIVE_COMMANDS.connect('default')).toBe('{"type":"connect","device":"default"}');
  });

  it('builds listening commands', () => {
    expect(NATIVE_COMMANDS.startListening('ptt')).toBe('{"type":"start_listening","mode":"ptt"}');
    expect(NATIVE_COMMANDS.startListening('hands_free')).toBe(
      '{"type":"start_listening","mode":"hands_free"}',
    );
    expect(NATIVE_COMMANDS.stopListening()).toBe('{"type":"stop_listening"}');
    expect(NATIVE_COMMANDS.cancel()).toBe('{"type":"cancel"}');
  });

  it('builds device and mic test commands', () => {
    expect(NATIVE_COMMANDS.setDevice(1)).toBe('{"type":"set_device","device":1}');
    expect(NATIVE_COMMANDS.getDevices()).toBe('{"type":"get_devices"}');
    expect(NATIVE_COMMANDS.micTestStart()).toBe('{"type":"mic_test_start"}');
    expect(NATIVE_COMMANDS.micTestStop()).toBe('{"type":"mic_test_stop"}');
    expect(NATIVE_COMMANDS.ping()).toBe('{"type":"ping"}');
  });
});

describe('parseNativeEvent', () => {
  it('parses control events', () => {
    expect(parseNativeEvent({ type: 'state', state: 'READY' })).toEqual({
      type: 'state',
      state: 'READY',
    });
    expect(parseNativeEvent({ type: 'level', rms: 0.5, peak: 0.9 })).toEqual({
      type: 'level',
      rms: 0.5,
      peak: 0.9,
    } satisfies NativeLevelEvent);
    expect(parseNativeEvent({ type: 'pong' })).toEqual({ type: 'pong' });
  });

  it('rejects non-control events (transcript/response)', () => {
    expect(parseNativeEvent({ type: 'transcript', text: 'hi' })).toBeNull();
    expect(parseNativeEvent({ type: 'response', text: 'hi' })).toBeNull();
    expect(parseNativeEvent(null)).toBeNull();
    expect(parseNativeEvent('pong')).toBeNull();
  });
});

describe('isNativeControlEvent', () => {
  it('identifies control message types', () => {
    expect(isNativeControlEvent('state')).toBe(true);
    expect(isNativeControlEvent('level')).toBe(true);
    expect(isNativeControlEvent('devices')).toBe(true);
    expect(isNativeControlEvent('mic_test')).toBe(true);
    expect(isNativeControlEvent('pong')).toBe(true);
    expect(isNativeControlEvent('transcript')).toBe(false);
    expect(isNativeControlEvent('response')).toBe(false);
    expect(isNativeControlEvent('audio_chunk')).toBe(false);
  });
});

describe('nativeStateToOrb', () => {
  it('maps backend states to orb states', () => {
    expect(nativeStateToOrb('LISTENING')).toBe('listening');
    expect(nativeStateToOrb('PROCESSING')).toBe('thinking');
    expect(nativeStateToOrb('SPEAKING')).toBe('speaking');
    expect(nativeStateToOrb('ERROR')).toBe('error');
    expect(nativeStateToOrb('IDLE')).toBe('idle');
    expect(nativeStateToOrb('CONNECTING')).toBe('idle');
    expect(nativeStateToOrb('READY')).toBe('idle');
  });
});

// Type-level sanity checks (compile-time only usage).
const _devices: NativeDevice[] = [];
void _devices;
