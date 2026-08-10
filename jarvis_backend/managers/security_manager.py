"""Security Manager — encryption, privacy controls, and security posture."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class SecurityManager:
    """Encryption, privacy controls, and security posture for JARVIS."""

    def __init__(self, memory_manager: Any):
        self.memory = memory_manager
        self._key: bytes | None = None
        self._load_or_create_key()

    def _load_or_create_key(self) -> None:
        key_path = os.path.join(os.path.expanduser("~"), ".jarvis", "secret.key")
        try:
            os.makedirs(os.path.dirname(key_path), exist_ok=True)
            if os.path.exists(key_path):
                with open(key_path, "rb") as f:
                    self._key = f.read()
            else:
                self._key = Fernet.generate_key()
                with open(key_path, "wb") as f:
                    f.write(self._key)
        except Exception as e:
            logger.error("Failed to load/create encryption key: %s", e)
            self._key = Fernet.generate_key()

    def encrypt(self, plaintext: str) -> str:
        if self._key is None:
            return plaintext
        try:
            return base64.urlsafe_b64encode(
                Fernet(self._key).encrypt(plaintext.encode("utf-8"))
            ).decode("utf-8")
        except Exception as e:
            logger.error("Encryption failed: %s", e)
            return plaintext

    def decrypt(self, ciphertext: str) -> str:
        if self._key is None:
            return ciphertext
        try:
            return (
                Fernet(self._key)
                .decrypt(base64.urlsafe_b64decode(ciphertext.encode("utf-8")))
                .decode("utf-8")
            )
        except Exception as e:
            logger.error("Decryption failed: %s", e)
            return ciphertext

    async def get_security_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {
            "encryption_enabled": self._key is not None,
            "auth_enabled": False,
            "audit_logging": True,
            "permission_system": True,
            "last_check": datetime.now().isoformat(),
        }
        try:
            from routes.state import auth_service

            status["auth_enabled"] = auth_service.enabled
        except Exception:
            pass
        try:
            audit = await self.memory.get_audit_log(limit=1)
            status["recent_audit_entries"] = len(audit)
        except Exception:
            status["recent_audit_entries"] = 0
        return status

    async def export_user_data(self) -> dict[str, Any]:
        data = {
            "exported_at": datetime.now().isoformat(),
            "conversations": [],
            "tasks": [],
            "projects": [],
            "knowledge": [],
            "preferences": {},
            "audit_log": [],
        }
        try:
            data["tasks"] = await self.memory.list_tasks()
            data["projects"] = await self.memory.list_projects()
            data["knowledge"] = await self.memory.list_knowledge()
            data["preferences"] = await self.memory.list_preferences()
            data["audit_log"] = await self.memory.get_audit_log(limit=500)
        except Exception as e:
            logger.error("Data export failed: %s", e)
            data["error"] = str(e)
        return data

    async def delete_user_data(self, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            return {"error": "confirm=true is required to delete data"}
        try:
            await self.memory.clear(confirm=True)
            return {"deleted": True}
        except Exception as e:
            logger.error("Data deletion failed: %s", e)
            return {"error": str(e)}

    async def get_privacy_settings(self) -> dict[str, Any]:
        try:
            prefs = await self.memory.list_preferences()
            return {
                "data_collection": prefs.get("data_collection", "disabled"),
                "personalization": prefs.get("personalization", "enabled"),
                "audit_logging": prefs.get("audit_logging", "enabled"),
                "encryption": prefs.get("encryption", "enabled"),
            }
        except Exception:
            return {
                "data_collection": "disabled",
                "personalization": "enabled",
                "audit_logging": "enabled",
                "encryption": "enabled",
            }

    async def update_privacy_setting(self, key: str, value: str) -> dict[str, Any]:
        allowed = {"data_collection", "personalization", "audit_logging", "encryption"}
        if key not in allowed:
            return {"error": f"Unknown setting: {key}"}
        try:
            await self.memory.set_preference(key, value)
            return {"updated": key, "value": value}
        except Exception as e:
            logger.error("Failed to update privacy setting: %s", e)
            return {"error": str(e)}
