/// <reference types="vite/client" />

interface ElectronApi {
  getAppVersion: () => Promise<string>;
  getPlatform: () => Promise<string>;
  reloadWindow: () => Promise<void>;

  toggleMainWindow: () => Promise<void>;
  showMainWindow: () => Promise<void>;
  hideMainWindow: () => Promise<void>;

  togglePanel: () => Promise<void>;
  openPanel: () => Promise<void>;
  closePanel: () => Promise<void>;
  updatePanelPosition: (x: number, y: number) => Promise<void>;
  getWorkArea: () => Promise<{ x: number; y: number; width: number; height: number }>;

  setWindowMode: (mode: string, cx?: number, cy?: number) => Promise<{ x: number; y: number }>;
  getOrbPosition: () => Promise<{ x: number; y: number }>;
  setOrbPosition: (cx: number, cy: number) => Promise<{ x: number; y: number }>;
  showContextMenu: () => Promise<void>;
  quitApp: () => Promise<void>;

  onContextMenuAction: (callback: (action: string) => void) => () => void;
  onTogglePanel: (callback: (...args: unknown[]) => void) => () => void;
  onOpenPanel: (callback: (...args: unknown[]) => void) => () => void;
  onClosePanel: (callback: (...args: unknown[]) => void) => () => void;

  requestPermission: (permission: string) => Promise<{ granted: boolean }>;

  notifyWakeWordDetected: () => Promise<void>;
  getSessionToken: () => Promise<string | null>;
  logVoice: (payload: unknown) => Promise<{ ok: boolean }>;

  showNotification: (title: string, body: string) => Promise<{ success: boolean; error?: string }>;
  bubbleVoiceControl: (action: string) => Promise<void>;

  onVoiceControl: (callback: (action: string) => void) => () => void;
  onWakeWordDetected: (callback: (...args: unknown[]) => void) => () => void;
  onMainWindowVisibility: (callback: (visible: boolean) => void) => () => void;
  onSwitchView: (callback: (view: string) => void) => () => void;

  getVaultPath: () => Promise<string>;
  openVault: () => Promise<{ ok: boolean; path: string; error?: string }>;

  storeApiKey: (keyName: string, value: string) => Promise<{ success: boolean; error?: string }>;
  retrieveApiKey: (keyName: string) => Promise<string | null>;
  retrieveApiKeys: () => Promise<Record<string, string>>;
  deleteApiKey: (keyName: string) => Promise<{ success: boolean; error?: string }>;

  getAutostartEnabled: () => Promise<boolean>;
  setAutostartEnabled: (enabled: boolean) => Promise<{ success: boolean }>;
  getStartMinimized: () => Promise<boolean>;
  setStartMinimized: (enabled: boolean) => Promise<{ success: boolean }>;
}

interface Window {
  electronAPI?: ElectronApi;
}
