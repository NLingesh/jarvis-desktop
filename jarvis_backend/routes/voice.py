from fastapi import APIRouter, HTTPException

from managers.native_audio import list_input_devices, resolve_device
from routes.state import llm, stt_manager, tts_manager, voice_manager

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/config")
async def get_voice_config():
    """Return current voice pipeline configuration."""
    return {
        "stt": stt_manager.diagnostics(),
        "tts": tts_manager.diagnostics(),
        "llm_provider": getattr(llm, "provider", "unknown"),
        "llm_model": getattr(llm, "model", "unknown"),
        "voice": voice_manager.diagnostics(),
    }


@router.post("/config")
async def update_voice_config(request: dict):
    """Update voice pipeline configuration.

    Accepted keys:
    - stt_model: Faster Whisper model name
    - stt_device: cpu / cuda
    - tts_voice: TTS voice identifier
    - llm_provider: mistral / anthropic / ollama
    - llm_model: model name
    """
    # In a real implementation, this would update environment variables
    # or a settings store and restart affected managers.
    # For now, we validate and acknowledge.
    allowed_keys = {"stt_model", "stt_device", "tts_voice", "llm_provider", "llm_model"}
    unknown = set(request.keys()) - allowed_keys
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown config keys: {unknown}")

    return {"status": "accepted", "config": request}


@router.get("/devices")
async def get_devices():
    """Return available input devices (microphones) detected by PortAudio."""
    devices = list_input_devices()
    if not devices:
        raise HTTPException(status_code=503, detail="No input device available")
    return {
        "devices": devices,
        "default": resolve_device(None),
    }
