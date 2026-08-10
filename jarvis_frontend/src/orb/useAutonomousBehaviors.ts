import { useCallback, useEffect, useRef, useState } from 'react';

export type OrbExpression =
  'calm' | 'alert' | 'warm' | 'focused' | 'playful' | 'concerned' | 'curious' | 'sleepy';

export interface AutonomousState {
  expression: OrbExpression;
  isSleepy: boolean;
  isFocused: boolean;
  idleMinutes: number;
  lastActivity: number;
  whisper: string | null;
}

const IDLE_SLEEPY_MS = 15 * 60 * 1000;
const CHECK_INTERVAL_MS = 5000;

export function useAutonomousBehaviors(
  isPanelOpen: boolean,
  isVoiceActive: boolean,
  isTyping: boolean,
) {
  const [state, setState] = useState<AutonomousState>(() => ({
    expression: 'calm',
    isSleepy: false,
    isFocused: false,
    idleMinutes: 0,
    lastActivity: Date.now(),
    whisper: null,
  }));

  const stateRef = useRef(state);
  stateRef.current = state;

  const recordActivity = useCallback(() => {
    setState((prev) => {
      const now = Date.now();
      const idleMs = now - prev.lastActivity;
      const idleMinutes = idleMs / 60000;
      const isSleepy = idleMs > IDLE_SLEEPY_MS && !isVoiceActive;
      const isFocused = isPanelOpen && !isVoiceActive;
      let expression: OrbExpression = 'calm';

      if (isVoiceActive) {
        expression = 'alert';
      } else if (isPanelOpen) {
        expression = isTyping ? 'focused' : 'warm';
      } else if (isSleepy) {
        expression = 'sleepy';
      } else if (idleMinutes > 2 && idleMinutes < 15) {
        expression = 'playful';
      }

      return {
        ...prev,
        idleMinutes,
        lastActivity: now,
        isSleepy,
        isFocused,
        expression,
      };
    });
  }, [isPanelOpen, isVoiceActive, isTyping]);

  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now();
      const idleMs = now - stateRef.current.lastActivity;
      setState((prev) => {
        const idleMinutes = idleMs / 60000;
        const isSleepy = idleMs > IDLE_SLEEPY_MS && !isVoiceActive && !isPanelOpen;
        const isFocused = isPanelOpen && !isVoiceActive;
        let expression: OrbExpression = prev.expression;

        if (isVoiceActive) {
          expression = 'alert';
        } else if (isPanelOpen) {
          expression = isTyping ? 'focused' : 'warm';
        } else if (isSleepy) {
          expression = 'sleepy';
        } else if (idleMinutes > 2 && idleMinutes < 15) {
          expression = 'playful';
        } else {
          expression = 'calm';
        }

        return { ...prev, idleMinutes, isSleepy, isFocused, expression };
      });
    }, CHECK_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [isPanelOpen, isVoiceActive, isTyping]);

  const dismissWhisper = useCallback(() => {
    setState((prev) => ({ ...prev, whisper: null }));
  }, []);

  return {
    state,
    recordActivity,
    dismissWhisper,
  };
}
