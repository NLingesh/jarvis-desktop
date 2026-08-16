import React, { useRef, useEffect, useCallback, useState, useMemo } from 'react';
import './OrbEngine.css';

export type OrbState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'processing'
  | 'notification'
  | 'offline'
  | 'error'
  | 'working'
  | 'panel-open';

export interface OrbEngineProps {
  state: OrbState;
  rms?: number;
  onToggleTalk?: () => void;
  onClick?: () => void;
  onExpandPanel?: () => void;
  onSingleClick?: () => void;
  onQuickAction?: (action: 'talk' | 'chat' | 'settings') => void;
  onDragMove?: (dx: number, dy: number) => void;
  onDragEnd?: () => void;
  onContextMenu?: () => void;
  quickActionsOpen?: boolean;
  onCloseQuickActions?: () => void;
  className?: string;
  style?: React.CSSProperties;
  wakePulse?: boolean;
}

const prefersReducedMotion = () => {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
};

const STATE_COLORS: Record<OrbState, { core: string; glow: string; particle: string }> = {
  idle: { core: '#00ff88', glow: 'rgba(0,255,136,0.3)', particle: '#00ff88' },
  listening: { core: '#00ffff', glow: 'rgba(0,255,255,0.4)', particle: '#00ffff' },
  thinking: { core: '#ffcc00', glow: 'rgba(255,204,0,0.3)', particle: '#ffcc00' },
  speaking: { core: '#b366ff', glow: 'rgba(179,102,255,0.35)', particle: '#b366ff' },
  processing: { core: '#ffb020', glow: 'rgba(255,176,32,0.3)', particle: '#ffb020' },
  notification: { core: '#00ff88', glow: 'rgba(0,255,136,0.5)', particle: '#00ff88' },
  offline: { core: '#555566', glow: 'rgba(85,85,102,0.2)', particle: '#555566' },
  error: { core: '#ff4466', glow: 'rgba(255,68,102,0.4)', particle: '#ff4466' },
  working: { core: '#ffb020', glow: 'rgba(255,176,32,0.35)', particle: '#ffb020' },
  'panel-open': { core: '#00ff88', glow: 'rgba(0,255,136,0.2)', particle: '#00ff88' },
};

const QUICK_ACTIONS = [
  { id: 'talk' as const, label: 'Talk', icon: '\uD83C\uDF99\uFE0F', angle: 0 },
  { id: 'chat' as const, label: 'Chat', icon: '\uD83D\uDCAC', angle: 90 },
  { id: 'settings' as const, label: 'Settings', icon: '\u2699\uFE0F', angle: 180 },
];

function hexToRgb(hex: string): [number, number, number] {
  const m = hex.replace('#', '').match(/.{1,2}/g);
  if (!m || m.length < 3) return [0, 0, 0];
  return [parseInt(m[0], 16), parseInt(m[1], 16), parseInt(m[2], 16)];
}

function rgbToHex(r: number, g: number, b: number) {
  return '#' + [r, g, b].map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
}

function lerpColor(a: string, b: string, t: number) {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t);
}

