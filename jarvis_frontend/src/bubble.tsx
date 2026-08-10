import React, { useState, useEffect, useRef, useCallback } from 'react';
import VoiceOrb from './components/VoiceOrb';
import { computeRms, uint8ToBase64 } from './audioStream';
import { describeMicError, logVoice } from './voiceDiagnostics';
import { useAutonomousBehaviors } from './orb/useAutonomousBehaviors';
import './bubble.css';

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'offline';
const DEFAULT_WAKE_WORD = 'computer';
const WAKE_COOLDOWN_MS = 2000;
const WAKE_PING_INTERVAL_MS = 25000;
const ENDPOINT_RMS_THRESHOLD = 500;
const ENDPOINT_SILENCE_MS = 900;
const CAPTURE_TIMEOUT_MS = 15000;
const REPLY_GRACE_TIMEOUT_MS = 60000;

function BubbleApp() {
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [pttActive, setPttActive] = useState(false);
  const [isPanelOpen, _setIsPanelOpen] = useState(false);
  const [, setWakePulse] = useState(false);
  const [replyText, setReplyText] = useState('');
  const wakeWsRef = useRef<WebSocket | null>(null);
  const wakeStreamRef = useRef<MediaStream | null>(null);
  const wakeCtxRef = useRef<AudioContext | null>(null);
  const wakeSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const wakeWorkletRef = useRef<AudioWorkletNode | null>(null);
  const wakePingRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const stopRequestedRef = useRef(false);
  const wakeStartingRef = useRef(false);
  const isListeningRef = useRef(false);
  const lastWakeTriggerRef = useRef(0);
  const dragStartRef = useRef<{ x: number; y: number } | null>(null);
  const pttWsRef = useRef<WebSocket | null>(null);
  const pttStreamRef = useRef<MediaStream | null>(null);
  const pttCtxRef = useRef<AudioContext | null>(null);
  const pttWorkletRef = useRef<AudioWorkletNode | null>(null);
  const pttSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const pttFlushResolveRef = useRef<(() => void) | null>(null);
  const pttRecordingTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pttReplyTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingAudioRef = useRef(false);
  const audioChunksRef = useRef<string[]>([]);
  const pendingSegmentsRef = useRef(0);
  const captureFlushResolveRef = useRef<(() => void) | null>(null);
  const captureTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const captureStartRef = useRef(0);
  const speechDetectedRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);
  const voiceSettingsRef = useRef<{
    enableWakeWord: boolean;
    alwaysOnListening: boolean;
    wakeWord: string;
  }>({
    enableWakeWord: true,
    alwaysOnListening: false,
    wakeWord: DEFAULT_WAKE_WORD,
  });

  // Refs break the circular dependency between the wake-word / command-capture
  // callbacks (startWakeWordListener -> handleWakeWordDetected ->
  // beginCommandCapture -> startWakeWordListener).
  const beginMicStreamRef = useRef<(ws: WebSocket) => Promise<void>>(async () => {});
  const beginCommandCaptureRef = useRef<(ws: WebSocket) => Promise<void>>(async () => {});
  const handleWakeWordDetectedRef = useRef<() => Promise<void>>(async () => {});
  const startWakeWordListenerRef = useRef<() => Promise<void>>(async () => {});

  const {
    state: autonomousState,
    recordActivity,
    dismissWhisper,
  } = useAutonomousBehaviors(
    isPanelOpen,
    orbState === 'listening' || orbState === 'speaking',
    false,
  );

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
      setTimeout(() => ctx.close().catch(() => {}), 800);
    } catch {
      /* ignore */
    }
  }, []);

  // ---------------------------------------------------------------------------
  // TTS playback queue
  // ---------------------------------------------------------------------------
  const playNextAudio = useCallback(() => {
    if (isPlayingAudioRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) {
      setOrbState('idle');
      return;
    }
    isPlayingAudioRef.current = true;
    setOrbState('speaking');
    try {
      const audioData = Uint8Array.from(atob(next), (c) => c.charCodeAt(0));
      const isWav =
        audioData.byteLength > 4 &&
        String.fromCharCode(audioData[0], audioData[1], audioData[2], audioData[3]) === 'RIFF';
      const blob = new Blob([audioData], { type: isWav ? 'audio/wav' : 'audio/mpeg' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        isPlayingAudioRef.current = false;
        playNextAudio();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        isPlayingAudioRef.current = false;
        playNextAudio();
      };
      audio.play().catch(() => {
        URL.revokeObjectURL(url);
        isPlayingAudioRef.current = false;
        playNextAudio();
      });
    } catch {
      isPlayingAudioRef.current = false;
      playNextAudio();
    }
  }, []);

  const enqueueAudio = useCallback(
    (audioBase64: string) => {
      audioQueueRef.current.push(audioBase64);
      playNextAudio();
    },
    [playNextAudio],
  );

  const reloadVoiceSettings = useCallback(() => {
    const stored = localStorage.getItem('voiceSettings');
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        voiceSettingsRef.current = {
          enableWakeWord: parsed.enableWakeWord ?? true,
          alwaysOnListening: parsed.alwaysOnListening ?? false,
          wakeWord: parsed.wakeWord ?? DEFAULT_WAKE_WORD,
        };
      } catch {
        // ignore
      }
    }
  }, []);

  const ensureMicPermission = useCallback(async (): Promise<boolean> => {
    try {
      if (navigator.permissions && (navigator.permissions as any).query) {
        try {
          const result = await (navigator.permissions as any).query({ name: 'microphone' });
          if (result.state === 'granted') return true;
        } catch {
          /* ignore */
        }
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      return true;
    } catch (err) {
      logVoice('mic_probing', { level: 'warn', error: describeMicError(err) });
      return false;
    }
  }, []);

  const teardownWakeMic = useCallback(() => {
    if (wakeWorkletRef.current) {
      wakeWorkletRef.current.port.onmessage = null;
      try {
        wakeWorkletRef.current.disconnect();
      } catch {
        /* ignore */
      }
      wakeWorkletRef.current = null;
    }
    if (wakeSourceRef.current) {
      try {
        wakeSourceRef.current.disconnect();
      } catch {
        /* ignore */
      }
      wakeSourceRef.current = null;
    }
    if (wakeStreamRef.current) {
      wakeStreamRef.current.getTracks().forEach((track) => track.stop());
      wakeStreamRef.current = null;
    }
    if (wakeCtxRef.current && wakeCtxRef.current.state !== 'closed') {
      wakeCtxRef.current.close().catch(() => {});
      wakeCtxRef.current = null;
    }
  }, []);

  const stopWakeWordListener = useCallback(() => {
    stopRequestedRef.current = true;
    wakeStartingRef.current = false;
    if (wakePingRef.current) {
      clearInterval(wakePingRef.current);
      wakePingRef.current = undefined;
    }
    if (captureTimerRef.current) {
      clearTimeout(captureTimerRef.current);
      captureTimerRef.current = undefined;
    }
    const ws = wakeWsRef.current;
    wakeWsRef.current = null;
    if (ws) {
      try {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'wake_stop' }));
        ws.close();
      } catch {
        /* ignore */
      }
    }
    teardownWakeMic();
  }, [teardownWakeMic]);

  const buildWsUrl = useCallback(async (): Promise<string> => {
    const api = (window as any).electronAPI;
    const token = api?.getSessionToken ? await api.getSessionToken() : null;
    const server = (localStorage.getItem('serverUrl') || '').trim() || 'localhost:8000';
    const trimmed = server.replace(/\/*$/, '');
    let url: string;
    if (trimmed.startsWith('ws://') || trimmed.startsWith('wss://')) {
      url = `${trimmed}/ws/voice`;
    } else if (trimmed.startsWith('http://')) {
      url = `ws://${trimmed.slice(7)}/ws/voice`;
    } else if (trimmed.startsWith('https://')) {
      url = `wss://${trimmed.slice(8)}/ws/voice`;
    } else {
      url = `ws://${trimmed}/ws/voice`;
    }
    if (token) url += `?token=${encodeURIComponent(token)}`;
    return url;
  }, []);

  // ---------------------------------------------------------------------------
  // Endpointing (silence-based auto-stop) for hands-free command capture.
  // ---------------------------------------------------------------------------
  const checkEndpointing = useCallback((pcm: Uint8Array) => {
    if (!pcm || pcm.byteLength === 0) return;
    const rms = computeRms(pcm);
    if (rms > ENDPOINT_RMS_THRESHOLD) {
      speechDetectedRef.current = true;
      silenceStartRef.current = null;
      return;
    }
    if (!speechDetectedRef.current) return;
    if (Date.now() - captureStartRef.current < 1200) return;
    if (silenceStartRef.current === null) {
      silenceStartRef.current = Date.now();
      return;
    }
    if (Date.now() - silenceStartRef.current >= ENDPOINT_SILENCE_MS) {
      silenceStartRef.current = null;
      logVoice('endpoint', { level: 'debug', rms });
      if (wakeWorkletRef.current) void stopCommandCapture();
    }
  }, []);

  const setWorkletHandler = useCallback(
    (
      worklet: AudioWorkletNode,
      ws: WebSocket,
      msgType: 'wake_chunk' | 'audio_chunk',
      endpointing: boolean,
    ) => {
      worklet.port.onmessage = (event) => {
        if (wakeWsRef.current !== ws && pttWsRef.current !== ws) return;
        if (!event.data || event.data.type !== 'pcm') return;
        const bytes = event.data.pcm as ArrayBuffer;
        if (bytes && bytes.byteLength > 0) {
          try {
            ws.send(
              JSON.stringify({
                type: msgType,
                data: uint8ToBase64(new Uint8Array(bytes)),
              }),
            );
          } catch {
            /* ignore */
          }
        }
        if (event.data.final) {
          const resolve = captureFlushResolveRef.current;
          captureFlushResolveRef.current = null;
          if (resolve) resolve();
          return;
        }
        if (msgType === 'audio_chunk' && endpointing) {
          checkEndpointing(new Uint8Array(bytes));
        }
      };
    },
    [checkEndpointing],
  );

  // ---------------------------------------------------------------------------
  // Voice reply handler — drives orb state, renders the text reply, plays TTS.
  // ---------------------------------------------------------------------------
  const attachVoiceHandler = useCallback(
    (ws: WebSocket, onReplyDone?: (socket: WebSocket) => void) => {
      ws.onmessage = (event) => {
        if (wakeWsRef.current !== ws && pttWsRef.current !== ws) return;
        let data: any;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }
        switch (data.type) {
          case 'status':
            if (data.status === 'processing') setOrbState('thinking');
            else if (data.status === 'generating_speech') setOrbState('speaking');
            break;
          case 'transcript':
            setReplyText(data.text);
            break;
          case 'partial':
            setReplyText(data.text);
            break;
          case 'response':
            setReplyText(data.text);
            if (data.audio) enqueueAudio(data.audio);
            if (onReplyDone) {
              setTimeout(() => onReplyDone(ws), 1500);
            }
            break;
          case 'audio_queue':
            pendingSegmentsRef.current = data.count ?? 0;
            setOrbState('speaking');
            break;
          case 'audio_segment_start':
            audioChunksRef.current = [];
            break;
          case 'audio_chunk':
            if (data.chunk) audioChunksRef.current.push(data.chunk);
            break;
          case 'audio_segment_end': {
            const combined = audioChunksRef.current.join('');
            audioChunksRef.current = [];
            if (combined) {
              enqueueAudio(combined);
            } else if (
              audioQueueRef.current.length === 0 &&
              !isPlayingAudioRef.current &&
              pendingSegmentsRef.current <= 1
            ) {
              setOrbState('idle');
            }
            if (pendingSegmentsRef.current > 0) {
              pendingSegmentsRef.current -= 1;
            }
            break;
          }
          case 'error':
            setReplyText(data.message || '');
            setOrbState('idle');
            break;
          default:
            break;
        }
      };
    },
    [enqueueAudio],
  );

  // ---------------------------------------------------------------------------
  // Hands-free command capture (after wake word) on the wake WebSocket.
  // ---------------------------------------------------------------------------
  const stopCommandCapture = useCallback(async () => {
    const ws = wakeWsRef.current;
    const worklet = wakeWorkletRef.current;
    if (captureTimerRef.current) {
      clearTimeout(captureTimerRef.current);
      captureTimerRef.current = undefined;
    }
    isListeningRef.current = false;
    setOrbState('thinking');
    try {
      if (worklet) {
        await new Promise<void>((resolve) => {
          captureFlushResolveRef.current = resolve;
          worklet.port.postMessage({ type: 'flush' });
          setTimeout(() => {
            if (captureFlushResolveRef.current) {
              captureFlushResolveRef.current = null;
              resolve();
            }
          }, 500);
        });
      }
    } catch {
      /* ignore */
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'audio_end' }));
      } catch {
        /* ignore */
      }
    }
  }, []);

  const beginCommandCapture = useCallback(
    async (ws: WebSocket) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (wakePingRef.current) {
        clearInterval(wakePingRef.current);
        wakePingRef.current = undefined;
      }
      try {
        ws.send(JSON.stringify({ type: 'wake_stop' }));
      } catch {
        /* ignore */
      }
      attachVoiceHandler(ws, () => {
        stopWakeWordListener();
        if (voiceSettingsRef.current.enableWakeWord) void startWakeWordListenerRef.current();
      });
      if (!wakeWorkletRef.current) {
        await beginMicStreamRef.current(ws);
      }
      if (wakeWorkletRef.current) {
        setWorkletHandler(wakeWorkletRef.current, ws, 'audio_chunk', true);
      }
      try {
        ws.send(
          JSON.stringify({ type: 'audio_start', format: 'pcm16', sample_rate: 16000, channels: 1 }),
        );
      } catch {
        /* ignore */
      }
      captureStartRef.current = Date.now();
      speechDetectedRef.current = false;
      silenceStartRef.current = null;
      isListeningRef.current = true;
      setOrbState('listening');
      setReplyText('');
      if (captureTimerRef.current) clearTimeout(captureTimerRef.current);
      captureTimerRef.current = setTimeout(() => {
        if (wakeWorkletRef.current) void stopCommandCapture();
      }, CAPTURE_TIMEOUT_MS);
    },
    [attachVoiceHandler, setWorkletHandler, stopCommandCapture, stopWakeWordListener],
  );

  const handleWakeWordDetected = useCallback(async () => {
    const ws = wakeWsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      setWakePulse(true);
      setTimeout(() => setWakePulse(false), 800);
      if (navigator.vibrate) navigator.vibrate(50);
      playConfirmationChime();
      const api = (window as any).electronAPI;
      if (api?.notifyWakeWordDetected) {
        try {
          await api.notifyWakeWordDetected();
        } catch {
          /* ignore */
        }
      }
      await beginCommandCaptureRef.current(ws);
    } else {
      setOrbState('idle');
    }
  }, [playConfirmationChime]);

  // ---------------------------------------------------------------------------
  // PTT capture (bubble "Talk" button).
  // ---------------------------------------------------------------------------
  const closePttWs = useCallback((ws: WebSocket) => {
    if (pttWsRef.current === ws) {
      try {
        ws.close();
      } catch {
        /* ignore */
      }
      pttWsRef.current = null;
    }
  }, []);

  const beginPttStream = useCallback(async () => {
    if (pttWsRef.current) return;
    try {
      const ws = new WebSocket(await buildWsUrl());
      pttWsRef.current = ws;

      ws.onopen = () => {
        if (pttWsRef.current !== ws) {
          ws.close();
          return;
        }
        ws.send(
          JSON.stringify({ type: 'audio_start', format: 'pcm16', sample_rate: 16000, channels: 1 }),
        );
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      };

      attachVoiceHandler(ws, () => closePttWs(ws));

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      pttStreamRef.current = stream;

      let ctx = pttCtxRef.current;
      if (!ctx || ctx.state === 'closed') {
        ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        pttCtxRef.current = ctx;
      }
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      await ctx.audioWorklet.addModule('/pcmWorklet.js');
      const source = ctx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(ctx, 'pcm16-capture', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        processorOptions: { sampleRate: ctx.sampleRate },
      });
      const zeroGain = ctx.createGain();
      zeroGain.gain.value = 0;
      source.connect(worklet);
      worklet.connect(zeroGain);
      zeroGain.connect(ctx.destination);

      setWorkletHandler(worklet, ws, 'audio_chunk', false);

      pttSourceRef.current = source;
      pttWorkletRef.current = worklet;
      pttRecordingTimerRef.current = setTimeout(() => {
        if (pttWorkletRef.current) void stopPttStream();
      }, 30000);
    } catch (err) {
      console.warn('PTT stream failed', err);
      void stopPttStream();
    }
  }, [attachVoiceHandler, buildWsUrl, closePttWs, setWorkletHandler]);

  const stopPttStream = useCallback(async () => {
    const ws = pttWsRef.current;
    const stream = pttStreamRef.current;
    const worklet = pttWorkletRef.current;

    if (pttRecordingTimerRef.current) {
      clearTimeout(pttRecordingTimerRef.current);
      pttRecordingTimerRef.current = undefined;
    }

    if (!worklet && !stream) {
      if (pttReplyTimerRef.current) {
        clearTimeout(pttReplyTimerRef.current);
        pttReplyTimerRef.current = undefined;
      }
      setOrbState('idle');
      setPttActive(false);
      return;
    }

    try {
      if (worklet) {
        await new Promise<void>((resolve) => {
          pttFlushResolveRef.current = resolve;
          worklet.port.postMessage({ type: 'flush' });
          setTimeout(() => {
            if (pttFlushResolveRef.current) {
              pttFlushResolveRef.current = null;
              resolve();
            }
          }, 500);
        });
      }
    } catch {
      /* ignore */
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: 'audio_end' }));
      } catch {
        /* ignore */
      }
    }

    if (worklet) {
      worklet.port.onmessage = null;
      try {
        worklet.disconnect();
      } catch {
        /* ignore */
      }
      pttWorkletRef.current = null;
    }
    if (pttSourceRef.current) {
      try {
        pttSourceRef.current.disconnect();
      } catch {
        /* ignore */
      }
      pttSourceRef.current = null;
    }
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      pttStreamRef.current = null;
    }
    if (pttCtxRef.current && pttCtxRef.current.state !== 'closed') {
      pttCtxRef.current.close().catch(() => {});
      pttCtxRef.current = null;
    }

    // Keep the socket open so the reply + TTS can arrive; close it after a
    // grace period in case the backend never responds.
    if (ws) {
      if (pttReplyTimerRef.current) clearTimeout(pttReplyTimerRef.current);
      pttReplyTimerRef.current = setTimeout(() => closePttWs(ws), REPLY_GRACE_TIMEOUT_MS);
    }

    setOrbState('thinking');
    setPttActive(false);
  }, [closePttWs]);

  const beginMicStream = useCallback(
    async (ws: WebSocket) => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        if (stopRequestedRef.current || wakeWsRef.current !== ws) {
          stream.getTracks().forEach((track: MediaStreamTrack) => track.stop());
          return;
        }
        wakeStreamRef.current = stream;

        let ctx = wakeCtxRef.current;
        if (!ctx) {
          ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
          wakeCtxRef.current = ctx;
        }
        if (ctx.state === 'suspended') {
          ctx.resume().catch(() => {});
        }

        await ctx.audioWorklet.addModule('/pcmWorklet.js');

        const source = ctx.createMediaStreamSource(stream);
        const worklet = new AudioWorkletNode(ctx, 'pcm16-capture', {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          processorOptions: { sampleRate: ctx.sampleRate },
        });
        const zeroGain = ctx.createGain();
        zeroGain.gain.value = 0;
        source.connect(worklet);
        worklet.connect(zeroGain);
        zeroGain.connect(ctx.destination);

        setWorkletHandler(worklet, ws, 'wake_chunk', false);

        wakeSourceRef.current = source;
        wakeWorkletRef.current = worklet;
      } catch (err) {
        console.warn('Wake-word mic stream failed', err);
        if (wakeWsRef.current === ws) {
          stopWakeWordListener();
        }
      }
    },
    [setWorkletHandler, stopWakeWordListener],
  );

  const startWakeWordListener = useCallback(async () => {
    if (!voiceSettingsRef.current.enableWakeWord) return;
    if (wakeWsRef.current || wakeStartingRef.current) return;
    wakeStartingRef.current = true;
    stopRequestedRef.current = false;
    try {
      const granted = await ensureMicPermission();
      if (!granted || stopRequestedRef.current) return;

      const ws = new WebSocket(await buildWsUrl());
      wakeWsRef.current = ws;

      ws.onopen = () => {
        if (stopRequestedRef.current || wakeWsRef.current !== ws) {
          ws.close();
          return;
        }
        const phrase = voiceSettingsRef.current.wakeWord || DEFAULT_WAKE_WORD;
        ws.send(JSON.stringify({ type: 'wake_start', phrase, sample_rate: 16000 }));
        if (wakePingRef.current) clearInterval(wakePingRef.current);
        wakePingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            try {
              ws.send(JSON.stringify({ type: 'ping' }));
            } catch {
              /* ignore */
            }
          }
        }, WAKE_PING_INTERVAL_MS);
        void beginMicStreamRef.current(ws);
      };

      ws.onmessage = (event) => {
        if (wakeWsRef.current !== ws) return;
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'wake_word') {
            const now = Date.now();
            if (now - lastWakeTriggerRef.current < WAKE_COOLDOWN_MS) return;
            lastWakeTriggerRef.current = now;
            void handleWakeWordDetectedRef.current();
          }
        } catch {
          /* ignore */
        }
      };

      ws.onclose = () => {
        if (wakeWsRef.current === ws) {
          wakeWsRef.current = null;
          if (wakePingRef.current) {
            clearInterval(wakePingRef.current);
            wakePingRef.current = undefined;
          }
        }
      };

      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      };
    } catch (err) {
      console.warn('Wake-word listener failed to start', err);
      teardownWakeMic();
    } finally {
      wakeStartingRef.current = false;
    }
  }, [buildWsUrl, ensureMicPermission, teardownWakeMic]);

  // Assign the circular callbacks so the event handlers above resolve them.
  beginMicStreamRef.current = beginMicStream;
  beginCommandCaptureRef.current = beginCommandCapture;
  handleWakeWordDetectedRef.current = handleWakeWordDetected;
  startWakeWordListenerRef.current = startWakeWordListener;

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
      api?.toggleMainWindow?.();
      recordActivity();
    }
  };

  const handleMouseLeave = () => {
    dragStartRef.current = null;
  };

  useEffect(() => {
    reloadVoiceSettings();
    const handleStorage = (e: StorageEvent) => {
      if (e.key === 'voiceSettings') {
        reloadVoiceSettings();
        if (voiceSettingsRef.current.enableWakeWord) {
          if (!wakeWsRef.current && !isListeningRef.current) startWakeWordListenerRef.current();
        } else {
          stopWakeWordListener();
        }
      }
    };
    window.addEventListener('storage', handleStorage);
    ensureMicPermission().then((granted) => {
      if (granted) startWakeWordListenerRef.current();
    });
    return () => {
      window.removeEventListener('storage', handleStorage);
      stopWakeWordListener();
    };
  }, [reloadVoiceSettings, ensureMicPermission, stopWakeWordListener]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onMainWindowVisibility) return;
    const unsubscribe = api.onMainWindowVisibility((visible: boolean) => {
      if (visible && !voiceSettingsRef.current.alwaysOnListening) {
        stopWakeWordListener();
      } else {
        startWakeWordListenerRef.current();
      }
    });
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [stopWakeWordListener]);

  return (
    <div
      className={`bubble-container ${autonomousState.expression !== 'calm' ? `data-expression-${autonomousState.expression}` : ''}`}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseLeave}
      role="button"
      tabIndex={0}
      aria-label="JARVIS voice assistant bubble"
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          const api = (window as any).electronAPI;
          api?.toggleMainWindow?.();
        }
      }}
    >
      <VoiceOrb
        state={orbState}
        analysers={[]}
        isError={false}
        isPanelOpen={isPanelOpen}
        isVoiceActive={orbState === 'listening' || orbState === 'speaking'}
        isTyping={false}
      />
      {autonomousState.whisper && (
        <div className="orb-whisper" aria-live="polite">
          {autonomousState.whisper}
          <button
            className="orb-whisper-dismiss"
            onClick={(e) => {
              e.stopPropagation();
              dismissWhisper();
            }}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
      {replyText && (
        <div className="bubble-reply" aria-live="polite">
          {replyText}
        </div>
      )}
      <button
        className={`ptt-button ${pttActive ? 'active' : ''}`}
        onMouseDown={(e) => {
          e.stopPropagation();
          setPttActive(true);
          setOrbState('listening');
          setReplyText('');
          stopWakeWordListener();
          void beginPttStream();
        }}
        onMouseUp={(e) => {
          e.stopPropagation();
          void stopPttStream();
        }}
        onMouseLeave={(e) => {
          e.stopPropagation();
          void stopPttStream();
        }}
        onTouchStart={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setPttActive(true);
          setOrbState('listening');
          setReplyText('');
          stopWakeWordListener();
          void beginPttStream();
        }}
        onTouchEnd={(e) => {
          e.preventDefault();
          e.stopPropagation();
          void stopPttStream();
        }}
        aria-label="Hold to talk"
        title="Hold to talk"
      >
        {pttActive ? '●' : 'Talk'}
      </button>
    </div>
  );
}

export default BubbleApp;
