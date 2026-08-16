const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  getPlatform: () => ipcRenderer.invoke('get-platform'),
  reloadWindow: () => ipcRenderer.invoke('reload-window'),

  toggleMainWindow: () => ipcRenderer.invoke('toggle-main-window'),
  showMainWindow: () => ipcRenderer.invoke('show-main-window'),
  hideMainWindow: () => ipcRenderer.invoke('hide-main-window'),

  togglePanel: () => ipcRenderer.invoke('toggle-panel'),
  openPanel: () => ipcRenderer.invoke('open-panel'),
  closePanel: () => ipcRenderer.invoke('close-panel'),
  updatePanelPosition: (x, y) => ipcRenderer.invoke('update-panel-position', x, y),
  getWorkArea: () => ipcRenderer.invoke('get-work-area'),

  setWindowMode: (mode, cx, cy) => ipcRenderer.invoke('set-window-mode', mode, cx, cy),
  getOrbPosition: () => ipcRenderer.invoke('get-orb-position'),
  setOrbPosition: (cx, cy) => ipcRenderer.invoke('set-orb-position', cx, cy),
  showContextMenu: () => ipcRenderer.invoke('show-context-menu'),
  quitApp: () => ipcRenderer.invoke('quit-app'),

  onContextMenuAction: (callback) => {
    const handler = (_event, action) => callback(action);
    ipcRenderer.on('context-menu-action', handler);
    return () => ipcRenderer.removeListener('context-menu-action', handler);
  },

  onTogglePanel: (callback) => {
    const handler = (_event, ...args) => callback(...args);
    ipcRenderer.on('toggle-panel', handler);
    return () => ipcRenderer.removeListener('toggle-panel', handler);
  },

  onOpenPanel: (callback) => {
    const handler = (_event, ...args) => callback(...args);
    ipcRenderer.on('open-panel', handler);
    return () => ipcRenderer.removeListener('open-panel', handler);
  },

  onClosePanel: (callback) => {
    const handler = (_event, ...args) => callback(...args);
    ipcRenderer.on('close-panel', handler);
    return () => ipcRenderer.removeListener('close-panel', handler);
  },

  requestPermission: (permission) => ipcRenderer.invoke('request-permission', permission),

  notifyWakeWordDetected: () => ipcRenderer.invoke('notify-wake-word-detected'),
  getSessionToken: () => ipcRenderer.invoke('get-session-token'),
  logVoice: (payload) => ipcRenderer.invoke('voice-log', payload),

  showNotification: (title, body) => ipcRenderer.invoke('show-notification', { title, body }),
  bubbleVoiceControl: (action) => ipcRenderer.invoke('bubble-voice-control', action),

  onVoiceControl: (callback) => {
    const handler = (_event, action) => callback(action);
    ipcRenderer.on('voice-control', handler);
    return () => ipcRenderer.removeListener('voice-control', handler);
  },

  getVaultPath: () => ipcRenderer.invoke('get-vault-path'),
  openVault: () => ipcRenderer.invoke('open-vault'),

  onWakeWordDetected: (callback) => {
    const handler = (_event, ...args) => callback(...args);
    ipcRenderer.on('wake-word-detected', handler);
    return () => ipcRenderer.removeListener('wake-word-detected', handler);
  },

  onMainWindowVisibility: (callback) => {
    const handler = (_event, visible) => callback(visible);
    ipcRenderer.on('main-window-visibility', handler);
    return () => ipcRenderer.removeListener('main-window-visibility', handler);
  },

  onSwitchView: (callback) => {
    const handler = (_event, view) => callback(view);
    ipcRenderer.on('switch-view', handler);
    return () => ipcRenderer.removeListener('switch-view', handler);
  },

  // OS keychain API key management (uses keytar under the hood)
  storeApiKey: (keyName, value) => ipcRenderer.invoke('store-api-key', keyName, value),
  retrieveApiKey: (keyName) => ipcRenderer.invoke('retrieve-api-key', keyName),
  retrieveApiKeys: () => ipcRenderer.invoke('retrieve-api-keys'),
  deleteApiKey: (keyName) => ipcRenderer.invoke('delete-api-key', keyName),

  getAutostartEnabled: () => ipcRenderer.invoke('get-autostart-enabled'),
  setAutostartEnabled: (enabled) => ipcRenderer.invoke('set-autostart-enabled', enabled),
  getStartMinimized: () => ipcRenderer.invoke('get-start-minimized'),
  setStartMinimized: (enabled) => ipcRenderer.invoke('set-start-minimized', enabled),
});
