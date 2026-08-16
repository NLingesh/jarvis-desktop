"""Centralized resource limits for inbound WebSocket/audio payloads.

The WS voice handler bounds per-chunk and per-utterance decoded PCM sizes so a
single connection cannot exhaust memory by streaming audio forever.  Kept in a
tiny module (rather than inline in main.py) so the guards are unit-testable.
"""

MAX_AUDIO_CHUNK_BYTES = 8 * 1024 * 1024  # per decoded chunk (~4 min of 16 kHz PCM)
MAX_UTTERANCE_BYTES = 16 * 1024 * 1024   # per utterance

MAX_OCR_IMAGE_BYTES = 8 * 1024 * 1024  # decoded image size accepted by /ocr
MAX_OCR_B64_CHARS = ((MAX_OCR_IMAGE_BYTES + 2) // 3) * 4 + 4  # base64 upper bound
MAX_CREATE_FILE_BYTES = 1_048_576  # content size accepted by /files/create


def audio_chunk_allowed(pcm_len: int, accumulated: int) -> bool:
    """Whether another decoded PCM chunk may be added to the current utterance."""
    return pcm_len <= MAX_AUDIO_CHUNK_BYTES and accumulated + pcm_len <= MAX_UTTERANCE_BYTES


def legacy_audio_blob_allowed(base64_len: int) -> bool:
    """Whether a base64 audio blob (legacy single-shot path) may be accepted."""
    return base64_len <= (MAX_UTTERANCE_BYTES * 4 // 3) + 8