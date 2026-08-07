import React, { useState, useEffect, useRef, useCallback, Suspense, lazy } from 'react';
import './App.css';
import VoiceOrb from './components/VoiceOrb';
import Onboarding from './components/Onboarding';
import { createPcm16Resampler, uint8ToBase64 } from './audioStream';
import type { Resampler } from './audioStream';

const Settings = lazy(() => import('./components/Settings'));
const MemoryPage = lazy(() => import('./components/MemoryPage'));

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

type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking';
type SheetState = 'hidden' | 'transcript' | 'response';

type SettingsState = {
  voice: string;
  volume: number;
  speed: number;
  theme: string;
  enableNotifications: boolean;
  serverUrl: string;
  enableWakeWord: boolean;
};

type EmailConfig = {
  email: string;
  appPassword: string;
  sessionToken: string | null;
};

function App() {
  const [isListening, setIsListening] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [orbState, setOrbState] = useState<OrbState>('idle');
  const [showSettings, setShowSettings] = useState(false);
  const [showMemory, setShowMemory] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(() => {
    return localStorage.getItem('jarvisOnboarded') !== 'true';
  });
  const [sheetState, setSheetState] = useState<SheetState>('hidden');
  const [liveTranscript, setLiveTranscript] = useState('');
  const [assistantText, setAssistantText] = useState('');
  const [textInput, setTextInput] = useState('');
  const [settings, setSettings] = useState<SettingsState>(() => ({
    voice: 'en-US',
    volume: 0.8,
    speed: 1.0,
    theme: 'dark',
    enableNotifications: true,
    serverUrl: localStorage.getItem('serverUrl') || 'localhost:8000',
    enableWakeWord: true,
  }));
  const [emailConfig, setEmailConfig] = useState<EmailConfig>(() => ({
    email: localStorage.getItem('emailAddress') || '',
    appPassword: '',
    sessionToken: localStorage.getItem('emailSessionToken') || null,
  }));

  const ws = useRef<WebSocket | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const analysers = useRef<Array<AnalyserNode>>([]);
  const audioChunksRef = useRef<string[]>([]);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingAudioRef = useRef(false);
  const enqueueAudioRef = useRef<(audioBase64: string) => void>(() => {});
  const lastActivityRef = useRef(Date.now());
  const collapseTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const streamRef = useRef<MediaStream | null>(null);
  const isConnectedRef = useRef(false);
  const audioSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const audioProcessorRef = useRef<ScriptProcessorNode | null>(null);
  const resamplerRef = useRef<Resampler | null>(null);
  const processingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const micPermissionGrantedRef = useRef(false);
  const micBusyRef = useRef(false);
  const awaitingPongRef = useRef(false);
  const pingSentAtRef = useRef(0);

  const getSessionToken = async (): Promise<string | null> => {
    const api = (window as any).electronAPI;
    if (!api?.getSessionToken) return null;
    try {
      return (await api.getSessionToken()) as string | null;
    } catch (err) {
      console.error('Failed to get session token', err);
      return null;
    }
  };

  const resolveWebSocketUrl = (server: string, token: string | null) => {
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
    if (token) {
      url += `?token=${encodeURIComponent(token)}`;
    }
    return url;
  };

  const resetCollapseTimer = useCallback(() => {
    lastActivityRef.current = Date.now();
    if (collapseTimerRef.current) {
      clearTimeout(collapseTimerRef.current);
    }
  }, []);

  const tryCollapseSheet = useCallback(() => {
    if (sheetState === 'hidden') return;
    if (isProcessing || isListening) return;
    if (Date.now() - lastActivityRef.current < 4000) return;
    setSheetState('hidden');
    setLiveTranscript('');
    setAssistantText('');
  }, [sheetState, isProcessing, isListening]);

  useEffect(() => {
    if (sheetState === 'hidden') return;
    const timer = setInterval(tryCollapseSheet, 1000);
    return () => clearInterval(timer);
  }, [sheetState, tryCollapseSheet]);

  const withTimeout = <T,>(promise: Promise<T>, ms: number, message: string): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(message)), ms);
      promise.then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (err) => {
          clearTimeout(timer);
          reject(err);
        },
      );
    });

  const tryGetUserMedia = async (constraints: MediaStreamConstraints): Promise<MediaStream> => {
    try {
      return await withTimeout(
        navigator.mediaDevices.getUserMedia(constraints),
        6000,
        'Microphone timed out opening the audio device',
      );
    } catch (err) {
      const name = (err as any)?.name || '';
      const message = (err as Error)?.message || '';
      const processingFailed =
        name === 'OverconstrainedError' || name === 'TimeoutError' || message.includes('timed out');
      if (processingFailed && typeof constraints.audio === 'object') {
        console.warn('Mic open failed with processing constraints, retrying plain audio', err);
        return withTimeout(
          navigator.mediaDevices.getUserMedia({ audio: true }),
          6000,
          'Microphone timed out opening the audio device',
        );
      }
      throw err;
    }
  };

  const ensureMicPermission = useCallback(async (): Promise<boolean> => {
    if (micPermissionGrantedRef.current) {
      return true;
    }
    try {
      if (navigator.permissions && (navigator.permissions as any).query) {
        try {
          const result = await (navigator.permissions as any).query({ name: 'microphone' });
          if (result.state === 'granted') {
            micPermissionGrantedRef.current = true;
            return true;
          }
          // 'prompt' or 'denied' → still try a real capture probe below; the OS
          // prompt (or Electron's permission handler) decides the outcome.
        } catch (permErr) {
          console.warn('Permissions API query failed', permErr);
        }
      }
      const stream = await tryGetUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      micPermissionGrantedRef.current = true;
      return true;
    } catch (err) {
      console.error('Microphone permission check failed', err);
      setError(
        'Microphone access denied or unavailable. Check that a microphone is connected and JARVIS is allowed to use it.',
      );
      return false;
    }
  }, []);

  useEffect(() => {
    let reconnectDelay = 1000;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      if (ws.current && ws.current.readyState === WebSocket.OPEN) {
        return;
      }
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
        const url = resolveWebSocketUrl(settings.serverUrl, token);
        ws.current = new WebSocket(url);

        ws.current.onopen = () => {
          isConnectedRef.current = true;
          awaitingPongRef.current = false;
          setError(null);
          reconnectDelay = 1000;
        };

        ws.current.onmessage = (event) => {
          let data: any;
          try {
            data = JSON.parse(event.data);
          } catch (err) {
            setError('Received invalid data from server');
            return;
          }

          if (data.type === 'pong') {
            awaitingPongRef.current = false;
          } else if (data.type === 'response') {
            setAssistantText(data.text);
            setSheetState('response');
            resetCollapseTimer();

            if (data.audio) {
              enqueueAudioRef.current(data.audio);
            }

            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            processingRef.current = false;
          } else if (data.type === 'partial') {
            setAssistantText(data.text);
            setSheetState('response');
            resetCollapseTimer();
          } else if (data.type === 'status') {
            if (data.status === 'processing') {
              setOrbState('thinking');
            } else if (data.status === 'generating_speech') {
              setOrbState('speaking');
            }
          } else if (data.type === 'audio_queue') {
            setOrbState('speaking');
          } else if (data.type === 'audio_segment_start') {
            audioChunksRef.current = [];
          } else if (data.type === 'audio_chunk') {
            if (data.chunk) {
              audioChunksRef.current.push(data.chunk);
            }
          } else if (data.type === 'audio_segment_end') {
            const combined = audioChunksRef.current.join('');
            audioChunksRef.current = [];
            if (combined) {
              enqueueAudioRef.current(combined);
            }
          } else if (data.type === 'error') {
            setError(data.message);
            setOrbState('idle');
            if (processingTimerRef.current) {
              clearTimeout(processingTimerRef.current);
              processingTimerRef.current = undefined;
            }
            setIsProcessing(false);
            processingRef.current = false;
            setSheetState('hidden');
          }
        };

        ws.current.onerror = () => {
          console.error('WebSocket error');
          setError('Connection error');
          isConnectedRef.current = false;
          setIsProcessing(false);
          processingRef.current = false;
        };

        ws.current.onclose = () => {
          isConnectedRef.current = false;
          // If the socket dies while a request is in flight, do not leave the
          // UI stuck in "processing" (silently blocking future taps).
          setIsProcessing(false);
          processingRef.current = false;
          if (reconnectTimer) {
            clearTimeout(reconnectTimer);
          }
          reconnectTimer = setTimeout(() => {
            reconnectDelay = Math.min(reconnectDelay * 2, 60000);
            const jitter = Math.random() * 0.3 + 0.85;
            const nextDelay = Math.min(Math.floor(reconnectDelay * jitter), 60000);
            reconnectDelay = nextDelay;
            connect();
          }, reconnectDelay);
        };
      } catch (err) {
        setError('Failed to connect to server');
      }
    };

    connect();

    const interval = setInterval(() => {
      if (!isConnectedRef.current && !reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, 60000);
          connect();
        }, reconnectDelay);
      }
    }, 5000);

    // Heartbeat: send a ping every 25 s and force a reconnect if the server
    // does not answer within 15 s (detects half-open connections).
    const pingInterval = setInterval(() => {
      const socket = ws.current;
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }
      if (awaitingPongRef.current && Date.now() - pingSentAtRef.current > 15000) {
        console.error('WebSocket heartbeat timed out; forcing reconnect');
        socket.close();
        return;
      }
      try {
        socket.send(JSON.stringify({ type: 'ping' }));
        awaitingPongRef.current = true;
        pingSentAtRef.current = Date.now();
      } catch (err) {
        console.error('Failed to send heartbeat ping', err);
      }
    }, 25000);

    return () => {
      clearInterval(interval);
      clearInterval(pingInterval);
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [settings.serverUrl, resetCollapseTimer]);

  useEffect(() => {
    const initAudio = async () => {
      try {
        audioContext.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      } catch (err) {
        setError('Audio context not supported');
      }
    };
    initAudio();
  }, []);

  useEffect(() => {
    return () => {
      if (recordingTimerRef.current) {
        clearTimeout(recordingTimerRef.current);
      }
      if (processingTimerRef.current) {
        clearTimeout(processingTimerRef.current);
      }
      if (audioProcessorRef.current) {
        audioProcessorRef.current.onaudioprocess = null;
        try {
          audioProcessorRef.current.disconnect();
        } catch (err) {
          console.warn('Failed to stop audio processor on unmount', err);
        }
        audioProcessorRef.current = null;
      }
      if (audioSourceRef.current) {
        try {
          audioSourceRef.current.disconnect();
        } catch (err) {
          console.warn('Failed to disconnect audio source on unmount', err);
        }
        audioSourceRef.current = null;
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track: MediaStreamTrack) => track.stop());
      }
      if (audioContext.current && audioContext.current.state !== 'closed') {
        audioContext.current.close().catch(() => {});
      }
    };
  }, []);

  const listeningRef = useRef(isListening);
  const processingRef = useRef(isProcessing);

  listeningRef.current = isListening;
  processingRef.current = isProcessing;

  const triggerWakeWord = useCallback(async () => {
    if (listeningRef.current || processingRef.current) {
      return;
    }
    await beginVoiceSession();
  }, []);

  useEffect(() => {
    const api = (window as any).electronAPI;
    if (!api?.onWakeWordDetected) return;

    const handler = () => {
      if (listeningRef.current || processingRef.current) return;
      triggerWakeWord();
    };

    const unsubscribe = api.onWakeWordDetected(handler);
    return () => {
      if (typeof unsubscribe === 'function') {
        unsubscribe();
      }
    };
  }, [triggerWakeWord]);

  const sendAudioStart = () => {
    const socket = ws.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        type: 'audio_start',
        format: 'pcm16',
        sample_rate: 16000,
        channels: 1,
      }),
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

  const startRecording = async () => {
    try {
      const stream = await tryGetUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      setIsListening(true);
      listeningRef.current = true;
      setOrbState('listening');
      setLiveTranscript('Recording... tap the orb again to send');
      setSheetState('transcript');
      resetCollapseTimer();

      let ctx = audioContext.current;
      if (!ctx || ctx.state === 'closed') {
        ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        audioContext.current = ctx;
      }
      if (ctx.state === 'suspended') {
        ctx.resume().catch(() => {});
      }

      // Stream PCM16 (16 kHz mono) to the backend as the user speaks instead of
      // buffering a huge blob and converting it after the fact.
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      const resampler = createPcm16Resampler(16000, ctx.sampleRate);
      source.connect(processor);
      processor.connect(ctx.destination);

      const analyser = ctx.createAnalyser();
      source.connect(analyser);
      analysers.current = [analyser];

      sendAudioStart();
      processor.onaudioprocess = (e: AudioProcessingEvent) => {
        const input = e.inputBuffer.getChannelData(0);
        const pcm = resampler.process(input);
        if (pcm.length > 0) {
          sendAudioChunk(pcm);
        }
      };

      audioSourceRef.current = source;
      audioProcessorRef.current = processor;
      resamplerRef.current = resampler;

      // Safety: never record forever. Auto-stop after 30 seconds.
      if (recordingTimerRef.current) {
        clearTimeout(recordingTimerRef.current);
      }
      recordingTimerRef.current = setTimeout(() => {
        if (audioProcessorRef.current) {
          stopManualRecording();
        }
      }, 30000);
    } catch (err) {
      console.error('Failed to start microphone recording', err);
      setError(
        'Could not start the microphone. Check that a microphone is connected and JARVIS has permission to use it.',
      );
      setOrbState('idle');
      setIsListening(false);
      listeningRef.current = false;
      analysers.current = [];
      setSheetState('hidden');
    }
  };

  const cleanupListening = (stream: MediaStream | null) => {
    if (recordingTimerRef.current) {
      clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = undefined;
    }
    if (audioProcessorRef.current) {
      audioProcessorRef.current.onaudioprocess = null;
      audioProcessorRef.current.disconnect();
      audioProcessorRef.current = null;
    }
    if (audioSourceRef.current) {
      try {
        audioSourceRef.current.disconnect();
      } catch (err) {
        console.warn('Failed to disconnect audio source', err);
      }
      audioSourceRef.current = null;
    }
    resamplerRef.current = null;
    if (stream) {
      stream.getTracks().forEach((track: MediaStreamTrack) => track.stop());
    }
    streamRef.current = null;
    analysers.current = [];
  };

  const stopManualRecording = async () => {
    const stream = streamRef.current;
    if (!audioProcessorRef.current && !stream) {
      setIsListening(false);
      listeningRef.current = false;
      setOrbState('idle');
      setSheetState('hidden');
      return;
    }

    setIsListening(false);
    listeningRef.current = false;

    // Flush any resampler output buffered since the last onaudioprocess pass.
    try {
      if (resamplerRef.current) {
        const tail = resamplerRef.current.finish();
        if (tail.length > 0) {
          sendAudioChunk(tail);
        }
      }
    } catch (err) {
      console.error('Failed to flush audio buffer', err);
    }

    sendAudioEnd();
    cleanupListening(stream);

    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      setError('Not connected to server');
      setSheetState('hidden');
      return;
    }

    setOrbState('thinking');
    setLiveTranscript('Transcribing...');
    setIsProcessing(true);
    processingRef.current = true;
    startProcessingWatchdog();
  };

  const beginVoiceSession = async () => {
    if (processingRef.current || listeningRef.current || micBusyRef.current) {
      return;
    }
    micBusyRef.current = true;
    try {
      const hasPermission = await ensureMicPermission();
      if (!hasPermission) return;
      if (navigator.vibrate) {
        navigator.vibrate(50);
      }
      setSheetState('transcript');
      resetCollapseTimer();
      await startRecording();
    } finally {
      micBusyRef.current = false;
    }
  };

  const toggleTalk = useCallback(async () => {
    if (processingRef.current) return;
    if (listeningRef.current) {
      await stopManualRecording();
      return;
    }
    await beginVoiceSession();
  }, [stopManualRecording]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.repeat) return;
      if (e.code === 'Space' || e.key === ' ') {
        const target = e.target as HTMLElement | null;
        if (
          target &&
          (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)
        ) {
          return;
        }
        e.preventDefault();
        toggleTalk();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleTalk]);

  const startProcessingWatchdog = () => {
    if (processingTimerRef.current) {
      clearTimeout(processingTimerRef.current);
    }
    processingTimerRef.current = setTimeout(() => {
      if (processingRef.current) {
        console.error('Processing watchdog fired: no reply within 45s');
        setIsProcessing(false);
        processingRef.current = false;
        setOrbState('idle');
        setError('The assistant took too long to respond. Please try again.');
      }
    }, 45000);
  };

  const sendMessage = async (content: string) => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      setError('Not connected to server');
      setSheetState('hidden');
      return;
    }

    try {
      setIsProcessing(true);
      processingRef.current = true;
      setOrbState('thinking');
      resetCollapseTimer();
      startProcessingWatchdog();

      ws.current.send(
        JSON.stringify({
          type: 'text',
          content,
        }),
      );
    } catch (err) {
      console.error('Failed to send message', err);
      setError('Failed to send message');
      setIsProcessing(false);
      processingRef.current = false;
      setOrbState('idle');
      setSheetState('hidden');
    }
  };

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
    } catch (err) {
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

  const handleSaveSettings = (updatedSettings: SettingsState, updatedEmailConfig: EmailConfig) => {
    setSettings(updatedSettings);
    setEmailConfig(updatedEmailConfig);

    localStorage.setItem('voiceSettings', JSON.stringify(updatedSettings));
    localStorage.setItem('serverUrl', updatedSettings.serverUrl);
    localStorage.setItem('emailAddress', updatedEmailConfig.email);

    if (showOnboarding) {
      localStorage.setItem('jarvisOnboarded', 'true');
      setShowOnboarding(false);
    }

    if (updatedEmailConfig.email && updatedEmailConfig.appPassword && updatedSettings.serverUrl) {
      const apiUrl = updatedSettings.serverUrl.trim();
      const baseUrl = apiUrl.startsWith('http') ? apiUrl : `http://${apiUrl}`;
      fetch(`${baseUrl}/api/mail/auth`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: updatedEmailConfig.email,
          password: updatedEmailConfig.appPassword,
        }),
      })
        .then((res) => {
          if (!res.ok) {
            console.warn('Mail auth request failed:', res.status, res.statusText);
            return;
          }
          return res.json();
        })
        .then((data) => {
          if (data && data.token) {
            localStorage.setItem('emailSessionToken', data.token);
            setEmailConfig((prev) => ({ ...prev, sessionToken: data.token, appPassword: '' }));
          }
        })
        .catch((error) => {
          console.warn('Mail auth request failed', error);
        });
    }
  };

  return (
    <ErrorBoundary>
      <div className="app" role="main" aria-label="JARVIS Voice Assistant">
        {showOnboarding && (
          <Onboarding
            settings={settings}
            emailConfig={emailConfig}
            onSave={(newSettings, newEmail) => {
              handleSaveSettings(newSettings, newEmail);
            }}
            onSkip={() => {
              localStorage.setItem('jarvisOnboarded', 'true');
              setShowOnboarding(false);
            }}
          />
        )}
        <main className="app-main">
          <div
            className={`orb-container ${isListening ? 'recording' : ''}`}
            onClick={toggleTalk}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                toggleTalk();
              }
            }}
            role="button"
            tabIndex={0}
            aria-label={isListening ? 'Stop recording' : 'Talk to JARVIS'}
            aria-pressed={isListening}
            title={isListening ? 'Tap to stop and send' : 'Tap to talk'}
          >
            <VoiceOrb state={orbState} analysers={analysers.current} />
            <div className="orb-hint">
              {isProcessing
                ? 'Thinking...'
                : isListening
                  ? audioProcessorRef.current
                    ? 'Tap to stop'
                    : 'Listening...'
                  : 'Tap to talk'}
            </div>
          </div>

          <button
            className="settings-btn"
            onClick={() => setShowSettings(!showSettings)}
            title="Settings"
            aria-label="Open settings"
          >
            ⚙️
          </button>

          <button
            className="settings-btn"
            onClick={() => setShowMemory(true)}
            title="Memory Vault"
            aria-label="Open memory vault"
          >
            📚
          </button>

          <div
            className={`bottom-sheet ${sheetState !== 'hidden' ? 'open' : ''}`}
            aria-hidden={sheetState === 'hidden'}
            role="region"
            aria-label="Conversation panel"
          >
            <div className="sheet-handle" aria-hidden="true" />
            <div className="sheet-content">
              {sheetState === 'transcript' && (
                <div className="sheet-transcript" aria-live="polite">
                  <p>{liveTranscript}</p>
                </div>
              )}
              {assistantText && (
                <div className="sheet-response" aria-live="polite">
                  <p>{assistantText}</p>
                </div>
              )}
            </div>
          </div>

          <form
            className="text-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              const text = textInput.trim();
              if (!text) return;
              setLiveTranscript(text);
              setSheetState('transcript');
              resetCollapseTimer();
              sendMessage(text);
              setTextInput('');
            }}
          >
            <label htmlFor="text-input" className="sr-only">
              Type a message
            </label>
            <input
              id="text-input"
              type="text"
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              placeholder="Type a message (or tap the orb to talk)..."
              aria-label="Type a message"
              aria-describedby="input-help"
            />
            <button type="submit" title="Send" aria-label="Send message">
              ➤
            </button>
            <span id="input-help" className="sr-only">
              Press Enter to send
            </span>
          </form>
        </main>

        {error && (
          <div className="error-banner" role="alert" aria-live="assertive">
            <p>{error}</p>
            <button onClick={() => setError(null)} aria-label="Dismiss error">
              ✕
            </button>
          </div>
        )}

        {showSettings && (
          <Suspense
            fallback={
              <div className="settings-overlay" aria-label="Loading settings">
                <div className="settings-panel">
                  <div className="settings-content">Loading…</div>
                </div>
              </div>
            }
          >
            <Settings
              onClose={() => setShowSettings(false)}
              settings={settings}
              emailConfig={emailConfig}
              onSave={handleSaveSettings}
            />
          </Suspense>
        )}

        {showMemory && (
          <Suspense fallback={<div className="memory-overlay">Loading memory vault…</div>}>
            <MemoryPage onClose={() => setShowMemory(false)} />
          </Suspense>
        )}
      </div>
    </ErrorBoundary>
  );
}

export default App;
