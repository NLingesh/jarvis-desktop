/**
 * Backend-owned microphone voice client (`/ws/voice/native`).
 *
 * The backend captures audio locally via sounddevice and runs VAD + STT
 * in-process; the frontend only sends control commands and renders the
 * resulting state/level events plus the existing transcript/response/audio
 * flow.  Browser `getUserMedia` is never used in native mode.
 */

export type NativeVoiceMode = 'ptt' | 'tap' | 'hands_free';

export type NativeServerState =
  'IDLE' | 'CONNECTING' | 'READY' | 'LISTENING' | 'PROCESSING' | 'SPEAKING' | 'ERROR';

export interface NativeDevice {
  id: number;
  name: string;
  channels: number;
  is_default: boolean;
}

export interface NativeStateEvent {
  type: 'state';
  state: NativeServerState;
  detail?: string | null;
}

export interface NativeLevelEvent {
  type: 'level';
  rms: number;
  peak: number;
}

export interface NativeDevicesEvent {
  type: 'devices';
  devices: NativeDevice[];
}

export interface NativeMicTestEvent {
  type: 'mic_test';
  status: 'started' | 'stopped';
}

export interface NativeErrorEvent {
  type: 'error';
  message: string;
}

export type NativeControlEvent =
  | NativeStateEvent
  | NativeLevelEvent
  | NativeDevicesEvent
  | NativeMicTestEvent
  | NativeErrorEvent
  | { type: 'pong' };

export const NATIVE_COMMANDS = {
  connect: (device?: number | string) => JSON.stringify({ type: 'connect', device }),
  startListening: (mode: NativeVoiceMode) => JSON.stringify({ type: 'start_listening', mode }),
  stopListening: () => JSON.stringify({ type: 'stop_listening' }),
  cancel: () => JSON.stringify({ type: 'cancel' }),
  setDevice: (device: number | string) => JSON.stringify({ type: 'set_device', device }),
  getDevices: () => JSON.stringify({ type: 'get_devices' }),
  micTestStart: () => JSON.stringify({ type: 'mic_test_start' }),
  micTestStop: () => JSON.stringify({ type: 'mic_test_stop' }),
  ping: () => JSON.stringify({ type: 'ping' }),
} as const;

export function parseNativeEvent(data: unknown): NativeControlEvent | null {
  if (!data || typeof data !== 'object') return null;
  const event = data as Record<string, unknown>;
  const type = event.type as string;
  if (
    type === 'state' ||
    type === 'level' ||
    type === 'devices' ||
    type === 'mic_test' ||
    type === 'error' ||
    type === 'pong'
  ) {
    return event as unknown as NativeControlEvent;
  }
  return null;
}

export function isNativeControlEvent(type: string): boolean {
  return (
    type === 'state' ||
    type === 'level' ||
    type === 'devices' ||
    type === 'mic_test' ||
    type === 'pong'
  );
}

export const NATIVE_STATE_LABELS: Record<NativeServerState, string> = {
  IDLE: 'Ready',
  CONNECTING: 'Opening microphone...',
  READY: 'Listening ready',
  LISTENING: 'Listening...',
  PROCESSING: 'Processing...',
  SPEAKING: 'Speaking...',
  ERROR: 'Error',
};

/** Map a backend state to the orb UI state used elsewhere in the app. */
export function nativeStateToOrb(
  state: NativeServerState,
): 'idle' | 'listening' | 'thinking' | 'speaking' | 'error' {
  switch (state) {
    case 'LISTENING':
      return 'listening';
    case 'PROCESSING':
      return 'thinking';
    case 'SPEAKING':
      return 'speaking';
    case 'ERROR':
      return 'error';
    case 'CONNECTING':
    case 'READY':
    case 'IDLE':
    default:
      return 'idle';
  }
}
