import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import './App.css';
import MinimalBubble from './components/MinimalBubble';
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
const PANEL_ANCHOR = { x: 320, y: 320 };
const ORB_POSITION_KEY = 'jarvisOrbPosition';

type WindowMode = 'orb' | 'menu' | 'panel';
const ENDPOINT_RMS_THRESHOLD = 500;
const ENDPOINT_SILENCE_MS = 900;

function getElectronAPI(): any {
  return (window as any).electronAPI;
}

type ChatToolResult = {
  tool?: string;
  result?: { success?: boolean; data?: Record<string, unknown> };
};

// Build a short, verified summary line for tools that actually ran and
// succeeded.  Lines whose detail is already present in the backend reply are
// skipped so a deterministic "Opened /home/wiz/Downloads." is not duplicated.
function summarizeVerifiedTools(tools: unknown, reply: string): string[] {
  const list = Array.isArray(tools) ? (tools as ChatToolResult[]) : [];
  const notes: string[] = [];
  for (const t of list) {
    if (!t || !t.result || !t.result.success) continue;
    const data = (t.result.data || {}) as Record<string, unknown>;
    const detail = ['opened', 'launched', 'url', 'terminal']
      .map((key) => data[key])
      .find((value) => typeof value === 'string' && value);
    if (detail === undefined) {
      notes.push(`✓ ${t.tool || 'action'} completed`);
      continue;
    }
    if (reply.includes(String(detail))) continue;
    notes.push(`✓ ${t.tool || 'action'}: ${detail}`);
  }
  return notes;
}

