import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import MicTest from './MicTest';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe('MicTest', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    (globalThis as any).WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the test button and connects on start', async () => {
    render(<MicTest serverUrl="localhost:8000" />);
    expect(screen.getByText('Test Microphone')).toBeTruthy();

    await act(async () => {
      screen.getByText('Test Microphone').click();
      await new Promise((r) => setTimeout(r, 0));
    });

    const ws = FakeWebSocket.instances[0];
    expect(ws.url).toBe('ws://localhost:8000/ws/voice/native');
    ws.open();
    await act(async () => {
      ws.emit({ type: 'devices', devices: [{ id: 1, name: 'Built-in Mic', channels: 1 }] });
      ws.emit({ type: 'state', state: 'READY' });
    });
    expect(screen.getByText(/Built-in Mic/)).toBeTruthy();
  });

  it('starts and stops a mic test, updating the meter from level events', async () => {
    render(<MicTest serverUrl="localhost:8000" />);

    await act(async () => {
      screen.getByText('Test Microphone').click();
      await new Promise((r) => setTimeout(r, 0));
    });
    const ws = FakeWebSocket.instances[0];
    ws.open();
    await act(async () => {
      ws.emit({ type: 'state', state: 'READY' });
      ws.emit({ type: 'level', rms: 0.5, peak: 0.8 });
      await new Promise((r) => setTimeout(r, 150));
    });

    expect(ws.sent).toContain('{"type":"mic_test_start"}');
    expect(screen.getByText('Level: 50%')).toBeTruthy();
    expect(screen.getByText('Peak: 80%')).toBeTruthy();

    await act(async () => {
      screen.getByText('Stop Test').click();
    });
    expect(ws.sent).toContain('{"type":"mic_test_stop"}');
  });

  it('surfaces an error message from the backend', async () => {
    render(<MicTest serverUrl="localhost:8000" />);

    await act(async () => {
      screen.getByText('Test Microphone').click();
      await new Promise((r) => setTimeout(r, 0));
    });
    const ws = FakeWebSocket.instances[0];
    ws.open();
    await act(async () => {
      ws.emit({ type: 'error', message: 'No input device available' });
    });
    expect(screen.getByText('No input device available')).toBeTruthy();
  });
});
