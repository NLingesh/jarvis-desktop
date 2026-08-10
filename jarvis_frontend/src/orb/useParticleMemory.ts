import { useRef } from 'react';

export interface ParticleMemory {
  trailPositions: Float32Array | null;
  echoStrength: number;
}

const ECHO_DECAY_MS = 3000;

export function useParticleMemory(
  particleCount: number,
  state: string,
  _analysers: AnalyserNode[],
  lastAudioRms: number,
) {
  const trailPositions = useRef<Float32Array | null>(null);
  const lastEchoTime = useRef(0);

  if (trailPositions.current === null || trailPositions.current.length !== particleCount * 3) {
    trailPositions.current = new Float32Array(particleCount * 3);
  }

  const now = performance.now();
  const isSpeaking = state === 'speaking';
  const timeSinceLastAudio = now - lastEchoTime.current;
  const echoStrength = isSpeaking
    ? 1
    : timeSinceLastAudio < ECHO_DECAY_MS
      ? 1 - timeSinceLastAudio / ECHO_DECAY_MS
      : 0;

  if (isSpeaking && lastAudioRms > 0.01) {
    lastEchoTime.current = now;
  }

  return {
    trailPositions: trailPositions.current,
    echoStrength,
  };
}
