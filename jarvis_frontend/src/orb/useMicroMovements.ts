import { useMemo } from 'react';

export interface MicroMovements {
  breathPhase: number;
  breathScale: number;
  driftX: number;
  driftY: number;
  wobbleAngle: number;
  shadowOpacity: number;
}

const BREATH_CYCLE_MS = 4500;
const DRIFT_CYCLE_MS = 12000;

export function useMicroMovements(timestamp: number, isSleepy: boolean, isFocused: boolean) {
  return useMemo(() => {
    const breathCycle = isSleepy ? BREATH_CYCLE_MS * 1.33 : BREATH_CYCLE_MS;
    const breathPhase = (timestamp % breathCycle) / breathCycle;
    const breathScale = 1 + Math.sin(breathPhase * Math.PI * 2) * 0.03;

    const driftPhase = (timestamp % DRIFT_CYCLE_MS) / DRIFT_CYCLE_MS;
    const driftAmp = isFocused ? 0.3 : isSleepy ? 3 : 1.5;
    const driftX = Math.sin(driftPhase * Math.PI * 2) * driftAmp;
    const driftY = Math.cos(driftPhase * Math.PI * 2 * 0.7) * driftAmp;

    const wobblePhase = (timestamp * 0.0003) % (Math.PI * 2);
    const wobbleAngle = Math.sin(wobblePhase) * 0.3;

    const shadowOpacity = 0.3 + Math.sin(breathPhase * Math.PI * 2) * 0.2;

    return {
      breathPhase,
      breathScale: isFocused ? 1 + (breathScale - 1) * 0.5 : breathScale,
      driftX,
      driftY,
      wobbleAngle,
      shadowOpacity,
    };
  }, [timestamp, isSleepy, isFocused]);
}
