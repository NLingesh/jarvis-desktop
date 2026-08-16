import React, { useState, useEffect, useCallback } from 'react';
import './SettingsView.css';
import MicTest from './MicTest';

export interface SettingsState {
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
}

export interface MicDevice {
  id: number;
  name: string;
  is_default: boolean;
}

export interface EmailConfig {
  email: string;
  appPassword: string;
  sessionToken: string | null;
}

interface SettingsViewProps {
  initialSettings?: SettingsState;
  initialEmailConfig?: EmailConfig;
  onSave?: (settings: SettingsState, emailConfig: EmailConfig) => void;
}

const DEFAULT_SETTINGS: SettingsState = {
  voice: 'en-US',
  volume: 0.8,
  speed: 1.0,
  theme: 'dark',
  enableNotifications: true,
  serverUrl: '127.0.0.1:8000',
  enableWakeWord: true,
  alwaysOnListening: false,
  voiceMode: 'native',
};

const DEFAULT_EMAIL: EmailConfig = {
  email: '',
  appPassword: '',
  sessionToken: null,
};

const SettingsView: React.FC<SettingsViewProps> = ({
  initialSettings,
  initialEmailConfig,
  onSave,
}) => {
  const [settings, setSettings] = useState<SettingsState>(initialSettings || DEFAULT_SETTINGS);
  const [emailConfig, setEmailConfig] = useState<EmailConfig>(initialEmailConfig || DEFAULT_EMAIL);
  const [toast, setToast] = useState<string | null>(null);
  const [autostartEnabled, setAutostartEnabled] = useState(false);
  const [startMinimizedEnabled, setStartMinimizedEnabled] = useState(false);
  const [micDevices, setMicDevices] = useState<MicDevice[]>([]);
  const [micDevicesError, setMicDevicesError] = useState<string | null>(null);
  const [micDevicesLoading, setMicDevicesLoading] = useState(false);

  useEffect(() => {
    if (initialSettings) setSettings(initialSettings);
    if (initialEmailConfig) setEmailConfig(initialEmailConfig);
  }, [initialSettings, initialEmailConfig]);

  useEffect(() => {
    (async () => {
      try {
        const api = (window as any).electronAPI;
        if (api?.getAutostartEnabled) {
          setAutostartEnabled(await api.getAutostartEnabled());
        }
      } catch {
        // ignore
      }
      try {
        const api = (window as any).electronAPI;
        if (api?.getStartMinimized) {
          setStartMinimizedEnabled(await api.getStartMinimized());
        }
      } catch {
        // ignore
      }
    })();
  }, []);

  const loadMicDevices = useCallback(async () => {
    if (settings.voiceMode !== 'native') return;
    setMicDevicesLoading(true);
    setMicDevicesError(null);
    try {
      const base = settings.serverUrl
        .replace(/^ws:\/\//, 'http://')
        .replace(/^wss:\/\//, 'https://')
        .replace(/\/+$/, '');
      const token = await getSessionToken();
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const res = await fetch(`${base}/api/voice/devices`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      const list: MicDevice[] = (body.devices ?? []).map((d: any) => ({
        id: d.id,
        name: d.name,
        is_default: Boolean(d.is_default),
      }));
      setMicDevices(list);
      if (list.length === 0) {
        setMicDevicesError('No microphone detected.');
      }
    } catch (err) {
      setMicDevicesError(err instanceof Error ? err.message : 'Could not load microphones');
    } finally {
      setMicDevicesLoading(false);
    }
  }, [settings.serverUrl, settings.voiceMode]);

  useEffect(() => {
    loadMicDevices();
  }, [loadMicDevices]);

  const getSessionToken = useCallback(async (): Promise<string | null> => {
    try {
      const api = (window as any).electronAPI;
      if (api?.getSessionToken) {
        const token = (await api.getSessionToken()) as string | null;
        if (token) return token;
      }
    } catch {
      // ignore
    }
    try {
      return localStorage.getItem('jarvisSessionToken');
    } catch {
      return null;
    }
  }, []);

  const activeMicLabel = useCallback(() => {
    const selected = settings.nativeMicDevice;
    if (selected !== undefined && micDevices.some((d) => d.id === selected)) {
      return micDevices.find((d) => d.id === selected)?.name ?? 'Auto';
    }
    const def = micDevices.find((d) => d.is_default);
    return def ? `${def.name} (default)` : 'Auto (default)';
  }, [settings.nativeMicDevice, micDevices]);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2000);
  }, []);

  const updateSetting = useCallback(
    <K extends keyof SettingsState>(key: K, value: SettingsState[K]) => {
      setSettings((prev) => {
        const next = { ...prev, [key]: value };
        try {
          localStorage.setItem('voiceSettings', JSON.stringify(next));
          localStorage.setItem('serverUrl', next.serverUrl);
          window.dispatchEvent(new CustomEvent('jarvis-settings-change'));
        } catch {
          // ignore
        }
        onSave?.(next, emailConfig);
        showToast('Saved');
        return next;
      });
    },
    [emailConfig, onSave, showToast],
  );

  const handleMicDeviceChange = useCallback(
    (value: string) => {
      const id = value === '' ? undefined : Number(value);
      updateSetting('nativeMicDevice', id);
    },
    [updateSetting],
  );

  const updateEmail = useCallback(
    (key: keyof EmailConfig, value: string) => {
      setEmailConfig((prev) => {
        const next = { ...prev, [key]: value };
        onSave?.(settings, next);
        return next;
      });
    },
    [settings, onSave],
  );

  const updateEmailAndSettings = useCallback(
    async (key: keyof EmailConfig, value: string) => {
      const nextEmail = { ...emailConfig, [key]: value };
      setEmailConfig(nextEmail);
      onSave?.(settings, nextEmail);
    },
    [emailConfig, settings, onSave],
  );

  return (
    <div className="settings-view">
      {toast && (
        <div className="settings-toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}

      <div className="settings-group">
        <h3 className="settings-group-title">Voice</h3>
        <div className="setting-item">
          <label htmlFor="s-voice">Language</label>
          <select
            id="s-voice"
            value={settings.voice}
            onChange={(e) => updateSetting('voice', e.target.value as SettingsState['voice'])}
          >
            <option value="en-US">English (US)</option>
            <option value="en-GB">English (UK)</option>
            <option value="es-ES">Spanish</option>
            <option value="fr-FR">French</option>
            <option value="de-DE">German</option>
          </select>
        </div>
        <div className="setting-item">
          <label htmlFor="s-volume">Volume ({Math.round(settings.volume * 100)}%)</label>
          <input
            id="s-volume"
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={settings.volume}
            onChange={(e) => updateSetting('volume', parseFloat(e.target.value))}
          />
        </div>
        <div className="setting-item">
          <label htmlFor="s-speed">Speed ({settings.speed}x)</label>
          <input
            id="s-speed"
            type="range"
            min="0.5"
            max="2"
            step="0.1"
            value={settings.speed}
            onChange={(e) => updateSetting('speed', parseFloat(e.target.value))}
          />
        </div>
        <div className="setting-item checkbox">
          <input
            id="s-wake"
            type="checkbox"
            checked={settings.enableWakeWord}
            onChange={(e) => updateSetting('enableWakeWord', e.target.checked)}
          />
          <label htmlFor="s-wake">Enable wake word</label>
        </div>
        <div className="setting-item checkbox">
          <input
            id="s-always"
            type="checkbox"
            checked={settings.alwaysOnListening}
            onChange={(e) => updateSetting('alwaysOnListening', e.target.checked)}
          />
          <label htmlFor="s-always">Always-on listening</label>
        </div>
        <div className="setting-item">
          <label htmlFor="s-voicemode">Capture engine</label>
          <select
            id="s-voicemode"
            value={settings.voiceMode}
            onChange={(e) =>
              updateSetting('voiceMode', e.target.value as SettingsState['voiceMode'])
            }
          >
            <option value="native">Backend (local microphone)</option>
            <option value="browser">Browser (getUserMedia)</option>
          </select>
          <small className="setting-hint">
            Backend capture is more reliable: the server opens the mic directly.
          </small>
        </div>
        {settings.voiceMode === 'native' && (
          <>
            <div className="setting-item">
              <label htmlFor="s-micdevice">Microphone</label>
              <select
                id="s-micdevice"
                value={
                  settings.nativeMicDevice !== undefined &&
                  micDevices.some((d) => d.id === settings.nativeMicDevice)
                    ? String(settings.nativeMicDevice)
                    : ''
                }
                onChange={(e) => handleMicDeviceChange(e.target.value)}
                disabled={micDevicesLoading || micDevices.length === 0}
              >
                <option value="">
                  {micDevicesLoading
                    ? 'Loading microphones...'
                    : micDevicesError
                      ? micDevicesError
                      : activeMicLabel()}
                </option>
                {micDevices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                    {d.is_default ? ' (default)' : ''}
                  </option>
                ))}
              </select>
              <small className="setting-hint">
                {micDevicesError && micDevices.length === 0
                  ? micDevicesError
                  : settings.nativeMicDevice !== undefined
                    ? 'Using selected microphone. Fallback to default if it disappears.'
                    : 'Using the system default microphone.'}
              </small>
            </div>
            <div className="setting-item">
              <label>Microphone test</label>
              <MicTest serverUrl={settings.serverUrl} />
            </div>
          </>
        )}
      </div>

      <div className="settings-group">
        <h3 className="settings-group-title">Appearance</h3>
        <div className="setting-item">
          <label htmlFor="s-theme">Theme</label>
          <select
            id="s-theme"
            value={settings.theme}
            onChange={(e) => updateSetting('theme', e.target.value as SettingsState['theme'])}
          >
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="auto">Auto</option>
          </select>
        </div>
        <div className="setting-item checkbox">
          <input
            id="s-notif"
            type="checkbox"
            checked={settings.enableNotifications}
            onChange={(e) => updateSetting('enableNotifications', e.target.checked)}
          />
          <label htmlFor="s-notif">Enable notifications</label>
        </div>
      </div>

      <div className="settings-group">
        <h3 className="settings-group-title">Server</h3>
        <div className="setting-item">
          <label htmlFor="s-server">Server URL</label>
          <input
            id="s-server"
            type="text"
            value={settings.serverUrl}
            onChange={(e) => updateSetting('serverUrl', e.target.value)}
            placeholder="localhost:8000"
          />
        </div>
      </div>

      <div className="settings-group">
        <h3 className="settings-group-title">Email</h3>
        <div className="setting-item">
          <label htmlFor="s-email">Email</label>
          <input
            id="s-email"
            type="email"
            value={emailConfig.email}
            onChange={(e) => updateEmail('email', e.target.value)}
            placeholder="your@email.com"
          />
        </div>
        <div className="setting-item">
          <label htmlFor="s-app-pw">App Password</label>
          <input
            id="s-app-pw"
            type="password"
            value={emailConfig.appPassword}
            onChange={(e) => updateEmailAndSettings('appPassword', e.target.value)}
            placeholder="App-specific password"
          />
        </div>
      </div>

      <div className="settings-group">
        <h3 className="settings-group-title">Privacy</h3>
        <div className="setting-item checkbox">
          <input id="s-privacy" type="checkbox" defaultChecked />
          <label htmlFor="s-privacy">Allow anonymous usage data</label>
        </div>
      </div>

      <div className="settings-group">
        <h3 className="settings-group-title">Startup</h3>
        <div className="setting-item checkbox">
          <input
            id="s-startup"
            type="checkbox"
            checked={autostartEnabled}
            onChange={async (e) => {
              const val = e.target.checked;
              setAutostartEnabled(val);
              try {
                const api = (window as any).electronAPI;
                await api?.setAutostartEnabled(val);
              } catch {
                // ignore
              }
            }}
          />
          <label htmlFor="s-startup">Launch JARVIS on startup</label>
        </div>
        <div className="setting-item checkbox">
          <input
            id="s-minimize"
            type="checkbox"
            checked={startMinimizedEnabled}
            onChange={async (e) => {
              const val = e.target.checked;
              setStartMinimizedEnabled(val);
              try {
                const api = (window as any).electronAPI;
                await api?.setStartMinimized(val);
              } catch {
                // ignore
              }
            }}
          />
          <label htmlFor="s-minimize">Start minimized to tray</label>
        </div>
      </div>
    </div>
  );
};

export default SettingsView;