const OrbEngine: React.FC<OrbEngineProps> = ({
  state,
  rms = 0,
  onToggleTalk,
  onClick,
  onExpandPanel,
  onSingleClick,
  onQuickAction,
  onDragMove,
  onDragEnd,
  onContextMenu,
  quickActionsOpen = false,
  onCloseQuickActions,
  className: _className,
  style,
  wakePulse = false,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const animFrameRef = useRef<number>(0);
  const particlesRef = useRef<
    Array<{
      x: number;
      y: number;
      z: number;
      vx: number;
      vy: number;
      vz: number;
      baseR: number;
      phase: number;
    }>
  >([]);
  const ripplesRef = useRef<Array<{ start: number; duration: number; maxRadius: number }>>([]);
  const wakePulsesRef = useRef<Array<{ start: number }>>([]);
  const speakingEchoRef = useRef<number>(0);
  const speakingEchoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [tooltip, setTooltip] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [dragScale, setDragScale] = useState(1);
  const reducedMotion = prefersReducedMotion();
  const stateRef = useRef(state);
  stateRef.current = state;
  const isDraggingRef = useRef(false);
  const prevStateRef = useRef<OrbState>(state);
  const transitionRef = useRef(0);

  const isPanelOpen = state === 'panel-open';
  const isNotification = state === 'notification';

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const rect = parent.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);

  useEffect(() => {
    if (particlesRef.current.length === 0) {
      const particles: typeof particlesRef.current = [];
      for (let i = 0; i < 80; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);
        const r = 0.85 + Math.random() * 0.15;
        particles.push({
          x: r * Math.sin(phi) * Math.cos(theta),
          y: r * Math.sin(phi) * Math.sin(theta),
          z: r * Math.cos(phi),
          vx: (Math.random() - 0.5) * 0.002,
          vy: (Math.random() - 0.5) * 0.002,
          vz: (Math.random() - 0.5) * 0.002,
          baseR: r,
          phase: Math.random() * Math.PI * 2,
        });
      }
      particlesRef.current = particles;
    }
  }, []);

  useEffect(() => {
    if (wakePulse) {
      wakePulsesRef.current.push({ start: performance.now() });
    }
  }, [wakePulse]);

  useEffect(() => {
    if (state === 'listening') {
      const interval = setInterval(
        () => {
          ripplesRef.current.push({
            start: performance.now(),
            duration: reducedMotion ? 300 : 1200,
            maxRadius: reducedMotion ? 30 : 70,
          });
        },
        reducedMotion ? 1000 : 800,
      );
      return () => clearInterval(interval);
    }
  }, [state, reducedMotion]);

  useEffect(() => {
    if (state === 'error') {
      ripplesRef.current.push({
        start: performance.now(),
        duration: reducedMotion ? 200 : 600,
        maxRadius: reducedMotion ? 20 : 50,
      });
      setTimeout(() => {
        ripplesRef.current.push({
          start: performance.now(),
          duration: reducedMotion ? 200 : 600,
          maxRadius: reducedMotion ? 20 : 50,
        });
      }, 400);
    }
  }, [state, reducedMotion]);

  useEffect(() => {
    if (state === 'speaking' && rms > 0.01) {
      speakingEchoRef.current = Math.min(1, rms * 2);
      if (speakingEchoTimerRef.current) clearTimeout(speakingEchoTimerRef.current);
      speakingEchoTimerRef.current = setTimeout(() => {
        speakingEchoRef.current = 0;
      }, 3000);
      return () => {
        if (speakingEchoTimerRef.current) clearTimeout(speakingEchoTimerRef.current);
      };
    }
  }, [state, rms]);

  useEffect(() => {
    if (state !== 'speaking') {
      speakingEchoRef.current = 0;
    }
  }, [state]);

  const drawFrame = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = container.getBoundingClientRect();
    const w = rect.width;
    const h = rect.height;
    const cx = w / 2;
    const cy = h / 2;
    const baseRadius = Math.min(w, h) * 0.32;
    const now = performance.now();

    ctx.clearRect(0, 0, w, h);

    const currentState = stateRef.current;
    if (prevStateRef.current !== currentState) {
      transitionRef.current = now;
      prevStateRef.current = currentState;
    }
    const transitionAge = now - transitionRef.current;
    const transitionDuration = reducedMotion ? 0 : 320;
    const t = transitionDuration > 0 ? Math.min(transitionAge / transitionDuration, 1) : 1;
    const ease = t < 1 ? 0.5 - 0.5 * Math.cos(t * Math.PI) : 1;

    const from = STATE_COLORS[prevStateRef.current] || STATE_COLORS['idle'];
    const to = STATE_COLORS[currentState] || STATE_COLORS['idle'];
    const c = {
      core: lerpColor(from.core, to.core, ease),
      glow: lerpColor(from.glow, to.glow, ease),
      particle: lerpColor(from.particle, to.particle, ease),
    };

    const isThinking = currentState === 'thinking';
    const isListening = currentState === 'listening';
    const isSpeaking = currentState === 'speaking';
    const isError = currentState === 'error';
    const isProcessing = currentState === 'processing';
    const isOffline = currentState === 'offline';
    const isWorking = currentState === 'working';

    const breathe = reducedMotion
      ? 1
      : 1 + Math.sin(now * 0.0014) * 0.03 + Math.sin(now * 0.00037) * 0.02;
    const microDrift = reducedMotion
      ? { x: 0, y: 0 }
      : {
          x: Math.sin(now * 0.00026) * 1.5,
          y: Math.cos(now * 0.00032) * 1.2,
        };
    const scale = isPanelOpen ? 0.33 : dragScale * breathe;
    const radius = baseRadius * scale;

    const orbX = cx + microDrift.x;
    const orbY = cy + microDrift.y;

    for (let i = ripplesRef.current.length - 1; i >= 0; i--) {
      const r = ripplesRef.current[i];
      const elapsed = now - r.start;
      const progress = Math.min(elapsed / r.duration, 1);
      const rippleRadius = r.maxRadius * progress * scale;
      const alpha = (1 - progress) * 0.5;
      ctx.beginPath();
      ctx.arc(orbX, orbY, radius + rippleRadius, 0, Math.PI * 2);
      ctx.strokeStyle = isError
        ? `rgba(255,68,102,${alpha})`
        : isProcessing
          ? `rgba(255,176,32,${alpha})`
          : `${c.glow.replace('0.3', String(alpha))}`;
      ctx.lineWidth = 1.5 * (1 - progress);
      ctx.stroke();
      if (progress >= 1) ripplesRef.current.splice(i, 1);
    }

    for (let i = wakePulsesRef.current.length - 1; i >= 0; i--) {
      const wp = wakePulsesRef.current[i];
      const elapsed = now - wp.start;
      const progress = Math.min(elapsed / 800, 1);
      const pulseRadius = radius + 40 * progress * scale;
      const alpha = (1 - progress) * 0.7;
      ctx.beginPath();
      ctx.arc(orbX, orbY, pulseRadius, 0, Math.PI * 2);
      ctx.strokeStyle = `${c.particle.replace(')', `, ${alpha})`)}`;
      ctx.lineWidth = 2 * (1 - progress);
      ctx.stroke();
      if (progress >= 1) wakePulsesRef.current.splice(i, 1);
    }

    if (isThinking) {
      const t = now * 0.001;
      for (let arc = 0; arc < 2; arc++) {
        const dir = arc === 0 ? 1 : -1;
        const speed = arc === 0 ? 2.4 : 3.6;
        const startAngle = t * speed * dir;
        const arcRadius = radius + 8;
        ctx.beginPath();
        ctx.arc(orbX, orbY, arcRadius, startAngle, startAngle + Math.PI * 1.1);
        ctx.strokeStyle = `${c.particle}88`;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }

    if (isError) {
      const t = now * 0.001;
      for (let i = 0; i < 2; i++) {
        const angle = t * 3 + i * Math.PI;
        const arcRadius = radius * 1.15;
        const startAngle = angle;
        ctx.beginPath();
        ctx.arc(orbX, orbY, arcRadius, startAngle, startAngle + Math.PI * 0.6);
        ctx.strokeStyle = '#ff4466';
        ctx.lineWidth = 2.5;
        ctx.lineCap = 'round';
        ctx.stroke();
      }
    }

    const glowGrad = ctx.createRadialGradient(orbX, orbY, radius * 0.2, orbX, orbY, radius * 1.8);
    glowGrad.addColorStop(0, isOffline ? 'rgba(85,85,102,0.15)' : c.glow);
    glowGrad.addColorStop(0.5, isOffline ? 'rgba(85,85,102,0.05)' : `${c.glow}66`);
    glowGrad.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(orbX, orbY, radius * 1.8, 0, Math.PI * 2);
    ctx.fillStyle = glowGrad;
    ctx.fill();

    const coreGrad = ctx.createRadialGradient(orbX, orbY, 0, orbX, orbY, radius);
    coreGrad.addColorStop(0, `${c.core}${isOffline ? '44' : 'cc'}`);
    coreGrad.addColorStop(0.5, `${c.core}${isOffline ? '22' : '66'}`);
    coreGrad.addColorStop(1, `${c.core}${isOffline ? '08' : '11'}`);
    ctx.beginPath();
    ctx.arc(orbX, orbY, radius, 0, Math.PI * 2);
    ctx.fillStyle = coreGrad;
    ctx.fill();

    if (!isOffline) {
      ctx.beginPath();
      ctx.arc(orbX, orbY, radius, 0, Math.PI * 2);
      ctx.strokeStyle = `${c.glow}`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    const particleAlpha = isOffline ? 0.25 : 0.8;
    for (const p of particlesRef.current) {
      const drift = reducedMotion ? 0 : Math.sin(now * 0.001 + p.phase) * 0.02;
      p.x += p.vx + drift;
      p.y += p.vy + drift;
      p.z += p.vz;

      const dist = Math.sqrt(p.x ** 2 + p.y ** 2 + p.z ** 2);
      const targetR = p.baseR * scale * (isListening ? 1.15 : isThinking ? 1.08 : 1);
      if (dist > 0) {
        p.x = (p.x / dist) * targetR;
        p.y = (p.y / dist) * targetR;
        p.z = (p.z / dist) * targetR;
      }

      const px = orbX + p.x * radius;
      const py = orbY + p.y * radius;
      const depth = (p.z + 1) / 2;
      const pAlpha = particleAlpha * (0.3 + depth * 0.7);
      const pSize = (1 + depth) * 1.2;

      if (isThinking && particlesRef.current.indexOf(p) < 6) {
        const thoughtDrift = Math.sin(now * 0.002 + p.phase) * radius * 0.15;
        p.x += thoughtDrift * 0.01;
      }

      ctx.beginPath();
      ctx.arc(px, py, pSize, 0, Math.PI * 2);
      ctx.fillStyle = `${c.particle}${Math.round(pAlpha * 255)
        .toString(16)
        .padStart(2, '0')}`;
      ctx.fill();
    }

    if (isSpeaking) {
      const echoAlpha = speakingEchoRef.current;
      for (let i = 0; i < 8; i++) {
        const angle = (now * 0.003 + (i * Math.PI) / 4) % (Math.PI * 2);
        const dist = radius * (1.1 + Math.sin(now * 0.01 + i) * 0.3);
        const wx = orbX + Math.cos(angle) * dist;
        const wy = orbY + Math.sin(angle) * dist;
        const waveRadius = 3 + echoAlpha * 4;
        ctx.beginPath();
        ctx.arc(wx, wy, waveRadius, 0, Math.PI * 2);
        ctx.fillStyle = `${c.particle}${Math.round(echoAlpha * 180)
          .toString(16)
          .padStart(2, '0')}`;
        ctx.fill();
      }
    }

    if (isProcessing) {
      const t = now * 0.001;
      const pulsePhase = (t % 3) / 3;
      const pulseAlpha = (1 - pulsePhase) * 0.4;
      ctx.beginPath();
      ctx.arc(orbX, orbY, radius * (1.05 + pulsePhase * 0.2), 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(255,176,32,${pulseAlpha})`;
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    if (isWorking) {
      const t = now * 0.001;
      const arcCount = 3;
      for (let i = 0; i < arcCount; i++) {
        const startAngle = t * 2.5 + (i * Math.PI * 2) / arcCount;
        const arcRadius = radius * 1.12;
        ctx.beginPath();
        ctx.arc(orbX, orbY, arcRadius, startAngle, startAngle + Math.PI * 0.7);
        ctx.strokeStyle = `rgba(255,176,32,${0.25 + Math.sin(t * 3 + i) * 0.15})`;
        ctx.lineWidth = 2;
        ctx.lineCap = 'round';
        ctx.stroke();
      }
    }

    if (isNotification) {
      const pulseScale = 1.1 + Math.sin(now * 0.004) * 0.05;
      const notifRadius = radius * pulseScale;
      const notifGrad = ctx.createRadialGradient(orbX, orbY, radius * 0.8, orbX, orbY, notifRadius);
      notifGrad.addColorStop(0, `${c.core}44`);
      notifGrad.addColorStop(1, `${c.core}11`);
      ctx.beginPath();
      ctx.arc(orbX, orbY, notifRadius, 0, Math.PI * 2);
      ctx.fillStyle = notifGrad;
      ctx.fill();

      const badgeX = orbX + radius * 0.7;
      const badgeY = orbY - radius * 0.7;
      ctx.beginPath();
      ctx.arc(badgeX, badgeY, 6, 0, Math.PI * 2);
      ctx.fillStyle = '#ff4466';
      ctx.fill();
    }

    animFrameRef.current = requestAnimationFrame(drawFrame);
  }, [reducedMotion, dragScale]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(drawFrame);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [drawFrame]);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (isDraggingRef.current) return;
      if (isPanelOpen) {
        onClick?.();
        return;
      }
      onSingleClick?.();
    },
    [isPanelOpen, onClick, onSingleClick],
  );

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (isDraggingRef.current) return;
      onExpandPanel?.();
    },
    [isDraggingRef, onExpandPanel],
  );

  const handleQuickAction = useCallback(
    (action: 'talk' | 'chat' | 'settings') => {
      onQuickAction?.(action);
    },
    [onQuickAction],
  );

  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      const startX = e.clientX;
      const startY = e.clientY;
      let moved = false;

      const onMove = (moveEvent: MouseEvent) => {
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
          moved = true;
          isDraggingRef.current = true;
          setIsDragging(true);
          setDragScale(1.15);
        }
        if (moved) onDragMove?.(dx, dy);
      };

      const onUp = () => {
        window.removeEventListener('mousemove', onMove);
        window.removeEventListener('mouseup', onUp);
        if (moved) onDragEnd?.();
        isDraggingRef.current = false;
        setIsDragging(false);
        setTimeout(
          () => {
            setDragScale(1);
          },
          reducedMotion ? 80 : 400,
        );
      };

      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
    },
    [reducedMotion, onDragMove, onDragEnd],
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        onExpandPanel?.();
      }
      if (e.key === ' ') {
        e.preventDefault();
        onToggleTalk?.();
      }
      if (e.key === 'Escape') {
        onCloseQuickActions?.();
      }
    },
    [onExpandPanel, onToggleTalk, onCloseQuickActions],
  );

  const stateLabel = useMemo(() => {
    const labels: Record<OrbState, string> = {
      idle: 'JARVIS is idle',
      listening: 'Listening...',
      thinking: 'Thinking...',
      speaking: 'Speaking...',
      processing: 'Processing...',
      notification: 'New notification',
      offline: 'Offline',
      error: 'Connection error',
      working: 'Working...',
      'panel-open': 'Panel open',
    };
    return labels[state] || 'JARVIS';
  }, [state]);

  const size = isPanelOpen ? 'var(--orb-size-small)' : 'var(--orb-size)';

  return (
    <div
      ref={containerRef}
      className={`orb-engine ${isHovered ? 'hovered' : ''} ${isPanelOpen ? 'panel-open' : ''} orb-state-${state}`}
      style={{
        width: size,
        height: size,
        cursor: onToggleTalk ? 'pointer' : 'default',
        transform: isPanelOpen ? undefined : `scale(${dragScale})`,
        transition: isDragging
          ? 'none'
          : reducedMotion
            ? 'transform 80ms ease'
            : 'transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1)',
        ...style,
      }}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onMouseDown={handleDragStart}
      onContextMenu={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onContextMenu?.();
      }}
      onMouseEnter={() => {
        setIsHovered(true);
        setTooltip(stateLabel);
      }}
      onMouseLeave={() => {
        setIsHovered(false);
        setTooltip(null);
      }}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-label={stateLabel}
      aria-pressed={state === 'listening'}
      title={stateLabel}
    >
      <canvas ref={canvasRef} className="orb-canvas" aria-hidden="true" />
      <div className="orb-core-glow" aria-hidden="true" />

      {isNotification && <div className="orb-badge" aria-label="Notification" />}

      {quickActionsOpen && onQuickAction && (
        <div className="orb-quick-actions" role="menu" aria-label="Quick actions">
          {QUICK_ACTIONS.map((action) => {
            const angleRad = (action.angle * Math.PI) / 180;
            const dist = 55;
            const x = Math.cos(angleRad) * dist;
            const y = Math.sin(angleRad) * dist;
            return (
              <button
                key={action.id}
                className="orb-quick-action"
                style={{
                  transform: `translate(${x}px, ${y}px)`,
                  transition: reducedMotion
                    ? 'transform 80ms ease'
                    : 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  handleQuickAction(action.id);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleQuickAction(action.id);
                }}
                role="menuitem"
                aria-label={action.label}
                title={action.label}
              >
                <span className="quick-action-icon" aria-hidden="true">
                  {action.icon}
                </span>
                <span className="quick-action-label">{action.label}</span>
              </button>
            );
          })}
        </div>
      )}

      {tooltip && !quickActionsOpen && (
        <div className="orb-tooltip" role="tooltip" aria-hidden={!tooltip}>
          {tooltip}
        </div>
      )}
    </div>
  );
};

export { STATE_COLORS };
export default OrbEngine;
