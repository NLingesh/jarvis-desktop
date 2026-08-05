const path = require('path');
const fs = require('fs');
const { getCurrentFuseWire, flipFuses, FuseVersion, FuseV1Options } = require('@electron/fuses');

const electronPath = path.join(__dirname, '..', 'node_modules', 'electron', 'dist', 'electron');

if (!fs.existsSync(electronPath)) {
  console.error('[fix-electron-binary] Electron binary not found, skipping fuse fix');
  process.exit(0);
}

async function fixBinary() {
  try {
    const fuseWire = await getCurrentFuseWire(electronPath);
    const runAsNodeValue = fuseWire[FuseV1Options.RunAsNode];
    const isRunAsNodeEnabled = String.fromCharCode(runAsNodeValue) === '1';

    if (isRunAsNodeEnabled) {
      console.log('[fix-electron-binary] Flipping RunAsNode fuse to Disabled...');
      await flipFuses(electronPath, {
        version: fuseWire.version === '1' ? FuseVersion.V1 : FuseVersion.V2,
        RunAsNode: false,
      });
      console.log('[fix-electron-binary] RunAsNode fuse disabled successfully');
    } else {
      console.log('[fix-electron-binary] RunAsNode fuse is already Disabled, nothing to do');
    }
  } catch (err) {
    console.error('[fix-electron-binary] Error:', err.message);
  }
}

fixBinary();
