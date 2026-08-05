const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

module.exports = async function(context) {
  const appDir = context.appOutDir;
  if (!appDir || !fs.existsSync(appDir)) {
    console.error('[fix-fuse-after-pack] App output directory not found:', appDir);
    return;
  }

  const platform = context.electronPlatformName;
  const isWindows = platform === 'win32';
  const baseName = isWindows ? 'electron.exe' : 'electron';
  
  const possibleNames = [
    baseName,
    (context.packager.productName || ''),
    (context.packager.appInfo.productName || ''),
  ].filter(Boolean);

  let electronBinaryPath = null;
  for (const name of possibleNames) {
    const testPath = path.join(appDir, name);
    if (fs.existsSync(testPath) && fs.statSync(testPath).isFile()) {
      electronBinaryPath = testPath;
      break;
    }
  }

  if (!electronBinaryPath) {
    const entries = fs.readdirSync(appDir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isFile() && !entry.name.endsWith('.so') &&
          !entry.name.endsWith('.pak') &&
          !entry.name.startsWith('LICENSE') && !entry.name.startsWith('chrome_') &&
          !entry.name.startsWith('resources') && !entry.name.startsWith('v8_') &&
          !entry.name.startsWith('snapshot') && !entry.name.startsWith('vk_')) {
        const fullPath = path.join(appDir, entry.name);
        try {
          const stat = fs.statSync(fullPath);
          if ((stat.mode & 0o111) && stat.size > 10 * 1024 * 1024) {
            electronBinaryPath = fullPath;
            break;
          }
        } catch (e) {}
      }
    }
  }

  if (!electronBinaryPath || !fs.existsSync(electronBinaryPath)) {
    console.error('[fix-fuse-after-pack] Electron binary not found in:', appDir);
    return;
  }

  console.log('[fix-fuse-after-pack] Flipping RunAsNode fuse on:', path.basename(electronBinaryPath));
  
  try {
    const fusesBin = path.join(
      path.dirname(require.resolve('@electron/fuses')),
      'bin.js'
    );
    execSync(`node "${fusesBin}" write --app "${electronBinaryPath}" RunAsNode=off`, {
      stdio: 'inherit',
      cwd: path.join(__dirname, '..'),
    });
    console.log('[fix-fuse-after-pack] RunAsNode fuse disabled successfully');
  } catch (err) {
    console.error('[fix-fuse-after-pack] Error:', err.message);
  }
};
