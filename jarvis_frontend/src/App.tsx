import React, { useState, useEffect, useRef, useCallback, Suspense, lazy } from 'react';
import './App.css';
import VoiceOrb from './components/VoiceOrb';
import Onboarding from './components/Onboarding';

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
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);
  const processingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const micPermissionGrantedRef = useRef(false);
  const micBusyRef = useRef(false);

  const blobToWavBase64 = async (blob: Blob): Promise<string> => {
    const arrayBuffer = await blob.arrayBuffer();
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    const audioContext = new AudioCtx();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    await audioContext.close();

    const targetRate = 16000;
    const frameCount = Math.ceil(audioBuffer.duration * targetRate);
    const offlineCtx = new OfflineAudioContext(1, frameCount, targetRate);
    const source = offlineCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(offlineCtx.destination);
    source.start(0);
    const rendered = await offlineCtx.startRendering();
    const pcmData = rendered.getChannelData(0);

    const buffer = new ArrayBuffer(44 + pcmData.length * 2);
    const view = new DataView(buffer);
    const writeString = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + pcmData.length * 2, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, targetRate, true);
    view.setUint32(28, targetRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, 'data');
    view.setUint32(40, pcmData.length * 2, true);
    let offset = 44;
    for (let i = 0; i < pcmData.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, pcmData[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }

    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...Array.from(bytes.subarray(i, i + chunkSize)));
    }
    return btoa(binary);
  };

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

          if (data.type === 'response') {
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

    return () => {
      clearInterval(interval);
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
      const recorder = mediaRecorderRef.current;
      if (recorder && recorder.state !== 'inactive') {
        try {
          recorder.stop();
        } catch (err) {
          console.warn('Failed to stop recorder on unmount', err);
        }
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

      if (audioContext.current) {
        if (audioContext.current.state === 'suspended') {
          audioContext.current.resume().catch(() => {});
        }
        try {
          const analyser = audioContext.current.createAnalyser();
          const source = audioContext.current.createMediaStreamSource(stream);
          source.connect(analyser);
          analysers.current = [analyser];
        } catch (analyserErr) {
          console.warn('Analyser setup failed', analyserErr);
        }
      }

      startBackendRecording(stream);

      // Safety: never record forever. Auto-stop after 30 seconds.
      if (recordingTimerRef.current) {
        clearTimeout(recordingTimerRef.current);
      }
      recordingTimerRef.current = setTimeout(() => {
        if (mediaRecorderRef.current) {
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
    if (stream) {
      stream.getTracks().forEach((track: MediaStreamTrack) => track.stop());
    }
    streamRef.current = null;
    analysers.current = [];
    mediaRecorderRef.current = null;
    recordedChunksRef.current = [];
  };

  const startBackendRecording = (stream: MediaStream) => {
    // Record audio locally and send it to the backend for offline transcription
    // (Vosk - no API key needed). Tap the orb again to stop and send.
    setLiveTranscript('Recording... tap the orb again to send');
    setSheetState('transcript');
    resetCollapseTimer();

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch (recErr) {
      cleanupListening(stream);
      setIsListening(false);
      listeningRef.current = false;
      setError('MediaRecorder is not supported in this browser');
      setOrbState('idle');
      setSheetState('hidden');
      return;
    }
    recordedChunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        recordedChunksRef.current.push(e.data);
      }
    };
    recorder.onerror = () => {
      cleanupListening(stream);
      setIsListening(false);
      listeningRef.current = false;
      setOrbState('idle');
      setSheetState('hidden');
      setError('Recording failed. Please try again.');
    };
    recorder.start();
    mediaRecorderRef.current = recorder;
  };

  const stopManualRecording = async () => {
    const recorder = mediaRecorderRef.current;
    const stream = streamRef.current;
    if (!recorder) {
      cleanupListening(stream);
      setIsListening(false);
      listeningRef.current = false;
      setOrbState('idle');
      setSheetState('hidden');
      return;
    }

    setIsListening(false);
    listeningRef.current = false;

    recorder.onstop = async () => {
      cleanupListening(stream);
      const blob = new Blob(recordedChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
      recordedChunksRef.current = [];

      if (blob.size === 0) {
        setError('I could not hear anything. Please try again.');
        setOrbState('idle');
        setSheetState('hidden');
        return;
      }

      setOrbState('thinking');
      setLiveTranscript('Transcribing...');
      resetCollapseTimer();
      try {
        const wavBase64 = await blobToWavBase64(blob);
        if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
          setError('Not connected to server');
          setSheetState('hidden');
          return;
        }
        setIsProcessing(true);
        processingRef.current = true;
        startProcessingWatchdog();
        ws.current.send(
          JSON.stringify({
            type: 'audio',
            audio_base64: wavBase64,
          }),
        );
      } catch (err) {
        console.error('Failed to transcribe audio', err);
        setError('Failed to transcribe audio');
        setIsProcessing(false);
        processingRef.current = false;
        setOrbState('idle');
        setSheetState('hidden');
      }
    };

    try {
      recorder.stop();
    } catch (err) {
      console.error('Failed to stop recorder', err);
      cleanupListening(stream);
      setOrbState('idle');
    }
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
                  ? mediaRecorderRef.current
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
