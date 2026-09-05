const { app, BrowserWindow, ipcMain, dialog, shell, session, Tray, nativeImage, globalShortcut, Notification } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const crypto = require('crypto');
const { spawn } = require('child_process');
const http = require('http');
const { autoUpdater } = require('electron-updater');

let keytar;
try {
  keytar = require('keytar');
} catch (e) {
  console.warn('[JARVIS] keytar not available; falling back to .env for API keys');
}

const KEYCHAIN_SERVICE = 'jarvis-api-keys';
const MANAGED_KEY_NAMES = [
  'MISTRAL_API_KEY',
  'ANTHROPIC_API_KEY',
  'ELEVENLABS_API_KEY',
  'NVIDIA_API_KEY',
];

const isDev = !app.isPackaged;
const BACKEND_HOST = '127.0.0.1';

if (process.platform !== 'darwin') {
  app.disableHardwareAcceleration();
}
app.commandLine.appendSwitch('no-sandbox', 'true');

function getBackendPort() {
  const envPort = process.env.JARVIS_BACKEND_PORT;
  if (envPort) return parseInt(envPort, 10);

  if (isDev) {
    const envPath = path.join(getBackendDir(), '.env');
    try {
      const content = fs.readFileSync(envPath, 'utf8');
      const match = content.match(/^SERVER_PORT\s*=\s*(.+)$/m);
      if (match) return parseInt(match[1].trim(), 10);
    } catch (e) {
      // .env not found, use default
    }
  } else {
    const userData = app.getPath('userData');
    const userEnvPath = path.join(userData, '.env');
    try {
      const content = fs.readFileSync(userEnvPath, 'utf8');
      const match = content.match(/^SERVER_PORT\s*=\s*(.+)$/m);
      if (match) return parseInt(match[1].trim(), 10);
    } catch (e) {
      // userData/.env not found, use default
    }
  }
  return 8000;
}

const BACKEND_PORT = getBackendPort();
const HEALTH_CHECK_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/health`;
const STARTUP_TIMEOUT_MS = 120000;
const POLL_INTERVAL_MS = 500;

function getAutostartPath() {
  return path.join(app.getPath('home'), '.config', 'autostart', 'jarvis-electron.desktop');
}

function getStartMinimizedPath() {
  return path.join(app.getPath('userData'), 'start-minimized.json');
}

function isAutostartEnabled() {
  try {
    return fs.existsSync(getAutostartPath());
  } catch (e) {
    return false;
  }
}

function setAutostartEnabled(enabled) {
  const autostartDir = path.dirname(getAutostartPath());
  try {
    if (!fs.existsSync(autostartDir)) {
      fs.mkdirSync(autostartDir, { recursive: true });
    }
    if (enabled) {
      const desktopEntry = `[Desktop Entry]
