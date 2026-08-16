import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import SettingsView, { SettingsState } from './SettingsView';

const BASE: SettingsState = {
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

describe('SettingsView microphone selector', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          devices: [
            { id: 1, name: 'Built-in Analog', is_default: true },
            { id: 2, name: 'USB Headset', is_default: false },
          ],
        }),
      })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('loads microphones from the backend and shows the default', async () => {
    render(<SettingsView initialSettings={BASE} />);
    expect(await screen.findByText(/Using the system default microphone/)).toBeTruthy();
    const select = screen.getByLabelText('Microphone') as HTMLSelectElement;
    expect(select.options.length).toBeGreaterThanOrEqual(2);
  });

  it('persists a selected microphone id as a non-sensitive device id', async () => {
    let saved: SettingsState | undefined;
    render(
      <SettingsView
        initialSettings={BASE}
        onSave={(s) => {
          saved = s;
        }}
      />,
    );
    const select = await screen.findByLabelText('Microphone');
    await act(async () => {
      fireEvent.change(select, { target: { value: '2' } });
      await new Promise((r) => setTimeout(r, 0));
    });

    const stored = JSON.parse(localStorage.getItem('voiceSettings') || '{}');
    expect(stored.nativeMicDevice).toBe(2);
    expect(saved?.nativeMicDevice).toBe(2);
  });

  it('falls back to the default option when the stored device disappears', async () => {
    const initial = { ...BASE, nativeMicDevice: 99 };
    render(<SettingsView initialSettings={initial} />);
    const select = (await screen.findByLabelText('Microphone')) as HTMLSelectElement;
    expect(select.value).toBe('');
    expect(select.options[0].textContent).toMatch(/default/);
  });

  it('shows "No microphone detected." when the backend returns no devices', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ devices: [] }) })),
    );
    render(<SettingsView initialSettings={BASE} />);
    expect(await screen.findAllByText('No microphone detected.')).not.toHaveLength(0);
  });
});