// Format verified tool executions from voice responses as "✓ tool: arg"
// lines so a completed desktop action is visibly attached to its assistant
// reply (e.g. "✓ launch_application: vs code").
export function summarizeVoiceToolResults(tools: unknown): string[] {
  const list = Array.isArray(tools) ? tools : [];
  const lines: string[] = [];
  for (const t of list) {
    if (!t || typeof t !== 'object') continue;
    const tool = String((t as { tool?: unknown }).tool || '').trim();
    if (!tool) continue;
    if ((t as { verified?: unknown }).verified === false) continue;
    const args = (t as { args?: Record<string, unknown> }).args;
    let argText = '';
    if (args && typeof args === 'object') {
      argText = Object.values(args)
        .filter((v) => typeof v === 'string' && v.trim())
        .join(', ');
    }
    lines.push(argText ? `✓ ${tool}: ${argText}` : `✓ ${tool}`);
  }
  return lines;
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
  const [activeConfirmation, setActiveConfirmation] = useState<{
    tool: string;
    prompt: string;
  } | null>(null);
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
  const [typedPrompt, setTypedPrompt] = useState('');
  const [conversation, setConversation] = useState<
    Array<{ role: 'user' | 'assistant'; text: string }>
  >([]);
  const conversationEndRef = useRef<HTMLDivElement>(null);
  const lastPromptRef = useRef('');
  const lastUserPushedRef = useRef('');
  const lastRealTranscriptRef = useRef('');
  const [isTextSubmitting, setIsTextSubmitting] = useState(false);
  const liveTranscriptRef = useRef(liveTranscript);
  liveTranscriptRef.current = liveTranscript;
  const assistantTextRef = useRef(assistantText);
  assistantTextRef.current = assistantText;

  const pushConversation = useCallback((role: 'user' | 'assistant', text: string) => {
    const clean = (text || '').trim();
    if (!clean) return;
    setConversation((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === role && last.text === clean) return prev;
      return [...prev, { role, text: clean }];
    });
  }, []);
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
  const [windowDragging, setWindowDragging] = useState(false);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const [micNotice, setMicNotice] = useState<string | null>(null);
  const micNoticeTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const showMicNotice = useCallback((text: string) => {
    setMicNotice(text);
    if (micNoticeTimerRef.current) clearTimeout(micNoticeTimerRef.current);
    micNoticeTimerRef.current = setTimeout(() => setMicNotice(null), 4500);
  }, []);

  const ws = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const analysers = useRef<Array<AnalyserNode>>([]);
  const audioChunksRef = useRef<string[]>([]);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingAudioRef = useRef(false);
  const pendingSegmentsRef = useRef(0);
  const enqueueAudioRef = useRef<(audioBase64: string) => void>(() => {});
  const playbackSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const playbackTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const stopPlayback = useCallback(() => {
    audioQueueRef.current = [];
    pendingSegmentsRef.current = 0;
    if (playbackTimerRef.current) {
      clearTimeout(playbackTimerRef.current);
      playbackTimerRef.current = undefined;
    }
    if (playbackSourceRef.current) {
      try {
        playbackSourceRef.current.stop();
      } catch {
        /* already stopped */
      }
      playbackSourceRef.current = null;
    }
    isPlayingAudioRef.current = false;
    if (orbStateRef.current === 'speaking') setOrbState('idle');
  }, []);
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
  const serverBuildRef = useRef<string | null>(null);

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
    stopPlayback();
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
  }, [isElectron, stopPlayback]);

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

  const sendConfirmation = useCallback((tool: string, confirm: boolean) => {
    const socket = ws.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'confirm', tool, confirm }));
    }
    setActiveConfirmation(null);
    if (confirm) {
      // An approved action is genuinely executing now; show controlled
      // progress until the verified response arrives.
      setOrbState('working');
      setIsProcessing(true);
    }
  }, []);

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
      // This is only a permission probe. Always release the temporary stream;
      // leaving it open prevents the real capture stream below from opening
      // on PipeWire/ALSA and makes the mic appear to be permanently busy.
      const probeStream = await tryGetUserMediaWithRetry({ audio: true });
      probeStream.getTracks().forEach((track) => track.stop());
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
      if (
        ws.current &&
        (ws.current.readyState === WebSocket.OPEN || ws.current.readyState === WebSocket.CONNECTING)
      )
        return;
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
          if (data.type === 'server' && data.build) {
            // The backend restarted with a different frontend bundle than the
            // one this renderer loaded. Reload so the running UI always matches
            // the served build (never a stale bundle with old endpoints).
            if (serverBuildRef.current && serverBuildRef.current !== data.build) {
              const api = (window as any).electronAPI;
              if (api?.reloadWindow) api.reloadWindow();
              else window.location.reload();
              return;
            }
            serverBuildRef.current = data.build;
          } else if (data.type === 'window_action') {
            const action = data.action || 'show_main';
            const api = (window as any).electronAPI;
            if (api?.showMainWindow && action === 'show_main') {
              api.showMainWindow();
            } else if (api?.toggleMainWindow) {
              api.toggleMainWindow();
            }
            if (data.request_id && ws.current && ws.current.readyState === WebSocket.OPEN) {
              ws.current.send(
                JSON.stringify({ type: 'window_action_ack', request_id: data.request_id }),
              );
            }
          } else if (data.type === 'state' && settingsRef.current.voiceMode === 'native') {
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
              // The backend synthesizes speech (TTS); actual "speaking" state
              // is set by playNextAudio only once playback begins.
              setOrbState('thinking');
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
            const spoken = (lastRealTranscriptRef.current || '').trim();
            if (spoken && spoken !== lastUserPushedRef.current) {
              lastUserPushedRef.current = spoken;
              pushConversation('user', spoken);
            }
            const toolLines = summarizeVoiceToolResults(data.tool_results);
            const text = String(data.text || '');
            const display = toolLines.length
              ? `${toolLines.join('\n')}${text ? `\n${text}` : ''}`
              : text;
            pushConversation('assistant', display);
            setAssistantText(display);
            setSheetState('response');
            lastActivityRef.current = Date.now();
            if (data.audio) enqueueAudioRef.current(data.audio);
            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            // Speaking state is set by playNextAudio only when playback of
            // decoded audio actually starts; here we only drop back to idle
            // when nothing is queued or playing so the orb never lies.
            if (audioQueueRef.current.length === 0 && !isPlayingAudioRef.current) {
              setOrbState('idle');
            }
            _setVoiceMachineState((prev) => transition(prev, 'audio_finished', getVoiceContext()));
          } else if (data.type === 'partial') {
            setAssistantText(data.text);
            setSheetState('response');
            lastActivityRef.current = Date.now();
          } else if (data.type === 'transcript') {
            lastRealTranscriptRef.current = data.text;
            setLiveTranscript(data.text);
            lastActivityRef.current = Date.now();
          } else if (data.type === 'status') {
            if (data.status === 'processing') setOrbState('thinking');
          } else if (data.type === 'proactive') {
            if (data.text) {
              pushConversation('assistant', data.text);
              setAssistantText(data.text);
              setSheetState('response');
              lastActivityRef.current = Date.now();
            }
          } else if (data.type === 'audio_queue') {
            pendingSegmentsRef.current = data.count ?? 0;
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
          } else if (data.type === 'confirmations') {
            const confirmations = data.confirmations || {};
            const keys = Object.keys(confirmations);
            if (keys.length > 0) {
              const first = confirmations[keys[0]];
              setActiveConfirmation({
                tool: first.tool || keys[0],
                prompt: first.confirmation_prompt || data.message || 'Please confirm this action.',
              });
            }
          } else if (data.type === 'voice_status') {
            // Microphone-cycle statuses (e.g. no-speech) are subtle and
            // non-blocking: they never raise the red error card, never attach
            // to a completed command's result, and never interrupt playback.
            if (data.status === 'no_speech') {
              showMicNotice(String(data.message || "I didn't catch that. Try again."));
            }
          } else if (data.type === 'error') {
            // Native microphone/STT errors arrive over this same socket, but they
            // are not network failures. Preserve the recognizer's useful message
            // instead of translating it into a misleading "Network error".
            const nativeMic = settingsRef.current.voiceMode === 'native';
            const nativeMessage = String(data.message || 'Microphone/audio error');
            // Defensive: a no-speech message that still arrives as type "error"
            // (e.g. from an older backend) must degrade to a subtle mic notice,
            // not a red error card.
            const looksLikeNoSpeech =
              /no speech was recognized|didn't catch any audio|could not hear any speech/i.test(
                nativeMessage,
              );
            if (looksLikeNoSpeech && data.error_scope !== 'stream') {
              showMicNotice("I didn't catch that. Try again.");
              return;
            }
            const message = nativeMic
              ? nativeMessage
              : handleVoiceError('ws', data.message, 'Connection error');
            setError(message);
            setOrbState('idle');
            stopPlayback();
            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            setSheetState('hidden');
            _setVoiceMachineState((prev) =>
              transition(prev, nativeMic ? 'mic_denied' : 'ws_failed', getVoiceContext()),
            );
          }
        };
        ws.current.onerror = () => {
          const message = handleVoiceError(
            'ws',
            new Error('WebSocket connection error'),
            'Connection error',
          );
          stopPlayback();
          setError(message);
          isConnectedRef.current = false;
          setIsProcessing(false);
          _setVoiceMachineState((prev) => transition(prev, 'ws_failed', getVoiceContext()));
        };
        ws.current.onclose = () => {
          isConnectedRef.current = false;
          stopPlayback();
          setIsProcessing(false);
          setIsListening(false);
          nativeListeningRef.current = false;
          nativeReadyRef.current = false;
          if (orbStateRef.current === 'listening') {
            setOrbState('idle');
          }
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
    let raf: number | undefined;
    let idleTimer: ReturnType<typeof setInterval> | undefined;
    let last = 0;
    const audioReactiveTick = () => {
      const active = listeningRef.current || orbStateRef.current === 'speaking';
      if (!active) {
        // Nothing to animate: stop the rAF loop entirely and only poll at a
        // low rate until listening/speaking resumes.
        raf = undefined;
        idleTimer = setInterval(() => {
          if (listeningRef.current || orbStateRef.current === 'speaking') {
            if (idleTimer) clearInterval(idleTimer);
            idleTimer = undefined;
            raf = requestAnimationFrame(audioReactiveTick);
          }
        }, 250);
        return;
      }
      const now = performance.now();
      // Throttle audio-reactive level updates to ~20 Hz so the renderer is not
      // re-rendered every animation frame while the assistant is active.
      if (now - last > 50 && analysers.current[0]) {
        last = now;
        const data = new Uint8Array(analysers.current[0].frequencyBinCount);
        analysers.current[0].getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        setRms(Math.sqrt(sum / data.length) / 255);
      }
      raf = requestAnimationFrame(audioReactiveTick);
    };
    raf = requestAnimationFrame(audioReactiveTick);
    return () => {
      if (raf !== undefined) cancelAnimationFrame(raf);
      if (idleTimer !== undefined) clearInterval(idleTimer);
    };
  }, []);

  const listeningRef = useRef(isListening);
  const processingRef = useRef(isProcessing);
  const toggleCooldownRef = useRef(0);
  listeningRef.current = isListening;
  processingRef.current = isProcessing;

  const sendPrompt = useCallback(
    async (raw: string) => {
      const prompt = raw.trim();
      if (!prompt || isTextSubmitting || isProcessing) return;
      lastPromptRef.current = prompt;
      lastUserPushedRef.current = prompt;
      lastRealTranscriptRef.current = '';
      setTypedPrompt('');
      setLiveTranscript('');
      setAssistantText('');
      setError(null);
      pushConversation('user', prompt);
      setIsTextSubmitting(true);
      setIsProcessing(true);
      setOrbState('thinking');
      try {
        const token = await getSessionToken();
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers['X-Jarvis-Token'] = token;
        const session_id = localStorage.getItem('jarvis_chat_session') || undefined;
        // Bound the request so the UI can never hang in "thinking" forever if
        // the backend (or its LLM) stalls.  Desktop commands return in ~1s via
        // deterministic routing; a normal LLM-only query stays well under this.
        const response = await withTimeout(
          fetch('/api/chat', {
            method: 'POST',
            headers,
            body: JSON.stringify({ message: prompt, session_id }),
          }),
          60000,
          'JARVIS took too long to respond. Please try again.',
        );
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail || 'JARVIS could not answer right now.');
        if (payload.session_id) localStorage.setItem('jarvis_chat_session', payload.session_id);
        const reply = String(payload.text || 'I could not generate an answer.');
        const verifiedNotes = summarizeVerifiedTools(payload.tool_results, reply);
        const display = verifiedNotes.length ? `${reply}\n\n${verifiedNotes.join('\n')}` : reply;
        setAssistantText(display);
        pushConversation('assistant', display);
        // The typed path produces text only (no TTS audio), so never mark the
        // orb as speaking here. Drop to idle unless audio is still playing.
        if (audioQueueRef.current.length === 0 && !isPlayingAudioRef.current) {
          setOrbState('idle');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'JARVIS could not answer right now.');
        setOrbState('idle');
      } finally {
        setIsTextSubmitting(false);
        setIsProcessing(false);
      }
    },
    [isTextSubmitting, isProcessing, pushConversation, getSessionToken],
  );

  const submitTypedPrompt = useCallback(
    (event: React.FormEvent) => {
      event.preventDefault();
      void sendPrompt(typedPrompt);
    },
    [typedPrompt, sendPrompt],
  );

  const retryLastPrompt = useCallback(() => {
    if (!lastPromptRef.current) return;
    void sendPrompt(lastPromptRef.current);
  }, [sendPrompt]);

  const toggleTalk = useCallback(async () => {
    console.log(
      '[voice] toggleTalk called, processing=',
      processingRef.current,
      'listening=',
      listeningRef.current,
      'nativeListening=',
      nativeListeningRef.current,
    );
    if (processingRef.current) return;
    const now = Date.now();
    if (now - toggleCooldownRef.current < 800) return;
    toggleCooldownRef.current = now;
    if (settingsRef.current.voiceMode === 'native') {
      const socket = ws.current;
      console.log('[voice] native mode, socket readyState=', socket?.readyState);
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      if (listeningRef.current || nativeListeningRef.current) {
        console.log('[voice] stopping listening');
        socket.send(JSON.stringify({ type: 'stop_listening' }));
        nativeListeningRef.current = false;
        setIsListening(false);
        setOrbState('thinking');
        setIsProcessing(true);
        requestStartRef.current = Date.now();
        startProcessingWatchdogRef.current();
        return;
      }
      console.log('[voice] starting listening');
      stopPlayback();
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
  }, [stopPlayback]);

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
    stopPlayback();
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
      console.log('[shortcut] voice-control received:', action);
      if (action === 'toggle' || action === 'start') {
        console.log('[shortcut] invoking toggleTalk');
        toggleTalk();
      } else if (action === 'stop') {
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

  // Web Audio playback. HTMLMediaElement (`new Audio`) fails to load ANY audio
  // resource in this Electron window (MEDIA_ERR_SRC_NOT_SUPPORTED) while the
  // Web Audio stack decodes and plays WAV/MP3 reliably, so playback routes
  // through AudioContext. The single queue/guard is unchanged.
  const playNextAudio = useCallback(async () => {
    if (isPlayingAudioRef.current) return;
    const ctx = audioContext.current;
    if (!ctx) {
      setError('Voice unavailable');
      return;
    }
    const next = audioQueueRef.current.shift();
    if (!next) {
      setOrbState('idle');
      return;
    }
    try {
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch {
          /* resume can reject when there is no output device */
        }
      }
      if (ctx.state !== 'running') {
        setError('Voice unavailable (no audio output device).');
        playNextAudio();
        return;
      }
      let bytes = Uint8Array.from(atob(next), (c) => c.charCodeAt(0));
      let buffer: AudioBuffer | null = null;
      try {
        buffer = await ctx.decodeAudioData(bytes.buffer);
      } catch (decodeErr) {
        // The backend emits exactly one complete file per segment, but if a
        // concatenated RIFF/WAV blob slips through (older backend, third-party
        // client), split on RIFF headers and decode the first complete file
        // instead of feeding incompatible audio to the decoder.
        bytes = Uint8Array.from(atob(next), (c) => c.charCodeAt(0));
        const riffOffsets: number[] = [];
        for (let i = 0; i + 4 <= bytes.length; i += 1) {
          if (
            bytes[i] === 0x52 &&
            bytes[i + 1] === 0x49 &&
            bytes[i + 2] === 0x46 &&
            bytes[i + 3] === 0x46
          ) {
            riffOffsets.push(i);
          }
        }
        for (let i = 0; i < riffOffsets.length && !buffer; i += 1) {
          try {
            buffer = await ctx.decodeAudioData(bytes.buffer.slice(riffOffsets[i]));
          } catch {
            /* try the next complete file */
          }
        }
        if (!buffer) throw decodeErr;
      }
      if (!buffer || buffer.length === 0 || buffer.duration <= 0) {
        throw new Error('empty audio buffer');
      }
      isPlayingAudioRef.current = true;
      setOrbState('speaking');
      logVoice('speaking', {
        level: 'debug',
        bytes: bytes.byteLength,
        duration_s: Math.round(buffer.duration * 1000) / 1000,
        sample_rate: buffer.sampleRate,
        channels: buffer.numberOfChannels,
      });
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = Math.max(settings.speed, 0.1);
      const gain = ctx.createGain();
      gain.gain.value = settings.volume;
      source.connect(gain);
      gain.connect(ctx.destination);
      playbackSourceRef.current = source;
      const startedAt = Date.now();
      source.onended = () => {
        if (playbackTimerRef.current) clearTimeout(playbackTimerRef.current);
        if (playbackSourceRef.current === source) playbackSourceRef.current = null;
        if (isPlayingAudioRef.current) {
          logVoice('speaking_end', {
            level: 'debug',
            played_ms: Date.now() - startedAt,
          });
        }
        isPlayingAudioRef.current = false;
        playNextAudio();
      };
      const expectedMs = (buffer.duration / Math.max(settings.speed, 0.1)) * 1000;
      playbackTimerRef.current = setTimeout(() => {
        // Watchdog: if `onended` never fired (node GC'd / interrupted), release
        // the pipeline so the queue can never stall waiting for an end event.
        if (isPlayingAudioRef.current && playbackSourceRef.current === source) {
          logVoice('error', {
            level: 'warn',
            stage: 'audio_context',
            code: 'playback_end_timeout',
            message: 'playback end event never fired; releasing queue',
          });
          try {
            source.stop();
          } catch {
            /* already stopped */
          }
          playbackSourceRef.current = null;
          isPlayingAudioRef.current = false;
          playNextAudio();
        }
      }, expectedMs + 1500);
      source.start();
    } catch (err) {
      isPlayingAudioRef.current = false;
      if (playbackTimerRef.current) clearTimeout(playbackTimerRef.current);
      logVoice('error', {
        level: 'error',
        stage: 'audio_context',
        code: (err as Error)?.name || 'decode_failed',
        message: (err as Error)?.message || 'Failed to decode or play audio',
      });
      setError("I couldn't play the response.");
      playNextAudio();
    }
  }, [settings.volume, settings.speed, logVoice]);

  const enqueueAudio = useCallback(
    (audioBase64: string) => {
      audioQueueRef.current.push(audioBase64);
      void playNextAudio();
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

  // Native Electron dragging. The outer `.bubble-container` is a
  // `-webkit-app-region: drag` region, so the OS/compositor moves the window
  // directly — no JS drag loop and no per-frame setPosition. The main process
  // reports drag state so nonessential CSS animations pause while moving.
  useEffect(() => {
    const api = getElectronAPI();
    const unsub = api?.onWindowDragState?.(setWindowDragging);
    return () => unsub?.();
  }, []);

  // The visible bubble is a `-webkit-app-region: no-drag` click target. A
  // native drag can only ever start on the surrounding drag region, so a click
  // reaching this handler is always a genuine click (never a drag).
  const handleOrbBubbleClick = useCallback(() => {
    openPanel();
  }, [openPanel]);

  const handleOrbContextMenu = useCallback(() => {
    getElectronAPI()?.showContextMenu?.();
  }, []);

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
    let pushToTalkActive = false;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return;
      if (e.ctrlKey && e.code === 'Space') {
        e.preventDefault();
        if (!isElectron && !pushToTalkActive) {
          pushToTalkActive = true;
          toggleTalk();
        }
        return;
      }
      if (e.key === 'Escape' && panelOpen) {
        handlePanelClose();
      }
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (pushToTalkActive && (e.code === 'Space' || e.key === 'Control')) {
        e.preventDefault();
        pushToTalkActive = false;
        if (!isElectron && listeningRef.current) toggleTalk();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
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
        };
      }
      // Orb mode: the bubble container fills the 72×72 window exactly and the
      // orb is flex-centered — no transforms on the drag surface.
      return { position: 'absolute' as const, inset: 0 };
    }
    return {
      position: 'absolute' as const,
      left: orbPosition.x,
      top: orbPosition.y,
      transform: 'translate(-50%, -50%)',
    };
  }, [isElectron, windowMode, orbPosition]);

  useEffect(() => {
    conversationEndRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' });
  }, [conversation, liveTranscript, assistantText, isProcessing, error]);

  const showTransientHud = !isElectron || windowMode === 'panel';
  const showMainUi = !isElectron || windowMode === 'panel';

  const headerStatus = isProcessing
    ? { label: 'Thinking…', cls: 'is-processing' }
    : isListening
      ? { label: isEndpointing ? 'Finishing up…' : 'Listening…', cls: 'is-listening' }
      : orbState === 'speaking'
        ? { label: 'Speaking…', cls: 'is-speaking' }
        : { label: 'JARVIS ready', cls: '' };

  const lastConversation = conversation[conversation.length - 1];
  const livePlaceholders = ['Listening...', 'Recording...', 'Transcribing...'];
  const liveUserShown =
    !!liveTranscript &&
    !livePlaceholders.includes(liveTranscript.trim()) &&
    !(lastConversation?.role === 'user' && lastConversation.text === liveTranscript.trim());
  const liveAssistantShown =
    !!assistantText &&
    !(lastConversation?.role === 'assistant' && lastConversation.text === assistantText.trim());

  return (
    <ToastProvider>
      <ErrorBoundary>
        <div
          className={`app ${isElectron ? 'app-electron' : ''} ${showMainUi ? 'main-ui' : ''} ${windowMode === 'panel' ? 'panel-mode' : ''} ${isElectron && windowMode === 'orb' ? 'orb-mode' : ''}`}
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
          {showMainUi && (
            <header className="main-header">
              <div className="main-header-orb">
                <MinimalBubble
                  state={effectiveOrbState}
                  audioLevel={rms}
                  onToggle={handlePanelClose}
                />
              </div>
              <span className={`main-header-dot ${headerStatus.cls}`} aria-hidden="true" />
              <span className="main-header-status" aria-live="polite">
                {headerStatus.label}
              </span>
              {isElectron && (
                <button
                  type="button"
                  className="main-header-collapse"
                  onClick={handlePanelClose}
                  aria-label="Minimize JARVIS to orb mode"
                  title="Minimize to orb"
                >
                  —
                </button>
              )}
            </header>
          )}
          <main className="app-main">
            <div className={`bubble-container ${windowDragging ? 'bubble-dragging' : ''}`}>
              <div
                className={`orb-anchor ${isListening ? 'recording' : ''} ${windowMode === 'panel' ? 'orb-anchor-hidden' : ''}`}
                style={orbAnchorStyle as React.CSSProperties}
                onContextMenu={(e) => {
                  e.preventDefault();
                  handleOrbContextMenu();
                }}
              >
                <MinimalBubble
                  state={effectiveOrbState}
                  audioLevel={rms}
                  onToggle={handleOrbBubbleClick}
                />
              </div>
            </div>

            {showMainUi && (
              <section className="conversation" aria-label="Conversation" aria-live="polite">
                <div className="conversation-inner">
                  {conversation.length === 0 &&
                    !liveTranscript &&
                    !assistantText &&
                    !isProcessing &&
                    !error && (
                      <div className="conversation-empty">
                        Ask JARVIS anything, or press Ctrl+Space to talk.
                      </div>
                    )}
                  {conversation.map((message, i) => (
                    <div key={i} className={`conversation-message ${message.role}`}>
                      <span className="conversation-message-role">
                        {message.role === 'user' ? 'You' : 'JARVIS'}
                      </span>
                      <div className="conversation-message-text">{message.text}</div>
                    </div>
                  ))}
                  {liveUserShown && (
                    <div className="conversation-message user">
                      <span className="conversation-message-role">You</span>
                      <div className="conversation-message-text">{liveTranscript}</div>
                    </div>
                  )}
                  {liveAssistantShown && (
                    <div className="conversation-message assistant">
                      <span className="conversation-message-role">JARVIS</span>
                      <div className="conversation-message-text">{assistantText}</div>
                    </div>
                  )}
                  {isProcessing && !assistantText && (
                    <div className={`conversation-status ${isListening ? 'listening' : ''}`}>
                      {isListening ? 'Listening…' : 'JARVIS is thinking…'}
                    </div>
                  )}
                  {isListening && !liveTranscript && !isProcessing && (
                    <div className="conversation-status listening">Listening…</div>
                  )}
                  {error && (
                    <div className="conversation-error" role="alert" aria-live="assertive">
                      <span className="conversation-error-title">Something went wrong</span>
                      <div className="conversation-error-text">{error}</div>
                      <button
                        type="button"
                        onClick={retryLastPrompt}
                        disabled={isTextSubmitting || isProcessing}
                      >
                        Retry
                      </button>
                    </div>
                  )}
                  <div ref={conversationEndRef} />
                </div>
              </section>
            )}

            {!showMainUi && (
              <Panel
                open={panelOpen}
                view={panelView}
                onViewChange={handlePanelViewChange}
                onClose={handlePanelClose}
                orbPosition={orbPosition}
                onToggleTalk={handlePanelToggleTalk}
                settings={settings}
                onSaveSettings={(next) => {
                  setSettings(next);
                  try {
                    localStorage.setItem('voiceSettings', JSON.stringify(next));
                    window.dispatchEvent(new CustomEvent('jarvis-settings-change'));
                  } catch {
                    /* ignore */
                  }
                }}
                fillWindow={isElectron}
              />
            )}
          </main>

          {showMainUi && (
            <footer className="composer">
              {micNotice && (
                <div className="mic-notice" role="status" aria-live="polite">
                  {micNotice}
                </div>
              )}
              <button
                type="button"
                className={`composer-mic ${isListening ? 'is-listening' : ''}`}
                onClick={toggleTalk}
                disabled={isProcessing}
                aria-label={isListening ? 'Stop listening' : 'Start listening'}
                title={isListening ? 'Stop listening' : 'Start listening (Ctrl+Space)'}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <rect x="9" y="2" width="6" height="12" rx="3" />
                  <path d="M5 10v1a7 7 0 0 0 14 0v-1" />
                  <line x1="12" y1="18" x2="12" y2="22" />
                  <line x1="8" y1="22" x2="16" y2="22" />
                </svg>
              </button>
              <form className="composer-form" onSubmit={submitTypedPrompt}>
                <input
                  value={typedPrompt}
                  onChange={(event) => setTypedPrompt(event.target.value)}
                  placeholder="Ask JARVIS anything…"
                  aria-label="Ask JARVIS anything"
                  disabled={isTextSubmitting || isProcessing}
                />
                <button
                  type="submit"
                  aria-label="Send message"
                  disabled={!typedPrompt.trim() || isTextSubmitting || isProcessing}
                >
                  ↵
                </button>
              </form>
            </footer>
          )}

          {showTransientHud && activeConfirmation && (
            <div className="confirmation-dialog" role="dialog" aria-live="assertive">
              <p>{activeConfirmation.prompt}</p>
              <div className="confirmation-actions">
                <button onClick={() => sendConfirmation(activeConfirmation.tool, true)}>
                  Confirm
                </button>
                <button onClick={() => sendConfirmation(activeConfirmation.tool, false)}>
                  Cancel
                </button>
              </div>
            </div>
          )}

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
