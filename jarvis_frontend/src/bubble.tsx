import React, { useState, useEffect, useRef, useCallback } from 'react';
import VoiceOrb from './components/VoiceOrb';
import './bubble.css';

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking';

function BubbleApp() {
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const wakeRecognitionRef = useRef<any>(null);
  const isListeningRef = useRef(false);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);

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
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
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
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        const normalized = transcript.toLowerCase();
        if (normalized.includes('jarvis')) {
          recognition.stop();
          handleWakeWordDetected();
        }
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
  }, [handleWakeWordDetected]);

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
    >
      <VoiceOrb state={orbState} analysers={[]} />
    </div>
  );
}

export default BubbleApp;
