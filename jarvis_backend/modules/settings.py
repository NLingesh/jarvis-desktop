"""Settings management for JARVIS backend.

API keys and mail credentials are stored in the OS keychain via keytar
(electron/main.js). When the backend process starts, the Electron main
process injects these as environment variables. This module provides
helpers to read, mask, and persist settings from the environment / .env.
"""

import asyncio
import logging
import os
import re
import signal

logger = logging.getLogger(__name__)

KEY_NAMES = [
    "MISTRAL_API_KEY",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "NVIDIA_API_KEY",
    "EMAIL_IMAP_SERVER",
    "EMAIL_IMAP_PORT",
    "EMAIL_SMTP_SERVER",
    "EMAIL_SMTP_PORT",
]


def _mask_secret(value: str) -> str:
    """Return a masked preview like 'sk-ant-****1234', never the full value."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:7] + "****" + value[-4:]


def get_masked_keys() -> dict[str, str]:
    """Return masked previews of all managed keys from the environment."""
    return {name: _mask_secret(os.getenv(name)) for name in KEY_NAMES}


def _write_env_keys(env_path: str, keys: dict[str, str]) -> None:
    """Update key=value entries in a .env file, preserving comments and other keys."""
    new_keys = {k: v.strip() for k, v in keys.items() if v and v.strip()}
    if not new_keys:
        return
    env_path = os.path.abspath(env_path)
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    try:
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []
    keys_present: set = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", stripped)
        if match and match.group(1) in new_keys:
            key = match.group(1)
            lines[i] = f"{key}={new_keys[key]}\n"
            keys_present.add(key)
    missing = [k for k in new_keys if k not in keys_present]
    if missing:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        for key in missing:
            lines.append(f"{key}={new_keys[key]}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


async def restart_backend_after(seconds: float = 1.5) -> None:
    """Gracefully terminate this process so the Electron host respawns it."""
    await asyncio.sleep(seconds)
    logger.info("Restarting backend to apply updated settings...")
    os.kill(os.getpid(), signal.SIGTERM)
