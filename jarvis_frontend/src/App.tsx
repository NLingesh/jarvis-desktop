import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import './App.css';
import OrbEngine from './orb/OrbEngine';
import { Panel, PanelView } from './panel';
import { computeRms, uint8ToBase64 } from './audioStream';
import {
  checkBackendHealth,
  checkVoiceDiagnostics,
  classifyError,
  logVoice,
  retryWithBackoff,
  withTimeout,
  type VoiceStage,
} from './voiceDiagnostics';
import { VoiceState, transition, type VoiceStateContext } from './voiceStateMachine';
import { ToastProvider } from './components/ToastProvider';
import type { OrbState } from './orb/OrbEngine';

const PCM_WORKLET_URL = '/pcmWorklet.js';

// Single expanding window geometry (mirrors electron/main.js MODE_SPECS).
const ORB_WINDOW = 96;
const MENU_WINDOW = 240;
const PANEL_ANCHOR = { x: 190, y: 520 };
const ORB_POSITION_KEY = 'jarvisOrbPosition';

type WindowMode = 'orb' | 'menu' | 'panel';
const ENDPOINT_RMS_THRESHOLD = 500;
const ENDPOINT_SILENCE_MS = 900;

function getElectronAPI(): any {
  return (window as any).electronAPI;
}

