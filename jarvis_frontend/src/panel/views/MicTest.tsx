import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NATIVE_COMMANDS } from '../../nativeVoiceClient';

interface MicTestProps {
  serverUrl: string;
}

interface Device {
  id: number;
  name: string;
}

function toBaseWsUrl(server: string, endpoint: string): string {
  const trimmed = server.replace(/\/*$/, '');
  if (trimmed.startsWith('ws://') || trimmed.startsWith('wss://')) return `${trimmed}${endpoint}`;
  if (trimmed.startsWith('http://')) return `ws://${trimmed.slice(7)}${endpoint}`;
  if (trimmed.startsWith('https://')) return `wss://${trimmed.slice(8)}${endpoint}`;
  return `ws://${trimmed}${endpoint}`;
}

const MicTest: React.FC<MicTestProps> = ({ serverUrl }) => {
  const [devices, setDevices] = useState<Device[]>([]);
  const [active, setActive] = useState(false);
  const [running, setRunning] = useState(false);
  const [level, setLevel] = useState(0);
  const [peak, setPeak] = useState(0);
  const [status, setStatus] = useState('');
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const tokenRef = useRef<string | null>(null);

  const getToken = useCallback(async (): Promise<string | null> => {
    const api = (window as any).electronAPI;
    if (api?.getSessionToken) {
      try {
        const token = (await api.getSessionToken()) as string | null;
        if (token) return token;
      } catch {
        // fall through to localStorage
      }
    }
    try {
      return localStorage.getItem('jarvisSessionToken');
    } catch {
      return null;
    }
  }, []);

  const connect = useCallback(async (): Promise<WebSocket | null> => {
    const token = tokenRef.current ?? (await getToken());
    tokenRef.current = token;
    const url = toBaseWsUrl(serverUrl, '/ws/voice/native');
    const ws = new WebSocket(token ? `${url}?token=${encodeURIComponent(token)}` : url);
    wsRef.current = ws;
    ws.onopen = () => {
      setError(null);
      ws.send(NATIVE_COMMANDS.connect());
      ws.send(NATIVE_COMMANDS.getDevices());
    };
    ws.onclose = () => {
      setRunning(false);
      setLevel(0);
      setPeak(0);
      setStatus('disconnected');
    };
    ws.onmessage = (event) => {
      let data: any;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      if (data.type === 'devices') {
        setDevices((data.devices ?? []) as Device[]);
        setActive(Boolean(data.active));
      } else if (data.type === 'level') {
        setLevel(Math.min(1, Math.max(0, data.rms ?? 0)));
        setPeak(Math.min(1, Math.max(0, data.peak ?? 0)));
      } else if (data.type === 'mic_test') {
        setStatus(data.status ?? '');
      } else if (data.type === 'state') {
        if (data.state === 'ERROR') setError(data.detail || 'Microphone error');
        if (data.state === 'READY' && !running) setRunning(true);
      } else if (data.type === 'error') {
        setError(data.message || 'Microphone error');
      }
    };
    return ws;
  }, [serverUrl, getToken]);

  const start = useCallback(async () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(NATIVE_COMMANDS.micTestStart());
      setRunning(true);
      return;
    }
    const ws = await connect();
    if (!ws) {
      setError('Could not connect to the voice server.');
      return;
    }
    const waitOpen = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(NATIVE_COMMANDS.micTestStart());
        setRunning(true);
      } else {
        setTimeout(waitOpen, 100);
      }
    };
    waitOpen();
  }, [connect]);

  const stop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(NATIVE_COMMANDS.micTestStop());
    }
    setRunning(false);
    setLevel(0);
    setPeak(0);
    setStatus('stopped');
  }, []);

  const selectDevice = useCallback((device: number | string | undefined) => {
    if (wsRef.current?.readyState === WebSocket.OPEN && device !== undefined) {
      wsRef.current.send(NATIVE_COMMANDS.setDevice(device));
    }
  }, []);

  useEffect(() => {
    return () => {
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  return (
    <div className="mic-test">
      <div className="mic-test-row">
        <select
          value={''}
          onChange={(e) => selectDevice(e.target.value === '' ? undefined : Number(e.target.value))}
        >
          <option value="" disabled>
            {devices.length ? 'Select microphone' : 'No microphones found'}
          </option>
          {devices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`btn ${running ? 'btn-danger' : 'btn-primary'}`}
          onClick={running ? stop : start}
        >
          {running ? 'Stop Test' : 'Test Microphone'}
        </button>
      </div>

      <div className="mic-test-meter" role="meter" aria-label="Microphone level">
        <div className="mic-test-meter-fill" style={{ width: `${Math.round(level * 100)}%` }} />
      </div>
      <div className="mic-test-meta">
        <span>Level: {Math.round(level * 100)}%</span>
        <span>Peak: {Math.round(peak * 100)}%</span>
        {status && <span className="mic-test-status">{status}</span>}
        {active && <span className="mic-test-status mic-test-active">mic active</span>}
      </div>
      {error && <p className="mic-test-error">{error}</p>}
    </div>
  );
};

export default MicTest;