Type=Application
Exec=${process.execPath} --no-sandbox
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=JARVIS
Comment=Start JARVIS with system
`;
      fs.writeFileSync(getAutostartPath(), desktopEntry);
    } else {
      if (fs.existsSync(getAutostartPath())) {
        fs.unlinkSync(getAutostartPath());
      }
    }
  } catch (e) {
    log(`Failed to ${enabled ? 'enable' : 'disable'} autostart: ${e.message}`);
  }
}

function isStartMinimizedEnabled() {
  try {
    const p = getStartMinimizedPath();
    if (!fs.existsSync(p)) return false;
    const data = JSON.parse(fs.readFileSync(p, 'utf8'));
    return !!data.enabled;
  } catch (e) {
    return false;
  }
}

function setStartMinimizedEnabled(enabled) {
  try {
    const p = getStartMinimizedPath();
    fs.writeFileSync(p, JSON.stringify({ enabled }));
  } catch (e) {
    log(`Failed to save start-minimized setting: ${e.message}`);
  }
}

// The Markdown vault folder that the backend reads/writes. Mirrors the
// backend's own resolution so the IPC "open vault" action opens the same dir.
function getVaultPath() {
  if (!isDev) {
    return path.join(app.getPath('userData'), 'JARVIS Memory');
  }
  const envPath = path.join(getBackendDir(), '.env');
  try {
    const content = fs.readFileSync(envPath, 'utf8');
    const match = content.match(/^MEMORY_VAULT_PATH\s*=\s*(.+)$/m);
    if (match) return match[1].trim();
  } catch (e) {
    // .env not found, use default
  }
  return path.join(os.homedir(), 'Documents', 'JARVIS Memory');
}

let mainWindow = null;
let pyProc = null;
let backendStdout = '';
let backendStderr = '';
let shuttingDown = false;
let appIsQuitting = false;
let tray = null;
let sessionToken = '';
let windowMode = 'orb';

// Single expanding window: the app is one frameless transparent window that
// grows from the 72×72 orb, through a larger quick-actions canvas, to the full
// panel sheet. The orb anchor stays screen-stable across every resize.
//
// The "main window" (panel) and the "bubble window" (orb) are two geometry
// modes of this one BrowserWindow. All bounds/position IPC routes through the
// explicit helpers below: `setMainWindowBounds` (guarded by the configured main
// minimum) or `setBubbleBounds`/`setBubblePosition` (compact orb geometry). A
// bubble-sized bounds request can therefore never collapse the main window.
const BUBBLE_WINDOW_SIZE = 72;
const MENU_WINDOW_SIZE = 240;
const MAIN_WINDOW_DEFAULT = { width: 640, height: 640 };
const MAIN_WINDOW_MIN_WIDTH = 640;
const MAIN_WINDOW_MIN_HEIGHT = 640;
const MODE_SPECS = {
  orb: { width: BUBBLE_WINDOW_SIZE, height: BUBBLE_WINDOW_SIZE, anchorX: 36, anchorY: 36 },
  menu: { width: MENU_WINDOW_SIZE, height: MENU_WINDOW_SIZE, anchorX: 120, anchorY: 120 },
  panel: {
    width: MAIN_WINDOW_DEFAULT.width,
    height: MAIN_WINDOW_DEFAULT.height,
    anchorX: 320,
    anchorY: 320,
  },
};

// Diagnostic bounds logging is gated behind an explicit flag; it prints only
// numeric window geometry (never secrets or personal content).
const DEBUG_BOUNDS = process.env.JARVIS_DEBUG_BOUNDS === '1';

function getMainWindow() {
  return mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
}

function logBounds(label, requested, previous, final) {
  if (!DEBUG_BOUNDS) return;
  log(
    `[bounds] ${label} requested=${JSON.stringify(requested)} ` +
      `previous=${JSON.stringify(previous)} final=${JSON.stringify(final)}`,
  );
}

// The only place the main (panel) window may change size. Refuses any request
// below the configured minimum, so a stray bubble geometry (72×72, stale orb
// dims, drag cleanup, etc.) can never collapse the conversation window.
function setMainWindowBounds(win, bounds) {
  if (!win || win.isDestroyed()) return false;
  const { width, height } = bounds;
  if (width < MAIN_WINDOW_MIN_WIDTH || height < MAIN_WINDOW_MIN_HEIGHT) {
    log(
      `[bounds] main-window bounds rejected ${width}x${height} ` +
        `(minimum ${MAIN_WINDOW_MIN_WIDTH}x${MAIN_WINDOW_MIN_HEIGHT})`,
    );
    return false;
  }
  const previous = win.getBounds();
  win.setBounds(bounds);
  logBounds('set-main-bounds', bounds, previous, win.getBounds());
  return true;
}

// Bubble-geometry bounds change (orb/menu). Only ever the compact bubble
// dimensions; it never resizes the main conversation layout.
function setBubbleBounds(win, bounds) {
  if (!win || win.isDestroyed()) return false;
  const previous = win.getBounds();
  win.setBounds(bounds);
  logBounds('set-bubble-bounds', bounds, previous, win.getBounds());
  return true;
}

// Bubble-geometry position change (native-drag persist, drag IPC). Position
// only — never a resize, so a drag-end can never trigger a window resize.
function setBubblePosition(win, x, y) {
  if (!win || win.isDestroyed()) return false;
  const previous = win.getBounds();
  win.setPosition(x, y);
  logBounds('set-bubble-position', { x, y }, previous, win.getBounds());
  return true;
}

function log(msg) {
  const ts = new Date().toISOString();
  console.log(`[JARVIS] ${ts} ${msg}`);
}

function getRoot() {
  if (isDev) {
    return path.join(__dirname, '..');
  }
  // In packaged mode, extraFiles are placed at app root (parent of resources/)
  return path.join(process.resourcesPath, '..');
}

function getVenvPython() {
  const binDir = process.platform === 'win32' ? 'Scripts' : 'bin';
  const exe = process.platform === 'win32' ? 'python.exe' : 'python3';
  return path.join(getRoot(), 'venv', binDir, exe);
}

function getBackendDir() {
  return path.join(getRoot(), 'jarvis_backend');
}

function getMainPyPath() {
  return path.join(getRoot(), 'jarvis_backend', 'main.py');
}

function getPreloadPath() {
  if (isDev) {
    return path.join(__dirname, 'preload.js');
  }
  return path.join(__dirname, 'preload.js');
}

function getIconPath() {
  const root = getRoot();
  const candidates = [
    path.join(root, 'build', 'icons', 'icon-512.png'),
    path.join(root, 'jarvis_frontend', 'public', 'icon-512.png'),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return c;
  }
  return undefined;
}

function getOrbPositionPath() {
  return path.join(app.getPath('userData'), 'orb-position.json');
}

function loadOrbPosition() {
  try {
    const posPath = getOrbPositionPath();
    if (fs.existsSync(posPath)) {
      const data = JSON.parse(fs.readFileSync(posPath, 'utf8'));
      if (typeof data.x === 'number' && typeof data.y === 'number') {
        return { x: data.x, y: data.y };
      }
    }
  } catch (e) {
    log(`Failed to load orb position: ${e.message}`);
  }
  return null;
}

function saveOrbPosition(x, y) {
  try {
    fs.writeFileSync(getOrbPositionPath(), JSON.stringify({ x, y }));
  } catch (e) {
    log(`Failed to save orb position: ${e.message}`);
  }
}

function getDefaultOrbPosition() {
  const { screen } = require('electron');
  const display = screen.getPrimaryDisplay();
  const { x, y, width, height } = display.workArea;
  return { x: x + width - BUBBLE_WINDOW_SIZE - 24, y: y + height - BUBBLE_WINDOW_SIZE - 24 };
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(v, max));
}

// The orb anchor (where the orb should sit) for the current window mode, in
// window-local coordinates.
function currentOrbAnchor() {
  const spec = MODE_SPECS[windowMode] || MODE_SPECS.orb;
  return { x: spec.anchorX, y: spec.anchorY };
}

// Where the orb currently sits on screen (window top-left + anchor).
function currentOrbCenter() {
  const win = getMainWindow();
  if (!win) return getDefaultOrbPosition();
  const [x, y] = win.getPosition();
  const a = currentOrbAnchor();
  return { x: x + a.x, y: y + a.y };
}

function applyWindowMode(mode, cx, cy) {
  const win = getMainWindow();
  if (!win) return { x: cx, y: cy };
  const spec = MODE_SPECS[mode] || MODE_SPECS.orb;
  const area = getWorkArea();
  const centerX = typeof cx === 'number' ? cx : currentOrbCenter().x;
  const centerY = typeof cy === 'number' ? cy : currentOrbCenter().y;
  const x = clamp(Math.round(centerX - spec.anchorX), area.x, area.x + area.width - spec.width);
  const y = clamp(Math.round(centerY - spec.anchorY), area.y, area.y + area.height - spec.height);
  const bounds = { x, y, width: spec.width, height: spec.height };
  // Panel mode is the main conversation window (guarded by its minimum size);
  // orb/menu are bubble-geometry modes and can never touch main-window bounds.
  const applied =
    mode === 'panel' ? setMainWindowBounds(win, bounds) : setBubbleBounds(win, bounds);
  if (!applied) return { x: centerX, y: centerY };
  windowMode = mode;
  const appliedCenter = { x: x + spec.anchorX, y: y + spec.anchorY };
  saveOrbPosition(appliedCenter.x, appliedCenter.y);
  return appliedCenter;
}

function sendToRenderer(channel, ...args) {
  if (mainWindow && mainWindow.webContents && !mainWindow.webContents.isDestroyed()) {
    mainWindow.webContents.send(channel, ...args);
  }
}

async function setupFirstRun() {
  if (isDev) return;

  const userData = app.getPath('userData');
  const userEnvPath = path.join(userData, '.env');

  if (fs.existsSync(userEnvPath)) return;

  const exampleEnvPath = path.join(getBackendDir(), '.env.example');
  if (!fs.existsSync(exampleEnvPath)) return;

  try {
    fs.copyFileSync(exampleEnvPath, userEnvPath);
  } catch (err) {
    log(`Failed to copy .env.example to userData: ${err.message}`);
    return;
  }

  const filePathDisplay = userEnvPath;

  dialog.showMessageBoxSync({
    type: 'info',
    title: 'JARVIS - First Run Setup',
    message: 'Welcome to JARVIS!',
    detail: `A configuration file has been created at:\n\n${filePathDisplay}\n\nPlease add your API keys to this file before using JARVIS. The backend will not work correctly without valid API keys.\n\nAfter editing the file, restart JARVIS for the changes to take effect.`,
    buttons: ['OK'],
  });

  try {
    shell.openPath(userEnvPath);
  } catch (err) {
    log(`Could not open editor for ${userEnvPath}: ${err.message}`);
  }
}

async function waitForBackend(timeoutMs) {
  log(`Polling ${HEALTH_CHECK_URL} (timeout ${timeoutMs}ms)`);
  const start = Date.now();

  while (Date.now() - start < timeoutMs) {
    try {
      const result = await new Promise((resolve) => {
        const req = http.get(HEALTH_CHECK_URL, (res) => {
          let body = '';
          res.on('data', (chunk) => { body += chunk; });
          res.on('end', () => {
            resolve({ status: res.statusCode, body });
          });
        });
        req.on('error', () => resolve(null));
        req.setTimeout(2000, () => {
          req.destroy();
          resolve(null);
        });
      });

      if (result && result.status === 200) {
        log('Backend health check passed');
        return true;
      }
    } catch (err) {
      // Connection refused – keep retrying
    }

    const elapsed = Math.round((Date.now() - start) / 1000);
    log(`Health check not ready (${elapsed}s elapsed), retrying...`);
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }

  log('Backend did not become ready within timeout');
  return false;
}

function createWindow() {
  log('Creating BrowserWindow');

  // JARVIS is a voice-first assistant, so always allow microphone/camera access
  // from the local renderer without requiring a system permission prompt.
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowed = [
      'media', 'microphone', 'audioCapture',
    ];
    const granted = allowed.includes(permission) && webContents.getURL().startsWith('http://127.0.0.1');
    if (!granted) {
      log(`Denying permission request: ${permission}`);
    }
    callback(granted);
  });
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    if (permission === 'media' || permission === 'microphone' || permission === 'audioCapture') {
      return true;
    }
    return false;
  });

  const spec = MODE_SPECS.orb;
  const area = getWorkArea();
  const saved = loadOrbPosition() || getDefaultOrbPosition();
  const x = clamp(Math.round(saved.x - spec.anchorX), area.x, area.x + area.width - spec.width);
  const y = clamp(Math.round(saved.y - spec.anchorY), area.y, area.y + area.height - spec.height);

  mainWindow = new BrowserWindow({
    width: spec.width,
    height: spec.height,
    x,
    y,
    minWidth: spec.width,
    minHeight: spec.height,
    maxWidth: MAIN_WINDOW_DEFAULT.width,
    maxHeight: MAIN_WINDOW_DEFAULT.height,
    resizable: false,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    center: false,
    title: 'JARVIS',
    backgroundColor: '#00000000',
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      enableRemoteModule: false,
    },
    icon: getIconPath(),
  });

  // Ctrl+Space toggles voice capture. While the window is focused this event
  // fires first (and prevents the key reaching the page); when the window is
  // not focused, the global shortcut below provides the same toggle.
  let ctrlSpaceDown = false;
  mainWindow.webContents.on('before-input-event', (event, input) => {
    const controlKey = input.key === 'Control' || input.code === 'ControlLeft' || input.code === 'ControlRight';
    if (input.type === 'keyDown' && input.code === 'Space' && input.control) {
      if (ctrlSpaceDown) return; // ignore OS key auto-repeat
      ctrlSpaceDown = true;
      event.preventDefault();
      log('[shortcut] Ctrl+Space pressed while focused (toggle voice)');
      sendToRenderer('voice-control', 'toggle');
    } else if (input.type === 'keyUp' && ctrlSpaceDown && (input.code === 'Space' || controlKey)) {
      ctrlSpaceDown = false;
      event.preventDefault();
    }
  });

  mainWindow.loadURL(`http://${BACKEND_HOST}:${BACKEND_PORT}`);
  windowMode = 'orb';

  // Restrict navigation to the local backend origin so the preload bridge
  // (which exposes the session token and keychain API) can never be handed to
  // an untrusted page.
  const allowedOrigin = `http://${BACKEND_HOST}:${BACKEND_PORT}`;
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(allowedOrigin)) {
      event.preventDefault();
    }
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(allowedOrigin)) return { action: 'allow' };
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-attach-webview', (event) => {
    event.preventDefault();
  });

  mainWindow.on('moved', () => {
    const c = currentOrbCenter();
    saveOrbPosition(c.x, c.y);
  });

  // Native dragging is handled by the OS (`-webkit-app-region: drag`), so no
  // renderer/JS loop moves the window. While a native drag is in progress the
  // renderer pauses nonessential CSS animations to avoid compositor artifacts
  // on the transparent window. A short debounce turns the flag off once the
  // window stops moving (drag end, or restore/setPosition that settles).
  let dragStateTimer = null;
  const sendDragState = (dragging) => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (windowMode !== 'orb') return;
    if (dragStateTimer) clearTimeout(dragStateTimer);
    if (dragging) {
      sendToRenderer('window-drag-state', true);
      dragStateTimer = setTimeout(() => sendDragState(false), 200);
    } else {
      sendToRenderer('window-drag-state', false);
    }
  };
  mainWindow.on('move', () => sendDragState(true));

  mainWindow.on('closed', () => {
    log('Panel window closed');
    mainWindow = null;
  });
}

