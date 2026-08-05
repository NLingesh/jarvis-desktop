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

  onWakeWordDetected: (callback: (...args: any[]) => void) => {
    const handler = (_event: any, ...args: any[]) => callback(...args);
    ipcRenderer.on('wake-word-detected', handler);
    return () => ipcRenderer.removeListener('wake-word-detected', handler);
  },
});
