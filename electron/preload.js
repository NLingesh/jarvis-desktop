const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  reloadWindow: () => ipcRenderer.invoke('reload-window'),

  toggleMainWindow: () => ipcRenderer.invoke('toggle-main-window'),
  showMainWindow: () => ipcRenderer.invoke('show-main-window'),
  hideMainWindow: () => ipcRenderer.invoke('hide-main-window'),
  getBubblePosition: () => ipcRenderer.invoke('get-bubble-position'),
  setBubblePosition: (x: number, y: number) => ipcRenderer.invoke('set-bubble-position', x, y),
  notifyWakeWordDetected: () => ipcRenderer.invoke('notify-wake-word-detected'),
  getSessionToken: () => ipcRenderer.invoke('get-session-token'),

  getVaultPath: () => ipcRenderer.invoke('get-vault-path'),
  openVault: () => ipcRenderer.invoke('open-vault'),

  onWakeWordDetected: (callback: (...args: any[]) => void) => {
    const handler = (_event: any, ...args: any) => callback(...args);
    ipcRenderer.on('wake-word-detected', handler);
    return () => ipcRenderer.removeListener('wake-word-detected', handler);
  },

  onMainWindowVisibility: (callback: (visible: boolean) => void) => {
    const handler = (_event: any, visible: boolean) => callback(visible);
    ipcRenderer.on('main-window-visibility', handler);
    return () => ipcRenderer.removeListener('main-window-visibility', handler);
  },

  // OS keychain API key management (uses keytar under the hood)
  storeApiKey: (keyName: string, value: string) => ipcRenderer.invoke('store-api-key', keyName, value),
  retrieveApiKey: (keyName: string) => ipcRenderer.invoke('retrieve-api-key', keyName),
  retrieveApiKeys: () => ipcRenderer.invoke('retrieve-api-keys'),
  deleteApiKey: (keyName: string) => ipcRenderer.invoke('delete-api-key', keyName),
});
