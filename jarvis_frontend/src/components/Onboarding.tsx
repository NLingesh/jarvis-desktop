import React, { useState, useCallback } from 'react';
import './Onboarding.css';

type Step = 'welcome' | 'keys' | 'mic' | 'model' | 'done';

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

type OnboardingProps = {
  settings: SettingsState;
  emailConfig: EmailConfig;
  onSave: (settings: SettingsState, emailConfig: EmailConfig) => void;
  onSkip: () => void;
};

const API_KEY_HINTS: Record<string, string> = {
  MISTRAL_API_KEY: 'Mistral AI (primary LLM)',
  ANTHROPIC_API_KEY: 'Anthropic Claude (fallback LLM)',
  ELEVENLABS_API_KEY: 'ElevenLabs (voice)',
  NVIDIA_API_KEY: 'NVIDIA NIM (reranking)',
};

const Onboarding: React.FC<OnboardingProps> = ({ settings, emailConfig, onSave, onSkip }) => {
  const [step, setStep] = useState<Step>('welcome');
  const [apiKeyValues, setApiKeyValues] = useState<Record<string, string>>({});
  const [hasMicPermission, setHasMicPermission] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);

  const checkMic = useCallback(async () => {
    setChecking(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((t) => t.stop());
      setHasMicPermission(true);
    } catch {
      setHasMicPermission(false);
    } finally {
      setChecking(false);
    }
  }, []);

  const handleComplete = () => {
    const keysToSave: Record<string, string> = {};
    let hasKeys = false;
    for (const key of Object.keys(API_KEY_HINTS)) {
      const val = apiKeyValues[key];
      if (val) {
        keysToSave[key] = val;
        hasKeys = true;
      }
    }
    if (hasKeys) {
      const apiUrl = settings.serverUrl.trim();
      const baseUrl = apiUrl.startsWith('http') ? apiUrl : `http://${apiUrl}`;
      fetch(`${baseUrl}/api/settings/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keys: keysToSave }),
      }).catch((e) => console.warn('Failed to save API keys during onboarding', e));
    }
    localStorage.setItem('jarvisOnboarded', 'true');
    onSave(settings, emailConfig);
    setStep('done');
  };

  const renderStep = () => {
    switch (step) {
      case 'welcome':
        return (
          <div className="onboarding-step">
            <h2>Welcome to JARVIS</h2>
            <p>Your voice-first AI assistant is almost ready. Let's set a few things up.</p>
            <div className="onboarding-actions">
              <button className="btn btn-primary" onClick={() => setStep('keys')}>
                Get Started
              </button>
              <button className="btn btn-secondary" onClick={onSkip}>
                Skip for now
              </button>
            </div>
          </div>
        );

      case 'keys':
        return (
          <div className="onboarding-step">
            <h2>API Keys</h2>
            <p>Add your API keys below. These are stored in your local config and never shared.</p>
            <div className="key-inputs">
              {Object.entries(API_KEY_HINTS).map(([key, label]) => (
                <div key={key} className="setting-item">
                  <label htmlFor={`key-${key}`}>{label}</label>
                  <input
                    id={`key-${key}`}
                    type="password"
                    placeholder={key}
                    value={apiKeyValues[key] || ''}
                    onChange={(e) => setApiKeyValues({ ...apiKeyValues, [key]: e.target.value })}
                  />
                  <small>Optional — you can also add these later in Settings</small>
                </div>
              ))}
            </div>
            <div className="onboarding-actions">
              <button className="btn btn-secondary" onClick={() => setStep('welcome')}>
                Back
              </button>
              <button className="btn btn-primary" onClick={() => setStep('mic')}>
                Continue
              </button>
            </div>
          </div>
        );

      case 'mic':
        return (
          <div className="onboarding-step">
            <h2>Microphone Access</h2>
            <p>JARVIS needs microphone access to listen to your voice.</p>
            {hasMicPermission === true && (
              <p style={{ color: '#00ff88' }}>Microphone access granted.</p>
            )}
            {hasMicPermission === false && (
              <p style={{ color: '#ff4444' }}>
                Microphone access denied. Please check your system settings.
              </p>
            )}
            <div className="onboarding-actions">
              <button className="btn btn-secondary" onClick={() => setStep('keys')}>
                Back
              </button>
              <button className="btn btn-primary" onClick={checkMic} disabled={checking}>
                {checking ? 'Checking…' : 'Check Microphone'}
              </button>
            </div>
          </div>
        );

      case 'model':
        return (
          <div className="onboarding-step">
            <h2>Voice Model</h2>
            <p>
              Offline speech recognition requires a Vosk model. Download it during setup or skip for
              now.
            </p>
            <div className="onboarding-actions">
              <button className="btn btn-secondary" onClick={() => setStep('mic')}>
                Back
              </button>
              <button className="btn btn-primary" onClick={() => setStep('done')}>
                Skip (use text)
              </button>
            </div>
          </div>
        );

      case 'done':
        return (
          <div className="onboarding-step">
            <h2>All Set!</h2>
            <p>JARVIS is ready. Tap the orb or type a message to get started.</p>
            <div className="onboarding-actions">
              <button className="btn btn-primary" onClick={handleComplete}>
                Finish
              </button>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div
      className="onboarding-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="JARVIS Setup Wizard"
    >
      <div className="onboarding-panel">
        <div className="onboarding-step-indicator">
          {['welcome', 'keys', 'mic', 'done'].map((s) => (
            <span key={s} className={`dot ${step === s ? 'active' : ''}`} aria-label={s} />
          ))}
        </div>
        {renderStep()}
      </div>
    </div>
  );
};

export default Onboarding;