async function startBackend() {
  const pythonPath = getVenvPython();
  const mainPy = getMainPyPath();
  const backendDir = getBackendDir();

  log(`Starting backend: ${pythonPath} ${mainPy}`);
  log(`Working directory: ${backendDir}`);

  const env = { ...process.env };
  env.SERVER_PORT = String(BACKEND_PORT);

  // Always generate a session token and pass it to the backend via env, so the
  // frontend's /ws/voice handshake succeeds in dev mode too (without it the
  // backend generates an unknown token and rejects every connection).
  const token = crypto.randomBytes(32).toString('hex');
  env.SESSION_TOKEN = token;
  sessionToken = token;

  if (!isDev) {
    // Retrieve API keys from OS keychain and inject into backend env
    if (keytar) {
      for (const keyName of MANAGED_KEY_NAMES) {
        const storedValue = await keytar.getPassword(KEYCHAIN_SERVICE, keyName);
        if (storedValue) {
          env[keyName] = storedValue;
          log(`Injected ${keyName} from OS keychain`);
        }
      }
    }

    const userData = app.getPath('userData');
    env.DATABASE_PATH = path.join(userData, 'jarvis_memory.db');
    env.ENV_PATH = path.join(userData, '.env');
    env.MEMORY_VAULT_PATH = getVaultPath();

    const tokenDir = path.join(userData, 'secrets');
    env.SESSION_TOKEN_PATH = path.join(tokenDir, 'session.token');
    if (!fs.existsSync(tokenDir)) {
      fs.mkdirSync(tokenDir, { recursive: true });
    }
    fs.writeFileSync(env.SESSION_TOKEN_PATH, token);
    fs.chmodSync(env.SESSION_TOKEN_PATH, 0o600);
    log(`Session token written to: ${env.SESSION_TOKEN_PATH}`);

    log(`Database path (packaged): ${env.DATABASE_PATH}`);
    log(`ENV_PATH (packaged): ${env.ENV_PATH}`);
  }

  pyProc = spawn(pythonPath, [mainPy], {
    cwd: backendDir,
    env: env,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
  });

  pyProc.stdout.on('data', (data) => {
    const text = data.toString();
    backendStdout += text;
    const lines = text.trim().split('\n');
    for (const line of lines) {
      if (line.trim()) log(`[backend] ${line.trim()}`);
    }
  });

  pyProc.stderr.on('data', (data) => {
    const text = data.toString();
    backendStderr += text;
    const lines = text.trim().split('\n');
    for (const line of lines) {
      if (line.trim()) log(`[backend:err] ${line.trim()}`);
    }
  });

  pyProc.on('error', (err) => {
    log(`Failed to start backend process: ${err.message}`);
  });

  pyProc.on('exit', (code, signal) => {
    log(`Backend process exited (code=${code}, signal=${signal})`);
  });
}

