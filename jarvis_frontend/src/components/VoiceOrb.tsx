import React, { useEffect, useRef, useCallback } from 'react';
import * as THREE from 'three';
import { useOrbWarmth } from '../orb/useOrbWarmth';
import { useMicroMovements } from '../orb/useMicroMovements';
import { useParticleMemory } from '../orb/useParticleMemory';

interface VoiceOrbProps {
  state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline';
  analysers: AnalyserNode[];
  isError?: boolean;
  isPanelOpen?: boolean;
  isVoiceActive?: boolean;
  isTyping?: boolean;
  onClick?: () => void;
  onMouseDown?: (e: React.MouseEvent) => void;
  onMouseUp?: (e: React.MouseEvent) => void;
  onMouseLeave?: () => void;
}

const PARTICLE_COUNT = 600;
const EPS = 0.0001;

const VoiceOrb: React.FC<VoiceOrbProps> = ({
  state,
  analysers,
  isError = false,
  isPanelOpen = false,
  isVoiceActive = false,
  isTyping: _isTyping = false,
  onClick,
  onMouseDown,
  onMouseUp,
  onMouseLeave,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const particlesRef = useRef<THREE.Points | null>(null);
  const coreRef = useRef<THREE.Mesh | null>(null);
  const auraRef = useRef<THREE.Mesh | null>(null);
  const animationIdRef = useRef<number>();
  const stateRef = useRef(state);
  stateRef.current = state;

  const { warmth } = useOrbWarmth(state, isError);
  const lastTimestampRef = useRef(0);
  const lastAudioRmsRef = useRef(0);
  const shockwaveRef = useRef<{ start: number; duration: number } | null>(null);

  const microMovements = useMicroMovements(Date.now(), false, isPanelOpen && !isVoiceActive);
  useParticleMemory(PARTICLE_COUNT, state, analysers, lastAudioRmsRef.current);

  const analysersRef = useRef(analysers);
  analysersRef.current = analysers;

  const triggerShockwave = useCallback(() => {
    shockwaveRef.current = { start: performance.now(), duration: 400 };
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      return;
    }

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      75,
      containerRef.current.clientWidth / containerRef.current.clientHeight,
      0.1,
      1000,
    );
    camera.position.z = 3;

    renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
    renderer.setClearColor(0x000000, 0);
    containerRef.current.appendChild(renderer.domElement);

    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const velocities = new Float32Array(PARTICLE_COUNT * 3);
    const basePositions = new Float32Array(PARTICLE_COUNT * 3);

    for (let i = 0; i < PARTICLE_COUNT * 3; i += 3) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 1;

      positions[i] = r * Math.sin(phi) * Math.cos(theta);
      positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i + 2] = r * Math.cos(phi);

      basePositions[i] = positions[i];
      basePositions[i + 1] = positions[i + 1];
      basePositions[i + 2] = positions[i + 2];

      velocities[i] = (Math.random() - 0.5) * 0.01;
      velocities[i + 1] = (Math.random() - 0.5) * 0.01;
      velocities[i + 2] = (Math.random() - 0.5) * 0.01;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      color: new THREE.Color(warmth.hex),
      size: 0.02,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.8,
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);
    particlesRef.current = particles;

    const coreGeometry = new THREE.SphereGeometry(0.25, 32, 32);
    const coreMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color(warmth.hex),
      transparent: true,
      opacity: 0.9,
    });
    const core = new THREE.Mesh(coreGeometry, coreMaterial);
    scene.add(core);
    coreRef.current = core;

    const auraGeometry = new THREE.SphereGeometry(0.4, 32, 32);
    const auraMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color(warmth.hex),
      transparent: true,
      opacity: 0.15,
    });
    const aura = new THREE.Mesh(auraGeometry, auraMaterial);
    scene.add(aura);
    auraRef.current = aura;

    const dataArray = new Uint8Array(256);
    const shockwaveVelocities = new Float32Array(PARTICLE_COUNT * 3);

    const animate = (timestamp: number) => {
      animationIdRef.current = requestAnimationFrame(animate);

      const dt = lastTimestampRef.current
        ? Math.min((timestamp - lastTimestampRef.current) / 1000, 0.1)
        : 0.016;
      lastTimestampRef.current = timestamp;

      const currentAnalysers = analysersRef.current;
      if (currentAnalysers.length > 0 && currentAnalysers[0]) {
        try {
          currentAnalysers[0].getByteFrequencyData(dataArray);
        } catch {
          // analyser not connected yet
        }
      }

      const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length / 255;
      lastAudioRmsRef.current = average;

      const positionAttribute = geometry.getAttribute('position');
      const positionArray = positionAttribute.array as Float32Array;
      const currentState = stateRef.current;

      for (let i = 0; i < PARTICLE_COUNT * 3; i += 3) {
        positionArray[i] += velocities[i];
        positionArray[i + 1] += velocities[i + 1];
        positionArray[i + 2] += velocities[i + 2];

        let x = positionArray[i];
        let y = positionArray[i + 1];
        let z = positionArray[i + 2];

        const distance = Math.sqrt(x * x + y * y + z * z);
        let targetDistance = 1;

        if (currentState === 'listening') {
          targetDistance = 1 + Math.max(0, -y * 0.3) + average * 0.2;
        } else if (currentState === 'thinking') {
          targetDistance = 1 + (Math.abs(x) > 0.5 ? 0.3 : 0) + average * 0.1;
        } else if (currentState === 'speaking') {
          targetDistance = 1 + average * 0.4;
        } else {
          targetDistance = 1 + average * 0.2;
        }

        if (distance > EPS) {
          x = (x / distance) * targetDistance;
          y = (y / distance) * targetDistance;
          z = (z / distance) * targetDistance;
        }

        positionArray[i] = x;
        positionArray[i + 1] = y;
        positionArray[i + 2] = z;
      }

      if (shockwaveRef.current) {
        const elapsed = timestamp - shockwaveRef.current.start;
        const progress = Math.min(elapsed / shockwaveRef.current.duration, 1);
        const amplitude = Math.sin(progress * Math.PI) * 0.5;

        for (let i = 0; i < PARTICLE_COUNT; i++) {
          const idx = i * 3;
          const bx = basePositions[idx];
          const by = basePositions[idx + 1];
          const bz = basePositions[idx + 2];
          const len = Math.sqrt(bx * bx + by * by + bz * bz) || 1;
          shockwaveVelocities[idx] = (bx / len) * amplitude * dt * 2;
          shockwaveVelocities[idx + 1] = (by / len) * amplitude * dt * 2;
          shockwaveVelocities[idx + 2] = (bz / len) * amplitude * dt * 2;

          positionArray[idx] += shockwaveVelocities[idx];
          positionArray[idx + 1] += shockwaveVelocities[idx + 1];
          positionArray[idx + 2] += shockwaveVelocities[idx + 2];
        }

        if (progress >= 1) {
          shockwaveRef.current = null;
        }
      }

      positionAttribute.needsUpdate = true;

      const mat = particles.material as THREE.PointsMaterial;
      mat.color.set(warmth.hex);
      mat.opacity = isError ? 0.5 : 0.8;

      const baseRotX =
        currentState === 'idle'
          ? 0.0002
          : currentState === 'listening'
            ? 0.001
            : currentState === 'thinking'
              ? 0.0005
              : 0.002;
      const baseRotY =
        currentState === 'idle'
          ? 0.0003
          : currentState === 'listening'
            ? 0.0015
            : currentState === 'thinking'
              ? 0.0008
              : 0.003;
      particles.rotation.x += baseRotX + microMovements.wobbleAngle * 0.0002;
      particles.rotation.y += baseRotY + microMovements.wobbleAngle * 0.0003;
      particles.position.x = microMovements.driftX * 0.01;
      particles.position.y = microMovements.driftY * 0.01;

      if (core && aura) {
        const scale = microMovements.breathScale;
        core.scale.setScalar(scale);
        aura.scale.setScalar(scale * 1.6);
        core.rotation.y += 0.002;
        aura.rotation.y -= 0.001;

        if (isError) {
          core.material.opacity = 0.5 + Math.sin(timestamp * 0.01) * 0.3;
          aura.material.opacity = 0.1 + Math.sin(timestamp * 0.01) * 0.1;
        } else {
          core.material.opacity = 0.9;
          aura.material.opacity = 0.15 + microMovements.shadowOpacity * 0.1;
        }
      }

      renderer.render(scene, camera);
    };

    animationIdRef.current = requestAnimationFrame(animate);

    const handleResize = () => {
      if (!containerRef.current) return;
      const width = containerRef.current.clientWidth;
      const height = containerRef.current.clientHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (animationIdRef.current) {
        cancelAnimationFrame(animationIdRef.current);
      }
      renderer.dispose();
      geometry.dispose();
      material.dispose();
      coreGeometry.dispose();
      coreMaterial.dispose();
      auraGeometry.dispose();
      auraMaterial.dispose();
      if (containerRef.current && renderer.domElement) {
        containerRef.current.removeChild(renderer.domElement);
      }
    };
  }, []);

  const handleClick = useCallback(() => {
    triggerShockwave();
    onClick?.();
  }, [onClick, triggerShockwave]);

  return (
    <div
      ref={containerRef}
      className="orb-base"
      style={{ width: '100%', height: '100%' }}
      role="img"
      aria-label={`JARVIS orb, state: ${state}`}
      aria-hidden={false}
      onClick={handleClick}
      onMouseDown={onMouseDown}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseLeave}
    >
      <div className="orb-fallback" aria-hidden="true" />
    </div>
  );
};

export default VoiceOrb;
