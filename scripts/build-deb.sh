#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/release"
DEB_BUILD="$PROJECT_ROOT/deb-build"

echo "[build-deb] Starting JARVIS .deb build"

cd "$PROJECT_ROOT"

echo "[build-deb] Step 1: Building frontend"
npm run build

echo "[build-deb] Step 2: Packaging backend venv"
bash "$SCRIPT_DIR/prepare-venv.sh"

echo "[build-deb] Step 3: Building Electron app with electron-builder"
npx electron-builder --config electron-builder.json --linux dir

echo "[build-deb] Step 4: Extracting app.asar and preparing unpacked app"
UNPACKED="$OUTPUT_DIR/linux-unpacked"
if [ -f "$UNPACKED/resources/app.asar" ]; then
    echo "[build-deb] Extracting app.asar"
    npx asar extract "$UNPACKED/resources/app.asar" "$UNPACKED/resources/app"
    rm -f "$UNPACKED/resources/app.asar"
fi

echo "[build-deb] Step 5: Copying node_modules"
if [ -d "$PROJECT_ROOT/node_modules" ]; then
    cp -r "$PROJECT_ROOT/node_modules" "$UNPACKED/resources/node_modules"
fi

echo "[build-deb] Step 6: Cleaning development files from backend"
find "$UNPACKED/jarvis_backend" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name "*.pyc" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name "*.log" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name ".env.example" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name ".env" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name "pytest.ini" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name "*.md" -delete 2>/dev/null || true
find "$UNPACKED/jarvis_backend" -name ".pytest_cache" -type d -exec rm -rf {} + 2>/dev/null || true

echo "[build-deb] Step 7: Creating .deb staging directory"
rm -rf "$DEB_BUILD"
mkdir -p "$DEB_BUILD/DEBIAN"
mkdir -p "$DEB_BUILD/opt/JARVIS"
mkdir -p "$DEB_BUILD/usr/share/applications"
mkdir -p "$DEB_BUILD/usr/share/icons/hicolor/512x512/apps"
mkdir -p "$DEB_BUILD/usr/share/icons/hicolor/192x192/apps"

echo "[build-deb] Step 8: Copying application files"
rsync -a "$UNPACKED/" "$DEB_BUILD/opt/JARVIS/"

echo "[build-deb] Step 9: Installing desktop entry and icons"
cp "$PROJECT_ROOT/build/icons/icon-512.png" "$DEB_BUILD/usr/share/icons/hicolor/512x512/apps/jarvis-electron.png"
cp "$PROJECT_ROOT/build/icons/icon-192.png" "$DEB_BUILD/usr/share/icons/hicolor/192x192/apps/jarvis-electron.png"

cat > "$DEB_BUILD/usr/share/applications/jarvis-electron.desktop" << 'EOF'
[Desktop Entry]
Name=JARVIS
Comment=Personal AI Desktop Companion
GenericName=AI Assistant
Exec=/opt/JARVIS/jarvis-electron --no-sandbox
Icon=jarvis-electron
StartupNotify=true
Terminal=false
Type=Application
Categories=Utility;ArtificialIntelligence;
MimeType=
Keywords=ai;assistant;voice;jarvis;
EOF

echo "[build-deb] Step 10: Creating Debian control files"
cat > "$DEB_BUILD/DEBIAN/control" << 'EOF'
Package: jarvis-electron
Version: 1.0.0
Section: utils
Priority: optional
Architecture: amd64
Depends: libgtk-3-0, libnotify4, libnss3, libxss1, libxtst6, xdg-utils, libatspi2.0-0, libuuid1, libsecret-1-0
Recommends: libappindicator3-1
Maintainer: JARVIS Team <noreply@jarvis.app>
Description: JARVIS Personal AI Desktop Companion
 JARVIS is a voice-first AI desktop assistant with file management,
 system integration, and local memory capabilities.
 .
 Features include voice control, STT/TTS, local LLM integration,
 file and application management, and an always-visible Orb UI.
EOF

cat > "$DEB_BUILD/DEBIAN/postinst" << 'EOF'
#!/bin/bash
set -e

mkdir -p "$HOME/.config/jarvis" "$HOME/.local/share/jarvis/models" "$HOME/.local/share/jarvis/memory"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

echo "JARVIS installed successfully."
EOF

cat > "$DEB_BUILD/DEBIAN/prerm" << 'EOF'
#!/bin/bash
set -e

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi

echo "JARVIS removed. User data preserved in:"
echo "  $HOME/.config/jarvis"
echo "  $HOME/.local/share/jarvis"
EOF

chmod 755 "$DEB_BUILD/DEBIAN/postinst" "$DEB_BUILD/DEBIAN/prerm"

echo "[build-deb] Step 11: Building .deb package"
mkdir -p "$OUTPUT_DIR"
dpkg-deb --build "$DEB_BUILD" "$OUTPUT_DIR/Jarvis-1.0.0.deb"

echo "[build-deb] Done! Package: $OUTPUT_DIR/Jarvis-1.0.0.deb"
ls -lh "$OUTPUT_DIR/Jarvis-1.0.0.deb"
