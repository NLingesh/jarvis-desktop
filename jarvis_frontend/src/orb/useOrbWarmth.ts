import { useCallback, useEffect, useState } from 'react';

export type OrbExpression =
  'calm' | 'alert' | 'warm' | 'focused' | 'playful' | 'concerned' | 'curious' | 'sleepy';

const WARMTH_PALETTE = {
  cold: '#00C8FF',
  warm: '#38BDF8',
  hot: '#00E5FF',
  dimmed: '#0E7490',
  error: '#F87171',
  amber: '#FBBF24',
} as const;

type WarmthLevel = 'cold' | 'warm' | 'hot' | 'dimmed' | 'error';

interface WarmthState {
  level: WarmthLevel;
  hex: string;
  expression: OrbExpression;
}

function getBaseWarmth(state: string): WarmthLevel {
  switch (state) {
    case 'thinking':
    case 'speaking':
    case 'listening':
      return 'hot';
    case 'idle':
    default:
      return 'cold';
  }
}

export function useOrbWarmth(state: string, isError: boolean) {
  const [warmth, setWarmth] = useState<WarmthState>(() => ({
    level: isError ? 'error' : getBaseWarmth(state),
    hex: isError ? WARMTH_PALETTE.error : WARMTH_PALETTE[getBaseWarmth(state)],
    expression: isError ? 'concerned' : 'calm',
  }));

  useEffect(() => {
    const level = isError ? 'error' : getBaseWarmth(state);
    const target = WARMTH_PALETTE[level];
    setWarmth({
      level,
      hex: target,
      expression: isError
        ? 'concerned'
        : state === 'listening'
          ? 'alert'
          : state === 'thinking'
            ? 'focused'
            : 'calm',
    });
  }, [state, isError]);

  const setExpression = useCallback((expression: OrbExpression) => {
    setWarmth((prev) => {
      if (prev.expression === expression) return prev;
      return { ...prev, expression };
    });
  }, []);

  return { warmth, setExpression, palette: WARMTH_PALETTE };
}