function stopBackend() {
  if (!pyProc) return;

  if (pyProc.killed || shuttingDown) return;
  shuttingDown = true;

  log('Stopping backend process (SIGTERM)...');
  pyProc.kill('SIGTERM');

  const forceKillTimer = setTimeout(() => {
    if (!pyProc.killed) {
      log('Backend did not exit, sending SIGKILL');
      pyProc.kill('SIGKILL');
    }
  }, 5000);

  pyProc.on('exit', () => {
    clearTimeout(forceKillTimer);
    log('Backend process stopped');
  });
}

function getWorkArea() {
  const { screen } = require('electron');
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workArea;
  return { x: display.bounds.x, y: display.bounds.y, width, height };
}

function togglePanel() {
  sendToRenderer('toggle-panel');
}

function openPanel() {
  sendToRenderer('open-panel');
}

function closePanel() {
  sendToRenderer('close-panel');
}

function updatePanelPosition(x, y) {
  const win = getMainWindow();
  if (!win) return;
  const area = getWorkArea();
  const [width, height] = win.getSize();
  const clampedX = Math.max(area.x + 10, Math.min(x, area.x + area.width - width - 10));
  const clampedY = Math.max(area.y + 10, Math.min(y, area.y + area.height - height - 10));
  setBubblePosition(win, clampedX, clampedY);
}

