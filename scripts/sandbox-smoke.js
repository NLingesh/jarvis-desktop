// Sandbox smoke test: runs Electron WITHOUT the --no-sandbox switch and verifies
// the Chromium sandbox is active by successfully creating a renderer process.
// Exit code 0 = sandbox works; non-zero = sandbox unavailable on this platform.
const { app, BrowserWindow } = require('electron');

app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  try {
    const win = new BrowserWindow({ show: false });
    const result = await new Promise((resolve) => {
      const timer = setTimeout(() => resolve('timeout'), 20000);
      win.webContents.once('did-finish-load', () => {
        clearTimeout(timer);
        resolve('loaded');
      });
      win.webContents.once('did-fail-load', (_e, _code, desc) => {
        clearTimeout(timer);
        resolve('fail:' + desc);
      });
      win.loadURL('data:text/html,<h1>sandbox-test</h1>');
    });
    console.log('SANDBOX_SMOKE_RESULT=' + result);
    app.exit(result === 'loaded' ? 0 : 1);
  } catch (err) {
    console.log('SANDBOX_SMOKE_RESULT=error:' + err.message);
    app.exit(1);
  }
});