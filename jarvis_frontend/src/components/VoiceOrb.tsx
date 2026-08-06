import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface VoiceOrbProps {
  state: 'idle' | 'listening' | 'thinking' | 'speaking';
  analysers: AnalyserNode[];
}

const VoiceOrb: React.FC<VoiceOrbProps> = ({ state, analysers }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const particlesRef = useRef<THREE.Points | null>(null);
  const animationIdRef = useRef<number>();
  const stateRef = useRef(state);
  const analysersRef = useRef(analysers);

  stateRef.current = state;
  analysersRef.current = analysers;

  useEffect(() => {
    if (!containerRef.current) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (err) {
      return;
    }

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(
      75,
      containerRef.current.clientWidth / containerRef.current.clientHeight,
      0.1,
      1000,
    );

    renderer.setSize(containerRef.current.clientWidth, containerRef.current.clientHeight);
    renderer.setClearColor(0x000000, 0);
    containerRef.current.appendChild(renderer.domElement);

    camera.position.z = 3;
    sceneRef.current = scene;

    const particleCount = 1000;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    const velocities = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount * 3; i += 3) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 1;

      positions[i] = r * Math.sin(phi) * Math.cos(theta);
      positions[i + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i + 2] = r * Math.cos(phi);

      velocities[i] = (Math.random() - 0.5) * 0.01;
      velocities[i + 1] = (Math.random() - 0.5) * 0.01;
      velocities[i + 2] = (Math.random() - 0.5) * 0.01;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const material = new THREE.PointsMaterial({
      color: 0x00ff88,
      size: 0.02,
      sizeAttenuation: true,
      transparent: true,
      opacity: 0.8,
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);
    particlesRef.current = particles;

    const light = new THREE.PointLight(0x00ff88, 1, 100);
    light.position.set(5, 5, 5);
    scene.add(light);

    const dataArray = new Uint8Array(256);

    const animate = () => {
      animationIdRef.current = requestAnimationFrame(animate);

      const currentAnalysers = analysersRef.current;
      if (currentAnalysers.length > 0 && currentAnalysers[0]) {
        try {
          currentAnalysers[0].getByteFrequencyData(dataArray);
        } catch (err) {
          // analyser not connected to a live source yet
        }
      }

      const average = dataArray.reduce((a, b) => a + b) / dataArray.length / 255;

      const positionAttribute = geometry.getAttribute('position');
      const positionArray = positionAttribute.array as Float32Array;

      for (let i = 0; i < particleCount * 3; i += 3) {
        positionArray[i] += velocities[i];
        positionArray[i + 1] += velocities[i + 1];
        positionArray[i + 2] += velocities[i + 2];

        let x = positionArray[i];
        let y = positionArray[i + 1];
        let z = positionArray[i + 2];

        const distance = Math.sqrt(x * x + y * y + z * z);
        const targetDistance = 1 + average * 0.5;

        if (distance > 0) {
          x = (x / distance) * targetDistance;
          y = (y / distance) * targetDistance;
          z = (z / distance) * targetDistance;
        }

        positionArray[i] = x;
        positionArray[i + 1] = y;
        positionArray[i + 2] = z;
      }

      positionAttribute.needsUpdate = true;

      const mat = particles.material as THREE.PointsMaterial;
      const currentState = stateRef.current;
      switch (currentState) {
        case 'idle':
          mat.color.setHex(0x00ff88);
          mat.size = 0.02;
          particles.rotation.x += 0.0002;
          particles.rotation.y += 0.0003;
          break;
        case 'listening':
          mat.color.setHex(0x00ffff);
          mat.size = 0.025 + Math.sin(Date.now() * 0.003) * 0.005;
          particles.rotation.x += 0.001;
          particles.rotation.y += 0.0015;
          break;
        case 'thinking':
          mat.color.setHex(0xffff00);
          mat.size = 0.02 + average * 0.02;
          particles.rotation.x += 0.0005;
          particles.rotation.y += 0.0008;
          break;
        case 'speaking':
          mat.color.setHex(0xff00ff);
          mat.size = 0.02 + average * 0.03;
          particles.rotation.x += 0.002;
          particles.rotation.y += 0.003;
          break;
      }

      renderer.render(scene, camera);
    };

    animate();

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
      containerRef.current?.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div
      className="orb-base"
      style={{ width: '100%', height: '100%' }}
      role="img"
      aria-label={`JARVIS orb, state: ${state}`}
      aria-hidden={false}
    >
      <div className="orb-fallback" aria-hidden="true" />
    </div>
  );
};

export default VoiceOrb;
