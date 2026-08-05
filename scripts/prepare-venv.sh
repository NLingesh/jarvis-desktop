#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
BACKEND_DIR="$PROJECT_ROOT/jarvis_backend"
SYSTEM_PYTHON="$(command -v python3)"

if [ -z "$SYSTEM_PYTHON" ]; then
    echo "[prepare-venv] ERROR: python3 not found in PATH"
    exit 1
fi

echo "[prepare-venv] Preparing self-contained Python virtual environment"

PY_VERSION=$("$SYSTEM_PYTHON" -c "import sys; print(f'python{sys.version_info.major}.{sys.version_info.minor}')")
SITE_PACKAGES="$VENV_DIR/lib/$PY_VERSION/site-packages"

TEMP_VENV="$PROJECT_ROOT/venv_portable"

if [ -d "$TEMP_VENV" ]; then
    rm -rf "$TEMP_VENV"
fi

echo "[prepare-venv] Creating virtual environment with --copies"
"$SYSTEM_PYTHON" -m venv --copies "$TEMP_VENV"

if [ -d "$SITE_PACKAGES" ]; then
    echo "[prepare-venv] Copying existing site-packages (preserving exact versions)"
    cp -r "$SITE_PACKAGES/"* "$TEMP_VENV/lib/$PY_VERSION/site-packages/" 2>/dev/null || true

    if [ -d "$VENV_DIR/bin" ]; then
        echo "[prepare-venv] Copying bin scripts from existing venv"
        EXISTING_BIN="$VENV_DIR/bin"
        NEW_BIN="$TEMP_VENV/bin"
        for f in "$EXISTING_BIN"/*; do
            if [ -f "$f" ] && [ ! -L "$f" ]; then
                basename=$(basename "$f")
                cp "$f" "$NEW_BIN/"
            fi
        done
    fi
else
    echo "[prepare-venv] No existing venv site-packages found; installing from requirements.txt"
    "$TEMP_VENV/bin/pip" install --upgrade pip
    "$TEMP_VENV/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

echo "[prepare-venv] Replacing old venv with portable version"
rm -rf "$VENV_DIR"
mv "$TEMP_VENV" "$VENV_DIR"

echo "[prepare-venv] Verifying installation"
"$VENV_DIR/bin/python" -c "import fastapi, uvicorn, httpx; print('Key dependencies verified OK')"
"$VENV_DIR/bin/python" -c "import modules; import main; print('Backend imports verified OK')" 2>/dev/null || echo "[prepare-venv] Note: main.py imports require cwd to be jarvis_backend/"

find "$VENV_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo "[prepare-venv] Precompiling bytecode for fast cold-start"
"$VENV_DIR/bin/python" -m compileall -q "$SITE_PACKAGES" 2>/dev/null || echo "[prepare-venv] compileall skipped (non-fatal)"

if [ ! -f "$BACKEND_DIR/.env" ] && [ -f "$BACKEND_DIR/.env.example" ]; then
    echo "[prepare-venv] Creating .env from .env.example"
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "[prepare-venv] NOTE: Edit $BACKEND_DIR/.env with your API keys"
fi

echo "[prepare-venv] Done. Virtual environment is self-contained with copied Python binary."