function showMainWindow() {
  if (!mainWindow) createWindow();
  mainWindow.show();
  mainWindow.focus();
}

function showMainWindowFromWakeWord() {
  showMainWindow();
  if (mainWindow && mainWindow.webContents) {
    const sendWake = () => sendToRenderer('wake-word-detected');
    // The window is created eagerly, but on a cold wake the renderer may not
    // have mounted yet; deliver the wake event once the page finished loading.
    if (mainWindow.webContents.isLoading()) {
      mainWindow.webContents.once('did-finish-load', () => setTimeout(sendWake, 500));
    } else {
      sendWake();
    }
  }
}

function hideMainWindow() {
  // The single window is always present as the orb; hiding would remove the
  // companion entirely, so this is a no-op kept for IPC compatibility.
}

function toggleMainWindow() {
  togglePanel();
}

function buildOrbContextMenu() {
  const { Menu } = require('electron');
  const template = [
    { label: 'Talk', click: () => sendToRenderer('context-menu-action', 'talk') },
    { label: 'Pause', click: () => sendToRenderer('context-menu-action', 'pause') },
    { type: 'separator' },
    { label: 'Settings', click: () => sendToRenderer('context-menu-action', 'settings') },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        appIsQuitting = true;
        app.quit();
      },
    },
  ];
  return Menu.buildFromTemplate(template);
}

