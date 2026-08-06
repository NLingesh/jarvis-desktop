import React, { useState, useEffect, useRef, useCallback } from 'react';
import VoiceOrb from './components/VoiceOrb';
import './bubble.css';

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking';

const WAKE_CONFIDENCE_THRESHOLD = 0.5;
const WAKE_COOLDOWN_MS = 2000;

function BubbleApp() {
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const wakeRecognitionRef = useRef<any>(null);
  const isListeningRef = useRef(false);
  const lastWakeTriggerRef = useRef(0);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);

  const playConfirmationChime = useCallback(() => {
    try {
      const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;
      const playTone = (start: number, freq: number, duration: number) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, start);
        gain.gain.setValueAtTime(0.0001, start);
        gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
        osc.connect(gain).connect(ctx.destination);
        osc.start(start);
        osc.stop(start + duration + 0.05);
      };
      playTone(now, 880, 0.12);
      playTone(now + 0.15, 1320, 0.18);
      setTimeout(() => {
        ctx.close().catch(() => {});
      }, 800);
    } catch (e) {
      console.warn('Confirmation chime failed', e);
    }
  }, []);

  const ensureMicPermission = useCallback(async (): Promise<boolean> => {
    try {
      if (navigator.permissions && (navigator.permissions as any).query) {
        try {
          const result = await (navigator.permissions as any).query({ name: 'microphone' });
          if (result.state === 'granted') {
            return true;
          }
        } catch (permErr) {
          console.warn('Permissions API query failed', permErr);
        }
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      return true;
    } catch (err) {
      console.warn('Microphone access denied for bubble');
      return false;
    }
  }, []);

  const handleWakeWordDetected = useCallback(async () => {
    setOrbState('listening');
    isListeningRef.current = true;

    if (navigator.vibrate) {
      navigator.vibrate(50);
    }

    const api = (window as any).electronAPI;
    if (api?.notifyWakeWordDetected) {
      try {
        await api.notifyWakeWordDetected();
      } catch (e) {
        console.warn('Failed to notify main process of wake word', e);
      }
    }

    setTimeout(() => {
      setOrbState('idle');
      isListeningRef.current = false;
    }, 1500);
  }, []);

  const startWakeWordListener = useCallback(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition || wakeRecognitionRef.current) {
      return;
    }
    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onresult = (event: any) => {
        let transcript = '';
        let bestConfidence: number | null = null;
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const top = event.results[i][0];
          if (top) {
            transcript += top.transcript;
            if (typeof top.confidence === 'number') {
              bestConfidence =
                bestConfidence === null ? top.confidence : Math.max(bestConfidence, top.confidence);
            }
          }
        }
        const normalized = transcript.toLowerCase();
        if (!normalized.includes('jarvis')) {
          return;
        }

        if (bestConfidence !== null && bestConfidence < WAKE_CONFIDENCE_THRESHOLD) {
          console.warn(
            `Wake word ignored: confidence ${bestConfidence} below threshold ${WAKE_CONFIDENCE_THRESHOLD}`,
          );
          return;
        }

        const now = Date.now();
        if (now - lastWakeTriggerRef.current < WAKE_COOLDOWN_MS) {
          console.warn('Wake word ignored: cooldown active');
          return;
        }
        lastWakeTriggerRef.current = now;

        playConfirmationChime();
        recognition.stop();
        handleWakeWordDetected();
      };

      recognition.onerror = (event: any) => {
        console.warn('Wake-word recognition error:', event.error);
      };

      recognition.onend = () => {
        if (isListeningRef.current) {
          try {
            recognition.start();
          } catch (e) {
            console.warn('Failed to restart wake-word listener', e);
          }
        }
      };

      recognition.start();
      wakeRecognitionRef.current = recognition;
    } catch (err) {
      console.warn('Wake-word listener failed to start', err);
    }
  }, [handleWakeWordDetected, playConfirmationChime]);

  const stopWakeWordListener = useCallback(() => {
    if (wakeRecognitionRef.current) {
      try {
        wakeRecognitionRef.current.onresult = null;
        wakeRecognitionRef.current.onend = null;
        wakeRecognitionRef.current.onerror = null;
        wakeRecognitionRef.current.stop();
      } catch (err) {
        console.warn('Failed to stop wake-word listener', err);
      }
      wakeRecognitionRef.current = null;
    }
  }, []);

  useEffect(() => {
    ensureMicPermission().then((granted) => {
      if (granted) {
        startWakeWordListener();
      }
    });
    return () => stopWakeWordListener();
  }, [ensureMicPermission, startWakeWordListener, stopWakeWordListener]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onMainWindowVisibility) {
      return undefined;
    }
    const unsubscribe = api.onMainWindowVisibility((visible: boolean) => {
      if (visible) {
        // Release the mic while the main window may be capturing audio.
        stopWakeWordListener();
      } else {
        startWakeWordListener();
      }
    });
    return () => {
      if (typeof unsubscribe === 'function') {
        unsubscribe();
      }
    };
  }, [startWakeWordListener, stopWakeWordListener]);

  const handleMouseDown = (e: React.MouseEvent) => {
    dragStartRef.current = { x: e.clientX, y: e.clientY };
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (!dragStartRef.current) return;
    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    dragStartRef.current = null;

    if (dist < 3) {
      const api = (window as any).electronAPI;
      if (api?.toggleMainWindow) {
        api.toggleMainWindow();
      }
    }
  };

  const handleMouseLeave = () => {
    dragStartRef.current = null;
  };

  return (
    <div
      className="bubble-container"
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      role="button"
      tabIndex={0}
      aria-label="JARVIS voice assistant bubble"
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          const api = (window as any).electronAPI;
          if (api?.toggleMainWindow) {
            api.toggleMainWindow();
          }
        }
      }}
    >
      <VoiceOrb state={orbState} analysers={[]} />
    </div>
  );
}

export default BubbleApp;
