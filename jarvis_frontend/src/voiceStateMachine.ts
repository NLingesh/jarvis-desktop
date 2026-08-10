export type VoiceState =
  | 'idle'
  | 'requesting_mic'
  | 'connecting_ws'
  | 'listening'
  | 'endpointing'
  | 'transcribing'
  | 'processing'
  | 'generating_speech'
  | 'speaking'
  | 'error';

export interface VoiceStateContext {
  micPermissionGranted: boolean;
  wsConnected: boolean;
  hasTranscript: boolean;
  hasResponse: boolean;
  sttAvailable: boolean;
  ttsAvailable: boolean;
}

export interface VoiceStateTransition {
  from: VoiceState;
  to: VoiceState;
  action: string;
  guard?: (ctx: VoiceStateContext) => boolean;
}

export const VALID_TRANSITIONS: VoiceStateTransition[] = [
  { from: 'idle', to: 'requesting_mic', action: 'start_voice' },
  { from: 'idle', to: 'connecting_ws', action: 'wake_word_detected' },
  {
    from: 'requesting_mic',
    to: 'connecting_ws',
    action: 'mic_granted',
    guard: (ctx) => ctx.wsConnected,
  },
  { from: 'requesting_mic', to: 'error', action: 'mic_denied' },
  { from: 'connecting_ws', to: 'listening', action: 'ws_open' },
  { from: 'connecting_ws', to: 'error', action: 'ws_failed' },
  { from: 'listening', to: 'endpointing', action: 'silence_detected' },
  { from: 'listening', to: 'transcribing', action: 'manual_stop' },
  {
    from: 'endpointing',
    to: 'transcribing',
    action: 'silence_timer_expired',
  },
  { from: 'transcribing', to: 'processing', action: 'stt_complete' },
  { from: 'transcribing', to: 'error', action: 'stt_failed' },
  { from: 'processing', to: 'generating_speech', action: 'llm_complete' },
  { from: 'processing', to: 'error', action: 'llm_failed' },
  { from: 'generating_speech', to: 'speaking', action: 'tts_start' },
  { from: 'generating_speech', to: 'error', action: 'tts_failed' },
  { from: 'speaking', to: 'idle', action: 'audio_finished' },
  { from: 'error', to: 'idle', action: 'dismiss' },
  { from: 'error', to: 'requesting_mic', action: 'retry' },
];

export function canTransition(
  current: VoiceState,
  action: string,
  ctx: VoiceStateContext,
): VoiceState | null {
  const transition = VALID_TRANSITIONS.find(
    (t) => t.from === current && t.action === action && (!t.guard || t.guard(ctx)),
  );
  return transition ? transition.to : null;
}

export function transition(
  current: VoiceState,
  action: string,
  ctx: VoiceStateContext,
): VoiceState {
  const next = canTransition(current, action, ctx);
  if (next) return next;
  console.warn(`[voice:fsm] Invalid transition: ${current} + ${action} -> blocked`);
  return current;
}
