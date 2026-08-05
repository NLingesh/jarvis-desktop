const { app, BrowserWindow, ipcMain, dialog, shell, session, Tray, nativeImage, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { spawn } = require('child_process');
const http = require('http');
const { autoUpdater } = require('electron-updater');

const isDev = !app.isPackaged;
const BACKEND_HOST = '127.0.0.1';

if (process.platform !== 'darwin') {
  app.disableHardwareAcceleration();
}
app.commandLine.appendSwitch('no-sandbox', 'true');
app.commandLine.appendSwitch('disable-gpu', 'true');
app.commandLine.appendSwitch('disable-gpu-compositing', 'true');

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

let mainWindow = null;
let bubbleWindow = null;
let pyProc = null;
let backendStdout = '';
let backendStderr = '';
let shuttingDown = false;
let appIsQuitting = false;
let tray = null;
let sessionToken = '';

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

function getBubblePositionPath() {
  return path.join(app.getPath('userData'), 'bubble-position.json');
}

function loadBubblePosition() {
  try {
    const posPath = getBubblePositionPath();
    if (fs.existsSync(posPath)) {
      const data = JSON.parse(fs.readFileSync(posPath, 'utf8'));
      if (typeof data.x === 'number' && typeof data.y === 'number') {
        return data;
      }
    }
  } catch (e) {
    log(`Failed to load bubble position: ${e.message}`);
  }
  return null;
}

function saveBubblePosition(x, y) {
  try {
    fs.writeFileSync(getBubblePositionPath(), JSON.stringify({ x, y }));
  } catch (e) {
    log(`Failed to save bubble position: ${e.message}`);
  }
}

function getDefaultBubblePosition() {
  const { screen } = require('electron');
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;
  return { x: width - 96, y: height - 96 };
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

  mainWindow = new BrowserWindow({
    width: 480,
    height: 720,
    minWidth: 400,
    minHeight: 600,
    resizable: true,
    center: true,
    frame: true,
    autoHideMenuBar: true,
    titleBarStyle: 'default',
    backgroundColor: '#0a0a0a',
    title: 'JARVIS',
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

  mainWindow.loadURL(`http://${BACKEND_HOST}:${BACKEND_PORT}`);

  mainWindow.on('close', (e) => {
    if (!appIsQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    log('Window closed');
    mainWindow = null;
  });
}

function startBackend() {
  const pythonPath = getVenvPython();
  const mainPy = getMainPyPath();
  const backendDir = getBackendDir();

  log(`Starting backend: ${pythonPath} ${mainPy}`);
  log(`Working directory: ${backendDir}`);

  const env = { ...process.env };
  env.SERVER_PORT = String(BACKEND_PORT);

  if (!isDev) {
    const userData = app.getPath('userData');
    env.DATABASE_PATH = path.join(userData, 'jarvis_memory.db');
    env.ENV_PATH = path.join(userData, '.env');

    const tokenDir = path.join(userData, 'secrets');
    env.SESSION_TOKEN_PATH = path.join(tokenDir, 'session.token');
    if (!fs.existsSync(tokenDir)) {
      fs.mkdirSync(tokenDir, { recursive: true });
    }
    const token = crypto.randomBytes(32).toString('hex');
    fs.writeFileSync(env.SESSION_TOKEN_PATH, token);
    fs.chmodSync(env.SESSION_TOKEN_PATH, 0o600);
    env.SESSION_TOKEN = token;
    sessionToken = token;
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

function createBubbleWindow() {
  if (bubbleWindow) return;

  const bubbleUrl = `http://${BACKEND_HOST}:${BACKEND_PORT}/bubble.html`;

  const savedPos = loadBubblePosition();
  const defaultPos = getDefaultBubblePosition();
  const initialPos = savedPos || defaultPos;

  bubbleWindow = new BrowserWindow({
    width: 80,
    height: 80,
    x: initialPos.x,
    y: initialPos.y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    center: false,
    title: 'JARVIS Bubble',
    webPreferences: {
      preload: getPreloadPath(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      enableRemoteModule: false,
    },
  });

  bubbleWindow.loadURL(bubbleUrl);

  bubbleWindow.on('moved', () => {
    const [x, y] = bubbleWindow.getPosition();
    saveBubblePosition(x, y);
  });

  bubbleWindow.on('closed', () => {
    log('Bubble window closed');
    bubbleWindow = null;
  });

  bubbleWindow.on('close', (e) => {
    if (!appIsQuitting) {
      e.preventDefault();
      bubbleWindow.hide();
    }
  });
}

function showMainWindow(nearBubble = false) {
  if (!mainWindow) {
    createWindow();
  }

  if (nearBubble && bubbleWindow) {
    const [bubbleX, bubbleY] = bubbleWindow.getPosition();
    const [mainWidth, mainHeight] = mainWindow.getSize();
    const { screen } = require('electron');
    const display = screen.getPrimaryDisplay();
    const { width, height } = display.workAreaSize;

    let x = bubbleX - mainWidth + 80;
    let y = bubbleY - mainHeight + 80;

    if (x < 0) x = 20;
    if (y < 0) y = 20;
    if (x + mainWidth > width) x = width - mainWidth - 20;
    if (y + mainHeight > height) y = height - mainHeight - 20;

    mainWindow.setPosition(x, y);
  }

  mainWindow.show();
  mainWindow.focus();
}

function showMainWindowFromWakeWord(nearBubble = false) {
  showMainWindow(nearBubble);
  if (mainWindow && mainWindow.webContents) {
    mainWindow.webContents.send('wake-word-detected');
  }
}

function hideMainWindow() {
  if (mainWindow) {
    mainWindow.hide();
  }
}

function toggleMainWindow() {
  if (mainWindow && mainWindow.isVisible()) {
    hideMainWindow();
  } else {
    showMainWindow(true);
  }
}

function createTray() {
  const iconPath = path.join(getRoot(), 'build', 'icons', 'icon-16.png');
  const trayIcon = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();

  tray = new Tray(trayIcon);

  const contextMenu = require('electron').Menu.buildFromTemplate([
    {
      label: 'Show JARVIS',
      click: () => showMainWindow(true),
    },
    {
      label: 'Hide bubble',
      click: () => {
        if (bubbleWindow) {
          bubbleWindow.hide();
        }
      },
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
    toggleMainWindow();
  });
}

async function init() {
  log('Electron app ready');
  log(`Mode: ${isDev ? 'development' : 'production (packaged)'}`);

  if (!isDev) {
    await setupFirstRun();
  }

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

  createBubbleWindow();
  createTray();

  if (!isDev) {
    const shortcut = process.env.GLOBAL_SHORTCUT || 'CommandOrControl+Shift+J';
    globalShortcut.register(shortcut, () => {
      toggleMainWindow();
    });
    log(`Registered global shortcut: ${shortcut}`);

    autoUpdater.checkForUpdatesAndNotify();
  }
}

ipcMain.handle('get-app-version', () => app.getVersion());
ipcMain.handle('get-platform', () => process.platform);
ipcMain.handle('reload-window', () => {
  if (mainWindow) mainWindow.reload();
});
ipcMain.handle('toggle-main-window', () => toggleMainWindow());
ipcMain.handle('show-main-window', () => showMainWindow(true));
ipcMain.handle('hide-main-window', () => hideMainWindow());
ipcMain.handle('get-bubble-position', () => {
  if (bubbleWindow) {
    return bubbleWindow.getPosition();
  }
  return getDefaultBubblePosition();
});
ipcMain.handle('set-bubble-position', (_event, x, y) => {
  if (bubbleWindow) {
    bubbleWindow.setPosition(x, y);
    saveBubblePosition(x, y);
  }
});
ipcMain.handle('notify-wake-word-detected', () => {
  showMainWindowFromWakeWord(true);
});
ipcMain.handle('get-session-token', () => sessionToken);

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
