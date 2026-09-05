import type { CSSProperties } from 'react';
import type { OrbState } from '../orb/OrbEngine';
import './MinimalBubble.css';

type MinimalBubbleProps = {
  state?: OrbState;
  audioLevel?: number;
  onToggle?: () => void;
};

export default function MinimalBubble({
  state = 'idle',
  audioLevel = 0,
  onToggle,
}: MinimalBubbleProps) {
  const normalizedLevel = Math.max(0, Math.min(1, audioLevel));

  const handleClick = () => {
    if (onToggle) {
      onToggle();
      return;
    }
    window.electronAPI?.toggleMainWindow?.();
  };

  return (
    <div
      className={`minimal-bubble minimal-bubble-${state}`}
      style={{ '--bubble-audio-level': normalizedLevel } as CSSProperties}
      aria-label="JARVIS"
    >
      <svg className="minimal-bubble-svg" viewBox="0 0 72 72" aria-hidden="true">
        {/* Live audio-level halo: scales with real mic/playback frames only. */}
        <circle className="minimal-bubble-halo" cx="36" cy="36" r="30" />
        <circle className="minimal-bubble-circle" cx="36" cy="36" r="35" />
      </svg>
      <button
        className="minimal-bubble-button"
        type="button"
        onClick={handleClick}
        aria-label="Open JARVIS"
      >
        <span className="minimal-bubble-text">JARVIS</span>
      </button>
    </div>
  );
}
