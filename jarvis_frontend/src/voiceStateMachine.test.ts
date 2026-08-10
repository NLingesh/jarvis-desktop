import { describe, it, expect } from 'vitest';
import {
  VALID_TRANSITIONS,
  canTransition,
  transition,
  type VoiceStateContext,
} from './voiceStateMachine';

const ctx: VoiceStateContext = {
  micPermissionGranted: true,
  wsConnected: true,
  hasTranscript: true,
  hasResponse: true,
  sttAvailable: true,
  ttsAvailable: true,
};

describe('voice state machine', () => {
  it('follows the happy path idle -> speaking -> idle', () => {
    let state = canTransition('idle', 'start_voice', ctx);
    expect(state).toBe('requesting_mic');

    state = canTransition('requesting_mic', 'mic_granted', ctx);
    expect(state).toBe('connecting_ws');

    state = canTransition('connecting_ws', 'ws_open', ctx);
    expect(state).toBe('listening');

    state = canTransition('listening', 'manual_stop', ctx);
    expect(state).toBe('transcribing');

    state = canTransition('transcribing', 'stt_complete', ctx);
    expect(state).toBe('processing');

    state = canTransition('processing', 'llm_complete', ctx);
    expect(state).toBe('generating_speech');

    state = canTransition('generating_speech', 'tts_start', ctx);
    expect(state).toBe('speaking');

    state = canTransition('speaking', 'audio_finished', ctx);
    expect(state).toBe('idle');
  });

  it('allows the endpointing branch', () => {
    expect(canTransition('listening', 'silence_detected', ctx)).toBe('endpointing');
    expect(canTransition('endpointing', 'silence_timer_expired', ctx)).toBe('transcribing');
  });

  it('routes failure stages into error', () => {
    expect(canTransition('requesting_mic', 'mic_denied', ctx)).toBe('error');
    expect(canTransition('connecting_ws', 'ws_failed', ctx)).toBe('error');
    expect(canTransition('transcribing', 'stt_failed', ctx)).toBe('error');
    expect(canTransition('processing', 'llm_failed', ctx)).toBe('error');
    expect(canTransition('generating_speech', 'tts_failed', ctx)).toBe('error');
  });

  it('enforces the ws guard on mic_granted', () => {
    expect(
      canTransition('requesting_mic', 'mic_granted', { ...ctx, wsConnected: false }),
    ).toBeNull();
    expect(canTransition('requesting_mic', 'mic_granted', { ...ctx, wsConnected: true })).toBe(
      'connecting_ws',
    );
  });

  it('rejects invalid transitions', () => {
    expect(canTransition('idle', 'ws_open', ctx)).toBeNull();
    expect(canTransition('listening', 'start_voice', ctx)).toBeNull();
    expect(canTransition('speaking', 'stt_complete', ctx)).toBeNull();
  });

  it('lets the user retry or dismiss from error', () => {
    expect(canTransition('error', 'retry', ctx)).toBe('requesting_mic');
    expect(canTransition('error', 'dismiss', ctx)).toBe('idle');
  });

  it('wakes from idle via wake_word_detected', () => {
    expect(canTransition('idle', 'wake_word_detected', ctx)).toBe('connecting_ws');
  });

  it('transition() returns the next state for valid actions', () => {
    expect(transition('idle', 'start_voice', ctx)).toBe('requesting_mic');
  });

  it('transition() stays put for invalid actions', () => {
    expect(transition('idle', 'ws_open', ctx)).toBe('idle');
  });

  it('every transition has unique from+action pairs', () => {
    const pairs = VALID_TRANSITIONS.map((t) => `${t.from}:${t.action}`);
    expect(new Set(pairs).size).toBe(pairs.length);
  });
});
