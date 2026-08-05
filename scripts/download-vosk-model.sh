#!/bin/bash
# Downloads the offline Vosk speech-recognition model used by JARVIS.
# The model enables fully offline voice capture (no API keys required).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/../jarvis_backend"
MODELS_DIR="$BACKEND_DIR/models"

MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_DIR="$MODELS_DIR/vosk-model-small-en-us-0.15"

if [ -d "$MODEL_DIR" ] && [ -n "$(ls -A "$MODEL_DIR")" ]; then
    echo "[download-vosk-model] Model already present at $MODEL_DIR"
    exit 0
fi

echo "[download-vosk-model] Downloading Vosk model (~40MB) to $MODELS_DIR"
mkdir -p "$MODELS_DIR"

if command -v curl &> /dev/null; then
    curl -L -o "$MODELS_DIR/vosk-model-small.zip" "$MODEL_URL"
elif command -v wget &> /dev/null; then
    wget -O "$MODELS_DIR/vosk-model-small.zip" "$MODEL_URL"
else
    echo "[download-vosk-model] ERROR: curl or wget is required" >&2
    exit 1
fi

echo "[download-vosk-model] Extracting..."
cd "$MODELS_DIR"
unzip -q -o vosk-model-small.zip
rm -f vosk-model-small.zip

echo "[download-vosk-model] Done. Model installed at $MODEL_DIR"
