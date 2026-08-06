from fastapi import APIRouter, HTTPException, Request

from routes.state import stt

router = APIRouter(prefix="/api/stt", tags=["stt"])


@router.post("/transcribe")
async def transcribe_audio(request: Request):
    """Transcribe audio to text using offline speech recognition.

    Expected JSON body:
    - `audio_base64`: base64-encoded WAV (PCM16, mono, 16kHz) audio

    Returns `{"text": "..."}`.
    """
    body = await request.json()
    audio_base64 = body.get("audio_base64") or body.get("audio")
    if not audio_base64:
        raise HTTPException(status_code=400, detail="audio_base64 is required")

    if not stt.available:
        detail = "Speech-to-text model not installed. Run scripts/download-vosk-model.sh"
        if not stt.has_cloud_fallback:
            detail += ", or set OPENAI_API_KEY for cloud fallback"
        raise HTTPException(status_code=503, detail=detail)

    try:
        text = stt.transcribe_base64(audio_base64)
        return {"text": text}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Speech-to-text failed: {e}") from e


@router.get("/status")
async def stt_status():
    """Check whether offline speech recognition is ready."""
    return {"available": stt.available, "cloud_fallback": stt.has_cloud_fallback}
