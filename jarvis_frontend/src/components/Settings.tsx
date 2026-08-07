import React, { useState, useEffect } from 'react';

type SettingsState = {
  voice: string;
  volume: number;
  speed: number;
  theme: string;
  enableNotifications: boolean;
  serverUrl: string;
  enableWakeWord: boolean;
  alwaysOnListening: boolean;
};

type EmailConfig = {
  email: string;
  appPassword: string;
  sessionToken: string | null;
};

interface SettingsProps {
  onClose: () => void;
  settings: SettingsState;
  emailConfig: EmailConfig;
  onSave: (settings: SettingsState, emailConfig: EmailConfig) => void;
}

const Settings: React.FC<SettingsProps> = ({
  onClose,
  settings: initialSettings,
  emailConfig: initialEmailConfig,
  onSave,
}) => {
  const [settings, setSettings] = useState<SettingsState>(initialSettings);
  const [emailConfig, setEmailConfig] = useState<EmailConfig>(initialEmailConfig);

  useEffect(() => {
    setSettings(initialSettings);
  }, [initialSettings]);

  useEffect(() => {
    setEmailConfig(initialEmailConfig);
  }, [initialEmailConfig]);

  const handleSettingChange = (key: keyof SettingsState, value: any) => {
    setSettings((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleEmailChange = (key: keyof EmailConfig, value: string) => {
    setEmailConfig((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleSave = () => {
    onSave(settings, emailConfig);
    onClose();
  };

  return (
    <div className="settings-overlay">
      <div className="settings-panel">
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="settings-content">
          <div className="settings-section">
            <h3>Voice Settings</h3>

            <div className="setting-item">
              <label>Language</label>
              <select
                value={settings.voice}
                onChange={(e) => handleSettingChange('voice', e.target.value)}
              >
                <option value="en-US">English (US)</option>
                <option value="en-GB">English (UK)</option>
                <option value="es-ES">Spanish</option>
                <option value="fr-FR">French</option>
                <option value="de-DE">German</option>
              </select>
            </div>

            <div className="setting-item">
              <label>Volume ({Math.round(settings.volume * 100)}%)</label>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={settings.volume}
                onChange={(e) => handleSettingChange('volume', parseFloat(e.target.value))}
              />
            </div>

            <div className="setting-item">
              <label>Speech Speed ({settings.speed}x)</label>
              <input
                type="range"
                min="0.5"
                max="2"
                step="0.1"
                value={settings.speed}
                onChange={(e) => handleSettingChange('speed', parseFloat(e.target.value))}
              />
            </div>

            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="wake-word"
                checked={settings.enableWakeWord}
                onChange={(e) => handleSettingChange('enableWakeWord', e.target.checked)}
              />
              <label htmlFor="wake-word">Enable wake word detection</label>
            </div>

            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="always-on"
                checked={settings.alwaysOnListening}
                onChange={(e) => handleSettingChange('alwaysOnListening', e.target.checked)}
              />
              <label htmlFor="always-on">Always-on listening</label>
            </div>
          </div>

          <div className="settings-section">
            <h3>Display</h3>

            <div className="setting-item">
              <label>Theme</label>
              <select
                value={settings.theme}
                onChange={(e) => handleSettingChange('theme', e.target.value)}
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
                <option value="auto">Auto</option>
              </select>
            </div>

            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="notifications"
                checked={settings.enableNotifications}
                onChange={(e) => handleSettingChange('enableNotifications', e.target.checked)}
              />
              <label htmlFor="notifications">Enable Notifications</label>
            </div>
          </div>

          <div className="settings-section">
            <h3>Server Configuration</h3>

            <div className="setting-item">
              <label>Server URL</label>
              <input
                type="text"
                value={settings.serverUrl}
                onChange={(e) => handleSettingChange('serverUrl', e.target.value)}
                placeholder="localhost:8000"
              />
            </div>
          </div>

          <div className="settings-section">
            <h3>Email Integration</h3>

            <div className="setting-item">
              <label>Email Address</label>
              <input
                type="email"
                value={emailConfig.email}
                onChange={(e) => handleEmailChange('email', e.target.value)}
                placeholder="your@email.com"
              />
            </div>

            <div className="setting-item">
              <label>App Password</label>
              <input
                type="password"
                value={emailConfig.appPassword}
                onChange={(e) => handleEmailChange('appPassword', e.target.value)}
                placeholder="app-specific password"
              />
              <small>For Gmail: Use an App Password (not your regular password)</small>
            </div>
          </div>

          <div className="settings-section">
            <h3>About</h3>
            <p>JARVIS Voice Assistant v1.0</p>
            <p>A voice-first AI assistant powered by Mistral AI</p>
          </div>
        </div>

        <div className="settings-footer">
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSave}>
            Save Settings
          </button>
        </div>
      </div>
    </div>
  );
};

export default Settings;
