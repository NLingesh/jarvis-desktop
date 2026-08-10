import { useEffect, useRef, useState } from 'react';

export interface PanelChoreographyState {
  isOpen: boolean;
  isAnimating: boolean;
  phase: 'idle' | 'expanding' | 'collapsing';
}

const EXPAND_MS = 220;
const COLLAPSE_MS = 180;

export function usePanelChoreography(open: boolean, orbPosition: { x: number; y: number }) {
  const [state, setState] = useState<PanelChoreographyState>({
    isOpen: open,
    isAnimating: false,
    phase: 'idle',
  });

  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = undefined;
    }

    if (open && !state.isOpen) {
      setState({ isOpen: true, isAnimating: true, phase: 'expanding' });
      timeoutRef.current = setTimeout(() => {
        setState((prev) => ({ ...prev, isAnimating: false, phase: 'idle' }));
      }, EXPAND_MS);
    } else if (!open && state.isOpen) {
      setState({ isOpen: true, isAnimating: true, phase: 'collapsing' });
      timeoutRef.current = setTimeout(() => {
        setState((prev) => ({ ...prev, isOpen: false, isAnimating: false, phase: 'idle' }));
      }, COLLAPSE_MS);
    }

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [open]);

  const position = useRef({ x: orbPosition.x - 190, y: orbPosition.y - 520 });

  useEffect(() => {
    position.current = {
      x: Math.min(Math.max(orbPosition.x - 190, 10), window.innerWidth - 400),
      y: Math.max(orbPosition.y - 520, 10),
    };
  }, [orbPosition]);

  return {
    state,
    position: position.current,
  };
}