type SettingsState = {
  voice: string;
  volume: number;
  speed: number;
  theme: string;
  enableNotifications: boolean;
  serverUrl: string;
  enableWakeWord: boolean;
  alwaysOnListening: boolean;
  voiceMode: 'native' | 'browser';
  nativeMicDevice?: number | string;
};

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-banner" style={{ padding: '2rem', textAlign: 'center' }}>
          <p>Something went wrong: {this.state.error?.message}</p>
          <button onClick={() => window.location.reload()}>Restart</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function App() {
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelView, setPanelView] = useState<PanelView>('chat');
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [windowMode, setWindowMode] = useState<WindowMode>('orb');
  const [quickActionsOpen, setQuickActionsOpen] = useState(false);
  const [_voiceMachineState, _setVoiceMachineState] = useState<VoiceState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<SettingsState>(() => {
    const stored = localStorage.getItem('voiceSettings');
    let parsed: Partial<SettingsState> = {};
    if (stored) {
      try {
        parsed = JSON.parse(stored);
      } catch {
        /* ignore */
      }
    }
    return {
      voice: parsed.voice ?? 'en-US',
      volume: parsed.volume ?? 0.8,
      speed: parsed.speed ?? 1.0,
      theme: parsed.theme ?? 'dark',
      enableNotifications: parsed.enableNotifications ?? true,
      serverUrl: localStorage.getItem('serverUrl') || parsed.serverUrl || 'localhost:8000',
      enableWakeWord: parsed.enableWakeWord ?? true,
      alwaysOnListening: parsed.alwaysOnListening ?? false,
      voiceMode: parsed.voiceMode ?? 'native',
      nativeMicDevice: parsed.nativeMicDevice,
    };
  });
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isEndpointing, setIsEndpointing] = useState(false);
  const [_sheetState, setSheetState] = useState<'hidden' | 'transcript' | 'response'>('hidden');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [assistantText, setAssistantText] = useState('');
  const liveTranscriptRef = useRef(liveTranscript);
  liveTranscriptRef.current = liveTranscript;
  const assistantTextRef = useRef(assistantText);
  assistantTextRef.current = assistantText;
  const [showOnboarding, setShowOnboarding] = useState(() => {
    return localStorage.getItem('jarvisOnboarded') !== 'true';
  });
  const [orbPosition, setOrbPosition] = useState<{ x: number; y: number }>(() => {
    try {
      const stored = localStorage.getItem(ORB_POSITION_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
          return { x: parsed.x, y: parsed.y };
        }
      }
    } catch {
      /* ignore */
    }
    return { x: Math.round(window.innerWidth / 2), y: Math.round(window.innerHeight / 2) };
  });
  const [rms, setRms] = useState(0);
  const isElectron = useMemo(() => !!getElectronAPI()?.setWindowMode, []);
  const dragStartPosRef = useRef<{ x: number; y: number } | null>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout>>();

  const ws = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const analysers = useRef<Array<AnalyserNode>>([]);
  const audioChunksRef = useRef<string[]>([]);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingAudioRef = useRef(false);
  const pendingSegmentsRef = useRef(0);
  const enqueueAudioRef = useRef<(audioBase64: string) => void>(() => {});
  const lastActivityRef = useRef(Date.now());
  const streamRef = useRef<MediaStream | null>(null);
  const isConnectedRef = useRef(false);
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
  const processingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const micPermissionGrantedRef = useRef(false);
  const micBusyRef = useRef(false);
  const awaitingPongRef = useRef(false);
  const pingSentAtRef = useRef(0);
  const recordingStartedAtRef = useRef(0);
  const speechDetectedRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);
  const flushResolveRef = useRef<(() => void) | null>(null);
  const requestStartRef = useRef(0);
  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const orbPositionRef = useRef(orbPosition);
  orbPositionRef.current = orbPosition;
  const orbStateRef = useRef<OrbState>('idle');
  orbStateRef.current = orbState;
  const windowModeRef = useRef<WindowMode>('orb');
  windowModeRef.current = windowMode;
  const stopManualRecordingRef = useRef<() => Promise<void>>(async () => {});
  const startProcessingWatchdogRef = useRef<() => void>(() => {});
  const beginVoiceSessionRef = useRef<() => Promise<void>>(async () => {});
  const nativeReadyRef = useRef(false);
  const nativeListeningRef = useRef(false);
  const nativeDevicesRef = useRef<Array<{ id: number; name: string }>>([]);

  useEffect(() => {
    const syncSettings = () => {
      try {
        const stored = localStorage.getItem('voiceSettings');
        if (stored) {
          const parsed = JSON.parse(stored);
          setSettings((prev) => ({
            ...prev,
            ...(typeof parsed.voiceMode === 'string' ? { voiceMode: parsed.voiceMode } : {}),
            ...(parsed.nativeMicDevice !== undefined
              ? { nativeMicDevice: parsed.nativeMicDevice }
              : {}),
          }));
        }
      } catch {
        /* ignore */
      }
    };
    window.addEventListener('storage', syncSettings);
    window.addEventListener('jarvis-settings-change', syncSettings);
    return () => {
      window.removeEventListener('storage', syncSettings);
      window.removeEventListener('jarvis-settings-change', syncSettings);
    };
  }, []);

  const closePanel = useCallback(() => {
    if (listeningRef.current || nativeListeningRef.current) {
      const socket = ws.current;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'stop_listening' }));
      }
      nativeListeningRef.current = false;
      setIsListening(false);
    }
    setPanelOpen(false);
    setQuickActionsOpen(false);
    setLiveTranscript('');
    setAssistantText('');
    setSheetState('hidden');
    setIsProcessing(false);
    if (orbStateRef.current !== 'offline') {
      setOrbState('idle');
    }
    if (isElectron && windowModeRef.current !== 'orb') {
      getElectronAPI()?.setWindowMode?.('orb');
    }
    setWindowMode('orb');
  }, [isElectron]);

  const openPanel = useCallback(
    (view?: PanelView) => {
      if (view) setPanelView(view);
      setQuickActionsOpen(false);
      setPanelOpen(true);
      if (isElectron && windowModeRef.current !== 'panel') {
        getElectronAPI()?.setWindowMode?.(
          'panel',
          orbPositionRef.current.x,
          orbPositionRef.current.y,
        );
      }
      setWindowMode('panel');
    },
    [isElectron],
  );

  const toggleQuickActions = useCallback(() => {
    const next = !quickActionsOpen;
    if (isElectron) {
      getElectronAPI()?.setWindowMode?.(
        next ? 'menu' : 'orb',
        orbPositionRef.current.x,
        orbPositionRef.current.y,
      );
    }
    setQuickActionsOpen(next);
  }, [isElectron, quickActionsOpen]);

  const closeQuickActions = useCallback(() => {
    if (quickActionsOpen && isElectron) {
      getElectronAPI()?.setWindowMode?.('orb', orbPositionRef.current.x, orbPositionRef.current.y);
    }
    setQuickActionsOpen(false);
  }, [isElectron, quickActionsOpen]);

  const handlePanelClose = useCallback(() => closePanel(), [closePanel]);

  const getSessionToken = useCallback(async (): Promise<string | null> => {
    const api = (window as any).electronAPI;
    if (api?.getSessionToken) {
      try {
        const token = (await api.getSessionToken()) as string | null;
        if (token) return token;
      } catch {
        /* ignore */
      }
    }
    // Browser-mode fallback (non-Electron dev/test): allow a locally stored
    // token so the voice WS handshake succeeds without the Electron bridge.
    return localStorage.getItem('jarvisSessionToken');
  }, []);

  const resolveWebSocketUrl = useCallback((server: string, token: string | null) => {
    const trimmed = server.replace(/\/*$/, '');
    const native = settingsRef.current.voiceMode === 'native';
    const endpoint = native ? '/ws/voice/native' : '/ws/voice';
    let url: string;
    if (trimmed.startsWith('ws://') || trimmed.startsWith('wss://')) {
      url = `${trimmed}${endpoint}`;
    } else if (trimmed.startsWith('http://')) {
      url = `ws://${trimmed.slice(7)}${endpoint}`;
    } else if (trimmed.startsWith('https://')) {
      url = `wss://${trimmed.slice(8)}${endpoint}`;
    } else {
      url = `ws://${trimmed}${endpoint}`;
    }
    if (token) url += `?token=${encodeURIComponent(token)}`;
    return url;
  }, []);

  const getVoiceContext = useCallback(
    (): VoiceStateContext => ({
      micPermissionGranted: micPermissionGrantedRef.current,
      wsConnected: isConnectedRef.current,
      hasTranscript: liveTranscriptRef.current.trim().length > 0,
      hasResponse: assistantTextRef.current.trim().length > 0,
      sttAvailable: true,
      ttsAvailable: true,
    }),
    [],
  );

  const handleVoiceError = useCallback(
    (stage: VoiceStage, error: unknown, fallback: string): string => {
      const classified = classifyError(stage, error);
      logVoice(stage, { code: classified.code, message: classified.message, level: 'error' });
      return classified.message || fallback;
    },
    [],
  );

  const checkHealth = useCallback(async () => {
    logVoice('health', { level: 'debug' });
    const server = settings.serverUrl;
    const result = await checkBackendHealth(server);
    const diagnostics = await checkVoiceDiagnostics(server);
    const stt = (diagnostics?.stt as { ready?: boolean } | undefined)?.ready;
    const tts = (diagnostics?.tts as { ready?: boolean } | undefined)?.ready;
    const llm = (diagnostics?.llm as { configured?: boolean } | undefined)?.configured;
    logVoice('health', {
      level: result.ok ? 'debug' : 'error',
      backend: result.ok,
      error: result.error,
      stt,
      tts,
      llm,
    });
    if (!result.ok) {
      if (orbStateRef.current === 'idle' || orbStateRef.current === 'offline') {
        setOrbState('offline');
      }
      if (result.error) {
        setError(result.error);
      }
    } else if (orbStateRef.current === 'offline') {
      setOrbState('idle');
      setError(null);
    }
  }, [settings.serverUrl]);

  const tryGetUserMedia = async (constraints: MediaStreamConstraints): Promise<MediaStream> => {
    try {
      return await withTimeout(
        navigator.mediaDevices.getUserMedia(constraints),
        6000,
        'Microphone timed out',
      );
    } catch (err) {
      const name = (err as any)?.name || '';
      const message = (err as Error)?.message || '';
      if (
        (name === 'OverconstrainedError' ||
          name === 'TimeoutError' ||
          message.includes('timed out')) &&
        typeof constraints.audio === 'object'
      ) {
        return withTimeout(
          navigator.mediaDevices.getUserMedia({ audio: true }),
          6000,
          'Microphone timed out',
        );
      }
      throw err;
    }
  };

  const tryGetUserMediaWithRetry = async (
    constraints: MediaStreamConstraints,
    retries = 2,
  ): Promise<MediaStream> =>
    retryWithBackoff(() => tryGetUserMedia(constraints), retries, 1000, 4000, 'mic');

  const ensureMicPermission = useCallback(async (): Promise<boolean> => {
    if (micPermissionGrantedRef.current) return true;
    try {
      if (navigator.permissions && (navigator.permissions as any).query) {
        try {
          const result = await (navigator.permissions as any).query({ name: 'microphone' });
          if (result.state === 'granted') {
            micPermissionGrantedRef.current = true;
            return true;
          }
        } catch {
          /* ignore */
        }
      }
      await tryGetUserMediaWithRetry({ audio: true });
      micPermissionGrantedRef.current = true;
      return true;
    } catch (err) {
      const message = handleVoiceError('mic', err, 'Microphone access denied.');
      setError(message);
      return false;
    }
  }, [handleVoiceError]);

  useEffect(() => {
    let reconnectDelay = 1000;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = async () => {
      if (cancelled) return;
      if (ws.current && ws.current.readyState === WebSocket.OPEN) return;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (ws.current) {
        ws.current.close();
        ws.current = null;
      }
      try {
        const token = await getSessionToken();
        if (cancelled) return;
        const url = resolveWebSocketUrl(settings.serverUrl, token);
        ws.current = new WebSocket(url);
        ws.current.onopen = () => {
          isConnectedRef.current = true;
          awaitingPongRef.current = false;
          setError(null);
          reconnectDelay = 1000;
          if (orbStateRef.current === 'offline') {
            setOrbState('idle');
          }
          _setVoiceMachineState((prev) => transition(prev, 'ws_open', getVoiceContext()));
          logVoice('ws_ready');
          if (settingsRef.current.voiceMode === 'native') {
            ws.current?.send(
              JSON.stringify({
                type: 'connect',
                device: settingsRef.current.nativeMicDevice ?? undefined,
              }),
            );
            ws.current?.send(JSON.stringify({ type: 'get_devices' }));
          }
        };
        ws.current.onmessage = (event) => {
          let data: any;
          try {
            data = JSON.parse(event.data);
          } catch {
            setError('Invalid data from server');
            return;
          }
          if (data.type === 'state' && settingsRef.current.voiceMode === 'native') {
            nativeReadyRef.current = data.state === 'READY' || data.state === 'LISTENING';
            nativeListeningRef.current = data.state === 'LISTENING';
            setIsListening(data.state === 'LISTENING');
            if (data.state === 'LISTENING') {
              setOrbState('listening');
              setSheetState('transcript');
            } else if (data.state === 'PROCESSING') {
              setOrbState('thinking');
              setIsProcessing(true);
            } else if (data.state === 'SPEAKING') {
              setOrbState('speaking');
            } else if (data.state === 'READY' || data.state === 'IDLE') {
              setIsProcessing(false);
              setIsListening(false);
              nativeListeningRef.current = false;
              if (!isPlayingAudioRef.current && audioQueueRef.current.length === 0) {
                setOrbState('idle');
              }
            } else if (data.state === 'ERROR') {
              setError(data.detail || 'Voice session error');
              setOrbState('error');
              if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
              errorTimerRef.current = setTimeout(() => {
                setOrbState((prev) => (prev === 'error' ? 'idle' : prev));
              }, 1600);
            }
          } else if (data.type === 'level' && settingsRef.current.voiceMode === 'native') {
            setRms(Math.min(1, Math.max(0, data.rms)));
          } else if (data.type === 'devices' && settingsRef.current.voiceMode === 'native') {
            nativeDevicesRef.current = data.devices ?? [];
          } else if (data.type === 'pong') {
            awaitingPongRef.current = false;
          } else if (data.type === 'response') {
            setAssistantText(data.text);
            setSheetState('response');
            lastActivityRef.current = Date.now();
            if (data.audio) enqueueAudioRef.current(data.audio);
            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            // Only show the orb as speaking if there is queued/playing audio;
            // otherwise return straight to idle so the UI never sticks.
            if (audioQueueRef.current.length > 0 || isPlayingAudioRef.current) {
              setOrbState('speaking');
            } else {
              setOrbState('idle');
            }
            _setVoiceMachineState((prev) => transition(prev, 'audio_finished', getVoiceContext()));
          } else if (data.type === 'partial') {
            setAssistantText(data.text);
            setSheetState('response');
            lastActivityRef.current = Date.now();
          } else if (data.type === 'transcript') {
            setLiveTranscript(data.text);
            lastActivityRef.current = Date.now();
          } else if (data.type === 'status') {
            if (data.status === 'processing') setOrbState('thinking');
            else if (data.status === 'generating_speech') setOrbState('speaking');
          } else if (data.type === 'proactive') {
            if (data.text) {
              setAssistantText(data.text);
              setSheetState('response');
              lastActivityRef.current = Date.now();
            }
          } else if (data.type === 'audio_queue') {
            pendingSegmentsRef.current = data.count ?? 0;
            setOrbState('speaking');
          } else if (data.type === 'audio_segment_start') {
            audioChunksRef.current = [];
          } else if (data.type === 'audio_chunk' && data.chunk) {
            audioChunksRef.current.push(data.chunk);
          } else if (data.type === 'audio_segment_end') {
            const combined = audioChunksRef.current.join('');
            audioChunksRef.current = [];
            if (combined) {
              enqueueAudioRef.current(combined);
            } else {
              // No audio arrived for this segment (e.g. TTS failed). Recover
              // immediately so the orb does not get stuck on speaking.
              if (
                audioQueueRef.current.length === 0 &&
                !isPlayingAudioRef.current &&
                pendingSegmentsRef.current <= 1
              ) {
                setOrbState('idle');
              }
            }
            if (pendingSegmentsRef.current > 0) {
              pendingSegmentsRef.current -= 1;
            }
          } else if (data.type === 'error') {
            const message = handleVoiceError('ws', data.message, 'Connection error');
            setError(message);
            setOrbState('idle');
            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            setSheetState('hidden');
            _setVoiceMachineState((prev) => transition(prev, 'ws_failed', getVoiceContext()));
          }
        };
        ws.current.onerror = () => {
          const message = handleVoiceError(
            'ws',
            new Error('WebSocket connection error'),
            'Connection error',
          );
          setError(message);
          isConnectedRef.current = false;
          setIsProcessing(false);
          _setVoiceMachineState((prev) => transition(prev, 'ws_failed', getVoiceContext()));
        };
        ws.current.onclose = () => {
          isConnectedRef.current = false;
          setIsProcessing(false);
          if (reconnectTimer) clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, 60000);
            const jitter = Math.random() * 0.3 + 0.85;
            const nextDelay = Math.min(Math.floor(reconnectDelay * jitter), 60000);
            reconnectDelay = nextDelay;
            connect();
          }, reconnectDelay);
        };
      } catch (err) {
        const message = handleVoiceError('ws', err, 'Failed to connect to server');
        setError(message);
        _setVoiceMachineState((prev) => transition(prev, 'ws_failed', getVoiceContext()));
      }
    };

    connect();
    const interval = setInterval(() => {
      if (!isConnectedRef.current && !reconnectTimer)
        reconnectTimer = setTimeout(connect, reconnectDelay);
    }, 5000);
    const pingInterval = setInterval(() => {
      const socket = ws.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      if (awaitingPongRef.current && Date.now() - pingSentAtRef.current > 15000) {
        socket.close();
        return;
      }
      try {
        socket.send(JSON.stringify({ type: 'ping' }));
        awaitingPongRef.current = true;
        pingSentAtRef.current = Date.now();
      } catch {
        /* ignore */
      }
    }, 25000);

    return () => {
      cancelled = true;
      clearInterval(interval);
      clearInterval(pingInterval);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws.current) ws.current.close();
    };
  }, [
    settings.serverUrl,
    settings.voiceMode,
    getSessionToken,
    resolveWebSocketUrl,
    handleVoiceError,
    getVoiceContext,
  ]);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, [checkHealth]);

  useEffect(() => {
    const initAudio = async () => {
      try {
        audioContext.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      } catch {
        setError('Audio not supported');
      }
    };
    initAudio();
    return () => {
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
      if (recordingTimerRef.current) clearTimeout(recordingTimerRef.current);
      if (processingTimerRef.current) clearTimeout(processingTimerRef.current);
      if (audioWorkletNodeRef.current) {
        audioWorkletNodeRef.current.port.onmessage = null;
        try {
          audioWorkletNodeRef.current.disconnect();
        } catch {
          /* ignore */
        }
        audioWorkletNodeRef.current = null;
      }
      if (audioSourceRef.current) {
        try {
          audioSourceRef.current.disconnect();
        } catch {
          /* ignore */
        }
        audioSourceRef.current = null;
      }
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      if (audioContext.current && audioContext.current.state !== 'closed')
        audioContext.current.close().catch(() => {});
    };
  }, []);

  useEffect(() => {
    let raf: number;
    const updateRms = () => {
      if (analysers.current[0]) {
        const data = new Uint8Array(analysers.current[0].frequencyBinCount);
        analysers.current[0].getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const r = Math.sqrt(sum / data.length) / 255;
        setRms(r);
      }
      raf = requestAnimationFrame(updateRms);
    };
    raf = requestAnimationFrame(updateRms);
    return () => cancelAnimationFrame(raf);
  }, []);

  const listeningRef = useRef(isListening);
  const processingRef = useRef(isProcessing);
  listeningRef.current = isListening;
  processingRef.current = isProcessing;

  const toggleTalk = useCallback(async () => {
    if (processingRef.current) return;
    if (settingsRef.current.voiceMode === 'native') {
      const socket = ws.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      if (listeningRef.current || nativeListeningRef.current) {
        socket.send(JSON.stringify({ type: 'stop_listening' }));
        nativeListeningRef.current = false;
        setIsListening(false);
        setOrbState('thinking');
        setIsProcessing(true);
        requestStartRef.current = Date.now();
        startProcessingWatchdogRef.current();
        return;
      }
      socket.send(JSON.stringify({ type: 'start_listening', mode: 'ptt' }));
      nativeListeningRef.current = true;
      setIsListening(true);
      setSheetState('transcript');
      setLiveTranscript('Listening...');
      return;
    }
    if (listeningRef.current) {
      await stopManualRecordingRef.current();
      return;
    }
    await beginVoiceSessionRef.current();
  }, []);

  const sendAudioStart = () => {
    const socket = ws.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({ type: 'audio_start', format: 'pcm16', sample_rate: 16000, channels: 1 }),
    );
  };

  const sendAudioChunk = (bytes: Uint8Array) => {
    const socket = ws.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'audio_chunk', data: uint8ToBase64(bytes) }));
  };

  const sendAudioEnd = () => {
    const socket = ws.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'audio_end' }));
  };

  const checkEndpointing = (pcm: Uint8Array) => {
    if (pcm.length === 0) return;
    const rms = computeRms(pcm);
    if (rms > ENDPOINT_RMS_THRESHOLD) {
      speechDetectedRef.current = true;
      silenceStartRef.current = null;
      return;
    }
    if (!speechDetectedRef.current) return;
    if (Date.now() - recordingStartedAtRef.current < 1000) return;
    if (silenceStartRef.current === null) {
      silenceStartRef.current = Date.now();
      return;
    }
    if (Date.now() - silenceStartRef.current >= ENDPOINT_SILENCE_MS) {
      silenceStartRef.current = null;
      setIsEndpointing(true);
      if (audioWorkletNodeRef.current) void stopManualRecordingRef.current();
    }
  };

  const startRecording = async () => {
    try {
      const stream = await tryGetUserMediaWithRetry({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      setIsListening(true);
      setOrbState('listening');
      setLiveTranscript('Recording...');
      setSheetState('transcript');
      lastActivityRef.current = Date.now();
      setIsEndpointing(false);
      let ctx = audioContext.current;
      if (!ctx || ctx.state === 'closed') {
        ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        audioContext.current = ctx;
      }
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      await ctx.audioWorklet.addModule(PCM_WORKLET_URL);
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
      const analyser = ctx.createAnalyser();
      source.connect(analyser);
      analysers.current = [analyser];
      worklet.port.onmessage = (event) => {
        if (!event.data || event.data.type !== 'pcm') return;
        const bytes = event.data.pcm as ArrayBuffer;
        if (bytes && bytes.byteLength > 0) {
          sendAudioChunk(new Uint8Array(bytes));
        }
        if (event.data.final) {
          const resolve = flushResolveRef.current;
          flushResolveRef.current = null;
          if (resolve) resolve();
          return;
        }
        checkEndpointing(new Uint8Array(bytes));
      };
      sendAudioStart();
      audioSourceRef.current = source;
      audioWorkletNodeRef.current = worklet;
      recordingStartedAtRef.current = Date.now();
      speechDetectedRef.current = false;
      silenceStartRef.current = null;
      if (recordingTimerRef.current) clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = setTimeout(() => {
        if (audioWorkletNodeRef.current) void stopManualRecordingRef.current();
      }, 30000);
    } catch (err) {
      const message = handleVoiceError('mic', err, 'Could not start the microphone.');
      setError(message);
      setOrbState('idle');
      setIsListening(false);
      setSheetState('hidden');
      _setVoiceMachineState((prev) => transition(prev, 'mic_denied', getVoiceContext()));
    }
  };

  const cleanupListening = (stream: MediaStream | null) => {
    if (recordingTimerRef.current) {
      clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = undefined;
    }
    if (audioWorkletNodeRef.current) {
      audioWorkletNodeRef.current.port.onmessage = null;
      try {
        audioWorkletNodeRef.current.disconnect();
      } catch {
        /* ignore */
      }
      audioWorkletNodeRef.current = null;
    }
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.disconnect();
      } catch {
        /* ignore */
      }
      audioSourceRef.current = null;
    }
    if (stream) stream.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    analysers.current = [];
    silenceStartRef.current = null;
  };

  const stopManualRecording = async () => {
    if (settingsRef.current.voiceMode === 'native') return;
    const stream = streamRef.current;
    if (!audioWorkletNodeRef.current && !stream) {
      setIsListening(false);
      setOrbState('idle');
      setSheetState('hidden');
      return;
    }
    setIsListening(false);
    try {
      const worklet = audioWorkletNodeRef.current;
      if (worklet) {
        await new Promise<void>((resolve) => {
          flushResolveRef.current = resolve;
          worklet.port.postMessage({ type: 'flush' });
          setTimeout(() => {
            if (flushResolveRef.current) {
              flushResolveRef.current = null;
              resolve();
            }
          }, 500);
        });
      }
    } catch {
      /* ignore */
    }
    sendAudioEnd();
    cleanupListening(stream);
    setIsEndpointing(false);
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      setError('Not connected to server');
      setSheetState('hidden');
      return;
    }
    setOrbState('thinking');
    setLiveTranscript('Transcribing...');
    setIsProcessing(true);
    requestStartRef.current = Date.now();
    startProcessingWatchdogRef.current();
  };
  stopManualRecordingRef.current = stopManualRecording;

  const beginVoiceSession = async () => {
    if (processingRef.current || listeningRef.current || micBusyRef.current) return;
    if (settingsRef.current.voiceMode === 'native') {
      const socket = ws.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        setError('Not connected to server');
        return;
      }
      nativeReadyRef.current = false;
      socket.send(JSON.stringify({ type: 'connect', device: settingsRef.current.nativeMicDevice }));
      await new Promise<void>((resolve) => {
        const start = Date.now();
        const check = () => {
          if (nativeReadyRef.current) return resolve();
          if (Date.now() - start > 8000) {
            setError('Microphone connection timed out');
            return resolve();
          }
          setTimeout(check, 100);
        };
        setTimeout(check, 100);
      });
      micBusyRef.current = true;
      try {
        socket.send(JSON.stringify({ type: 'start_listening', mode: 'ptt' }));
        nativeListeningRef.current = true;
        setIsListening(true);
        setSheetState('transcript');
        setLiveTranscript('Listening...');
      } finally {
        micBusyRef.current = false;
      }
      return;
    }
    micBusyRef.current = true;
    try {
      const hasPermission = await ensureMicPermission();
      if (!hasPermission) return;
      if (navigator.vibrate) navigator.vibrate(50);
      setSheetState('transcript');
      lastActivityRef.current = Date.now();
      await startRecording();
    } finally {
      micBusyRef.current = false;
    }
  };
  beginVoiceSessionRef.current = beginVoiceSession;

  const triggerWakeWord = useCallback(async () => {
    if (listeningRef.current || processingRef.current) return;
    const attempt = (n: number) => {
      if (listeningRef.current || processingRef.current) return;
      if (ws.current && ws.current.readyState === WebSocket.OPEN) {
        _setVoiceMachineState((prev) => transition(prev, 'wake_word_detected', getVoiceContext()));
        void beginVoiceSessionRef.current();
        return;
      }
      if (n < 8) setTimeout(() => attempt(n + 1), 500);
    };
    attempt(0);
  }, [getVoiceContext]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onWakeWordDetected) return;
    const handler = () => {
      if (listeningRef.current || processingRef.current) return;
      triggerWakeWord();
    };
    const unsubscribe = api.onWakeWordDetected(handler);
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [triggerWakeWord]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onSwitchView) return;
    const unsubscribe = api.onSwitchView((view: string) => {
      openPanel(view as PanelView);
    });
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [openPanel]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onTogglePanel) return;
    const unsubToggle = api.onTogglePanel(() => {
      if (panelOpen) closePanel();
      else openPanel();
    });
    const unsubOpen = api.onOpenPanel(() => openPanel());
    const unsubClose = api.onClosePanel(() => closePanel());
    return () => {
      if (typeof unsubToggle === 'function') unsubToggle();
      if (typeof unsubOpen === 'function') unsubOpen();
      if (typeof unsubClose === 'function') unsubClose();
    };
  }, [panelOpen, openPanel, closePanel]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onVoiceControl) return;
    const unsubscribe = api.onVoiceControl((action: string) => {
      if (action === 'toggle' || action === 'start') toggleTalk();
      else if (action === 'stop') {
        if (listeningRef.current) toggleTalk();
      }
    });
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [toggleTalk]);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onContextMenuAction) return;
    const unsubscribe = api.onContextMenuAction((action: string) => {
      if (action === 'talk') toggleTalk();
      else if (action === 'quit') api.quitApp?.();
      else openPanel(action as PanelView);
    });
    return () => {
      if (typeof unsubscribe === 'function') unsubscribe();
    };
  }, [toggleTalk, openPanel]);

  useEffect(() => {
    if (!isElectron) return;
    const api = getElectronAPI();
    let cancelled = false;
    api?.getOrbPosition?.().then((pos: { x: number; y: number } | null) => {
      if (!cancelled && pos && typeof pos.x === 'number' && typeof pos.y === 'number') {
        setOrbPosition(pos);
        localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(pos));
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isElectron]);

  useEffect(() => {
    localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(orbPosition));
  }, [orbPosition]);

  useEffect(() => {
    if (!quickActionsOpen) return;
    const timer = setTimeout(() => closeQuickActions(), 6000);
    const handleBlur = () => closeQuickActions();
    window.addEventListener('blur', handleBlur);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('blur', handleBlur);
    };
  }, [quickActionsOpen, closeQuickActions]);

  const playNextAudio = useCallback(() => {
    if (isPlayingAudioRef.current) return;
    const next = audioQueueRef.current.shift();
    if (!next) {
      setOrbState('idle');
      return;
    }
    isPlayingAudioRef.current = true;
    try {
      const audioData = Uint8Array.from(atob(next), (c) => c.charCodeAt(0));
      const isWav =
        audioData.byteLength > 4 &&
        String.fromCharCode(audioData[0], audioData[1], audioData[2], audioData[3]) === 'RIFF';
      const blob = new Blob([audioData], { type: isWav ? 'audio/wav' : 'audio/mpeg' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.volume = settings.volume;
      audio.playbackRate = settings.speed;
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
      setError('Failed to play audio');
      isPlayingAudioRef.current = false;
      playNextAudio();
    }
  }, [settings.volume, settings.speed]);

  const enqueueAudio = useCallback(
    (audioBase64: string) => {
      audioQueueRef.current.push(audioBase64);
      playNextAudio();
    },
    [playNextAudio],
  );
  enqueueAudioRef.current = enqueueAudio;

  const startProcessingWatchdog = () => {
    if (processingTimerRef.current) clearTimeout(processingTimerRef.current);
    processingTimerRef.current = setTimeout(() => {
      if (processingRef.current) {
        setIsProcessing(false);
        setOrbState('idle');
        setError('The assistant took too long to respond.');
      }
    }, 45000);
  };
  startProcessingWatchdogRef.current = startProcessingWatchdog;

  const handleOrbDragMove = useCallback(
    (dx: number, dy: number) => {
      if (!dragStartPosRef.current) {
        dragStartPosRef.current = {
          x: orbPositionRef.current.x - dx,
          y: orbPositionRef.current.y - dy,
        };
        // Grow the window while dragging so a fast flick cannot leave the
        // cursor outside the (otherwise tiny) window and drop the mousemove
        // stream. The orb stays centered under the cursor the whole time.
        if (isElectron) {
          setWindowMode('menu');
          getElectronAPI()?.setWindowMode?.(
            'menu',
            orbPositionRef.current.x,
            orbPositionRef.current.y,
          );
        }
      }
      const start = dragStartPosRef.current;
      const next = { x: Math.round(start.x + dx), y: Math.round(start.y + dy) };
      if (isElectron) {
        const applied = getElectronAPI()?.setOrbPosition?.(next.x, next.y);
        if (applied && typeof applied.then === 'function') {
          applied.then((pos: { x: number; y: number } | null) => {
            if (pos && typeof pos.x === 'number') setOrbPosition(pos);
          });
        }
      } else {
        setOrbPosition(next);
      }
    },
    [isElectron],
  );

  const handleOrbDragEnd = useCallback(() => {
    dragStartPosRef.current = null;
    localStorage.setItem(ORB_POSITION_KEY, JSON.stringify(orbPositionRef.current));
    if (isElectron) {
      setWindowMode('orb');
      getElectronAPI()?.setWindowMode?.('orb', orbPositionRef.current.x, orbPositionRef.current.y);
    }
  }, [isElectron]);

  const handleOrbContextMenu = useCallback(() => {
    getElectronAPI()?.showContextMenu?.();
  }, []);

  const handleQuickAction = useCallback(
    (action: 'talk' | 'chat' | 'memory' | 'tools') => {
      setQuickActionsOpen(false);
      if (action === 'talk') {
        if (isElectron)
          getElectronAPI()?.setWindowMode?.(
            'orb',
            orbPositionRef.current.x,
            orbPositionRef.current.y,
          );
        toggleTalk();
      } else {
        openPanel(action);
      }
    },
    [toggleTalk, openPanel, isElectron],
  );

  const handlePanelToggleTalk = useCallback(() => {
    if (isProcessing) return;
    toggleTalk();
  }, [isProcessing, toggleTalk]);

  const handlePanelViewChange = useCallback((view: PanelView) => {
    setPanelView(view);
  }, []);

  useEffect(() => {
    logVoice('fsm', { level: 'debug', state: _voiceMachineState });
  }, [_voiceMachineState]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return;
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        if (!isElectron) toggleTalk();
        return;
      }
      if (e.key === 'Escape' && panelOpen) {
        handlePanelClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleTalk, panelOpen, handlePanelClose, isElectron]);

  const effectiveOrbState: OrbState = panelOpen && orbState === 'idle' ? 'panel-open' : orbState;

  const orbAnchorStyle = useMemo(() => {
    if (isElectron) {
      if (windowMode === 'panel') {
        return {
          position: 'absolute' as const,
          left: PANEL_ANCHOR.x,
          top: PANEL_ANCHOR.y,
          transform: 'translate(-50%, -50%)',
          display: 'none',
        };
      }
      const anchor = windowMode === 'menu' ? MENU_WINDOW / 2 : ORB_WINDOW / 2;
      return {
        position: 'absolute' as const,
        left: anchor,
        top: anchor,
        transform: 'translate(-50%, -50%)',
      };
    }
    return {
      position: 'absolute' as const,
      left: orbPosition.x,
      top: orbPosition.y,
      transform: 'translate(-50%, -50%)',
    };
  }, [isElectron, windowMode, orbPosition]);

  const showTransientHud = !isElectron || windowMode === 'panel';

  return (
    <ToastProvider>
      <ErrorBoundary>
        <div
          className={`app ${isElectron ? 'app-electron' : ''} ${windowMode === 'panel' ? 'panel-mode' : ''}`}
          role="main"
          aria-label="JARVIS Voice Assistant"
        >
          {showOnboarding && (panelOpen || !isElectron) && (
            <div className="onboarding-overlay" aria-hidden={!showOnboarding}>
              <div className="onboarding-panel">
                <h2>Welcome to JARVIS</h2>
                <p>Your desktop companion is ready. Configure your settings to get started.</p>
                <button
                  onClick={() => {
                    localStorage.setItem('jarvisOnboarded', 'true');
                    setShowOnboarding(false);
                  }}
                >
                  Get Started
                </button>
              </div>
            </div>
          )}
          <main className="app-main">
            <div
              className={`orb-anchor ${isListening ? 'recording' : ''} ${windowMode === 'panel' ? 'orb-anchor-hidden' : ''}`}
              style={orbAnchorStyle as React.CSSProperties}
            >
              <OrbEngine
                state={effectiveOrbState}
                rms={rms}
                onToggleTalk={toggleTalk}
                onExpandPanel={() => openPanel()}
                onSingleClick={toggleQuickActions}
                onQuickAction={handleQuickAction}
                onClick={handlePanelClose}
                onDragMove={handleOrbDragMove}
                onDragEnd={handleOrbDragEnd}
                onContextMenu={handleOrbContextMenu}
                quickActionsOpen={quickActionsOpen}
                onCloseQuickActions={closeQuickActions}
              />
            </div>

            {showTransientHud && (
              <div className="orb-hint" aria-live="polite">
                {isProcessing
                  ? 'Thinking...'
                  : isListening
                    ? isEndpointing
                      ? 'Finishing...'
                      : 'Tap to stop'
                    : 'Tap to talk'}
              </div>
            )}

            {showTransientHud && isListening && liveTranscript && (
              <div className="orb-caption" aria-live="polite">
                {liveTranscript}
              </div>
            )}

            <Panel
              open={panelOpen}
              view={panelView}
              onViewChange={handlePanelViewChange}
              onClose={handlePanelClose}
              orbPosition={orbPosition}
              onToggleTalk={handlePanelToggleTalk}
              fillWindow={isElectron}
            />
          </main>

          {showTransientHud && error && (
            <div className="error-banner" role="alert" aria-live="assertive">
              <p>{error}</p>
              <button onClick={() => setError(null)} aria-label="Dismiss error">
                &#10005;
              </button>
            </div>
          )}
        </div>
      </ErrorBoundary>
    </ToastProvider>
  );
}

export default App;