function createTray() {
  const iconPath = path.join(getRoot(), 'build', 'icons', 'icon-16.png');
  const trayIcon = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();

  tray = new Tray(trayIcon);

  const contextMenu = require('electron').Menu.buildFromTemplate([
    {
      label: 'Toggle Panel',
      click: () => togglePanel(),
    },
    {
      label: 'Talk',
      click: () => sendToRenderer('voice-control', 'start'),
    },
    {
      label: 'Memory',
      click: () => sendToRenderer('switch-view', 'memory'),
    },
    {
      label: 'Files',
      click: () => sendToRenderer('switch-view', 'files'),
    },
    {
      label: 'Settings',
      click: () => sendToRenderer('switch-view', 'settings'),
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        appIsQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setToolTip('JARVIS');
  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    togglePanel();
  });
}

async function init() {
  log('Electron app ready');
  log(`Mode: ${isDev ? 'development' : 'production (packaged)'}`);

  if (!isDev) {
    await setupFirstRun();
  }

  const alreadyHealthy = await waitForBackend(2000);
  if (!alreadyHealthy) {
    startBackend();
    const ready = await waitForBackend(STARTUP_TIMEOUT_MS);
    if (!ready) {
      const detail = backendStdout || '(no stdout)';
      const stderr = backendStderr || '(no stderr)';
      const fullDetail = `STDOUT:\n${detail}\n\nSTDERR:\n${stderr}`;

      dialog.showErrorBox(
        'JARVIS Backend Failed to Start',
        `The backend server did not become ready within ${STARTUP_TIMEOUT_MS / 1000} seconds.\n\n` +
        `Health check URL: ${HEALTH_CHECK_URL}\n\n` +
        `Backend output:\n${fullDetail}`
      );
      app.quit();
      return;
    }
  } else {
    log('Reusing existing backend');
    try {
      const tokenResult = await new Promise((resolve) => {
        http.get(`http://${BACKEND_HOST}:${BACKEND_PORT}/api/session-token`, (res) => {
          let body = '';
          res.on('data', (chunk) => { body += chunk; });
          res.on('end', () => resolve(body));
        }).on('error', () => resolve(null));
      });
      if (tokenResult) {
        const parsed = JSON.parse(tokenResult);
        if (parsed.token) {
          sessionToken = parsed.token;
          log('Retrieved existing session token');
        }
      }
    } catch (err) {
      log(`Failed to retrieve session token: ${err.message}`);
    }
  }

  if (!isStartMinimizedEnabled()) {
    createWindow();
  }
  createTray();

  // Ctrl+Space toggles the voice session from anywhere on the desktop (the orb
  // is always present and often unfocused). Register in dev and prod alike.
  const voiceShortcut = process.env.VOICE_SHORTCUT || 'Control+Space';
  try {
    globalShortcut.register(voiceShortcut, () => {
      // When focused, before-input-event provides true press/release semantics.
      // Keep the legacy toggle behavior as a global fallback in the background.
      if (!mainWindow || !mainWindow.isFocused()) {
        log('[shortcut] Ctrl+Space received (global toggle)');
        sendToRenderer('voice-control', 'toggle');
      }
    });
    log(`Registered global shortcut: ${voiceShortcut}`);
  } catch (err) {
    log(`Failed to register global shortcut ${voiceShortcut}: ${err.message}`);
  }

  const toggleShortcut = process.env.GLOBAL_SHORTCUT || 'CommandOrControl+Shift+J';
  try {
    globalShortcut.register(toggleShortcut, () => {
      toggleMainWindow();
    });
    log(`Registered global shortcut: ${toggleShortcut}`);
  } catch (err) {
    log(`Failed to register global shortcut ${toggleShortcut}: ${err.message}`);
  }

autoUpdater.on('checking-for-update', () => {
  log('Checking for updates...');
});

autoUpdater.on('update-available', (info) => {
  log(`Update available: v${info.version}`);
  if (mainWindow) {
    dialog.showMessageBox({
      type: 'info',
      title: 'Update Available',
      message: `A new version of JARVIS (v${info.version}) is available.`,
      detail: 'The update will be downloaded in the background. It will be installed when you restart the app.',
      buttons: ['OK', 'Install Now'],
      cancelId: 0,
    }).then((result) => {
      if (result.response === 1) {
        autoUpdater.quitAndInstall();
      }
    });
  } else {
    autoUpdater.downloadUpdate();
  }
});

autoUpdater.on('update-not-available', () => {
  log('No updates available');
});

autoUpdater.on('error', (err) => {
  log(`Update error: ${err == null ? 'unknown' : err.message}`);
  if (mainWindow) {
    dialog.showErrorBox(
      'Update Error',
      `Failed to check for updates: ${err == null ? 'unknown error' : err.message}`
    );
  }
});

autoUpdater.on('update-downloaded', (info) => {
  log(`Update downloaded: v${info.version}`);
  const response = dialog.showMessageBoxSync({
    type: 'info',
    title: 'Update Ready',
    message: `JARVIS v${info.version} has been downloaded.`,
    detail: 'Restart now to install the update.',
    buttons: ['Restart Now', 'Later'],
    cancelId: 1,
  });
  if (response === 0) {
    autoUpdater.quitAndInstall();
  }
});

autoUpdater.on('download-progress', (progressObj) => {
  log(`Download progress: ${Math.round(progressObj.percent)}%`);
});

if (!isDev) {
    autoUpdater.checkForUpdatesAndNotify();
  }
}

ipcMain.handle('get-app-version', () => app.getVersion());
ipcMain.handle('get-platform', () => process.platform);
ipcMain.handle('reload-window', () => {
  if (mainWindow) mainWindow.reload();
});
ipcMain.handle('toggle-main-window', () => toggleMainWindow());
ipcMain.handle('show-main-window', () => showMainWindow());
ipcMain.handle('hide-main-window', () => hideMainWindow());

ipcMain.handle('toggle-panel', () => togglePanel());
ipcMain.handle('open-panel', () => openPanel());
ipcMain.handle('close-panel', () => closePanel());
ipcMain.handle('update-panel-position', (_event, x, y) => updatePanelPosition(x, y));
ipcMain.handle('get-work-area', () => getWorkArea());

ipcMain.handle('set-window-mode', (_event, mode, cx, cy) => {
  return applyWindowMode(mode, cx, cy);
});
ipcMain.handle('get-orb-position', () => {
  const c = currentOrbCenter();
  return c;
});
ipcMain.handle('set-orb-position', (_event, cx, cy) => {
  const win = getMainWindow();
  if (!win) return { x: cx, y: cy };
  // Bubble position requests only ever move the compact orb window. If the
  // window is currently the main conversation panel, a stale bubble request
  // must not reposition (or resize) it — ignore it.
  if (windowMode === 'panel') {
    log('[bounds] set-orb-position ignored: window is in main (panel) mode');
    return currentOrbCenter();
  }
  const a = currentOrbAnchor();
  const area = getWorkArea();
  const [width, height] = win.getSize();
  const x = clamp(Math.round(cx - a.x), area.x, area.x + area.width - width);
  const y = clamp(Math.round(cy - a.y), area.y, area.y + area.height - height);
  setBubblePosition(win, x, y);
  const appliedCenter = { x: x + a.x, y: y + a.y };
  saveOrbPosition(appliedCenter.x, appliedCenter.y);
  return appliedCenter;
});
ipcMain.handle('show-context-menu', () => {
  buildOrbContextMenu().popup({ window: mainWindow });
});
ipcMain.handle('quit-app', () => {
  appIsQuitting = true;
  app.quit();
});

ipcMain.handle('request-permission', async (_event, permission) => {
  const result = await dialog.showMessageBox({
    type: 'question',
    title: 'JARVIS Permission',
    message: `JARVIS requests permission to ${permission}`,
    detail: 'This permission is required for the requested action. You can change this later in Settings.',
    buttons: ['Allow', 'Deny'],
    defaultId: 1,
    cancelId: 1,
  });
  return { granted: result.response === 0 };
});
ipcMain.handle('notify-wake-word-detected', () => {
  showMainWindowFromWakeWord();
});
ipcMain.handle('get-session-token', () => sessionToken);

ipcMain.handle('voice-log', (_event, payload) => {
  const line = `[voice] ${JSON.stringify(payload)}`;
  log(line);
  try {
    const file = path.join(app.getPath('userData'), 'voice.log');
    fs.appendFileSync(file, `${line}\n`);
  } catch (err) {
    // A diagnostics log write must never break the voice pipeline.
  }
  return { ok: true };
});

ipcMain.handle('show-notification', (_event, { title, body }) => {
  try {
    if (!Notification.isSupported()) return { success: false, error: 'not supported' };
    new Notification({ title, body }).show();
    return { success: true };
  } catch (err) {
    log(`Could not show notification: ${err.message}`);
    return { success: false, error: err.message };
  }
});

ipcMain.handle('bubble-voice-control', (_event, action) => {
  sendToRenderer('voice-control', action);
});

ipcMain.handle('switch-view', (_event, view) => {
  sendToRenderer('switch-view', view);
});


ipcMain.handle('get-vault-path', () => getVaultPath());
ipcMain.handle('open-vault', async () => {
  const vaultPath = getVaultPath();
  try {
    await shell.openPath(vaultPath);
    return { ok: true, path: vaultPath };
  } catch (err) {
    log(`Could not open vault folder: ${err.message}`);
    return { ok: false, path: vaultPath, error: err.message };
  }
});

ipcMain.handle('store-api-key', async (_event, keyName, value) => {
  if (!keytar) return { success: false, error: 'keytar unavailable' };
  if (keytar && MANAGED_KEY_NAMES.includes(keyName)) {
    await keytar.setPassword(KEYCHAIN_SERVICE, keyName, value);
    log(`API key ${keyName} stored in OS keychain`);
    return { success: true };
  }
  return { success: false, error: `Unknown key: ${keyName}` };
});

ipcMain.handle('retrieve-api-key', async (_event, keyName) => {
  if (!keytar) return null;
  return await keytar.getPassword(KEYCHAIN_SERVICE, keyName);
});

ipcMain.handle('retrieve-api-keys', async () => {
  if (!keytar) return {};
  const result = {};
  for (const name of MANAGED_KEY_NAMES) {
    const val = await keytar.getPassword(KEYCHAIN_SERVICE, name);
    if (val) result[name] = val;
  }
  return result;
});

ipcMain.handle('delete-api-key', async (_event, keyName) => {
  if (!keytar) return { success: false, error: 'keytar unavailable' };
  await keytar.deletePassword(KEYCHAIN_SERVICE, keyName);
  return { success: true };
});

ipcMain.handle('get-autostart-enabled', () => {
  return isAutostartEnabled();
});

ipcMain.handle('set-autostart-enabled', (_event, enabled) => {
  setAutostartEnabled(enabled);
  return { success: true };
});

ipcMain.handle('get-start-minimized', () => {
  return isStartMinimizedEnabled();
});

ipcMain.handle('set-start-minimized', (_event, enabled) => {
  setStartMinimizedEnabled(enabled);
  return { success: true };
});

app.whenReady().then(init);

app.on('window-all-closed', () => {
  log('All windows closed');
  stopBackend();
});

app.on('before-quit', () => {
  appIsQuitting = true;
  globalShortcut.unregisterAll();
  log('Application quitting');
  stopBackend();
});

app.on('quit', () => {
  log('Application quit');
  stopBackend();
});

process.on('exit', () => {
  stopBackend();
});

process.on('SIGINT', () => {
  log('Received SIGINT');
  stopBackend();
  process.exit(0);
});

process.on('SIGTERM', () => {
  log('Received SIGTERM');
  stopBackend();
  process.exit(0);
});

process.on('uncaughtException', (err) => {
  log(`Uncaught exception: ${err.message}`);
  stopBackend();
});
