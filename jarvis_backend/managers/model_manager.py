"""Model Manager — Ollama integration, model discovery, download, selection.

Provides a unified interface for managing local and cloud AI models.
"""

import json
import logging
import os
from collections.abc import AsyncGenerator

import httpx

logger = logging.getLogger(__name__)


class ModelManager:
    """Manages AI models across providers (Ollama, OpenAI, Anthropic, etc.)."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        openai_api_key: str | None = None,
        anthropic_api_key: str | None = None,
        mistral_api_key: str | None = None,
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.anthropic_api_key = anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self.mistral_api_key = mistral_api_key or os.getenv("MISTRAL_API_KEY")

    def diagnostics(self) -> dict:
        return {
            "ollama_url": self.ollama_url,
            "ollama_available": self._check_ollama(),
            "openai_configured": bool(self.openai_api_key),
            "anthropic_configured": bool(self.anthropic_api_key),
            "mistral_configured": bool(self.mistral_api_key),
        }

    def _check_ollama(self) -> bool:
        try:
            with httpx.Client(timeout=2.0) as client:
                r = client.get(f"{self.ollama_url}/api/tags")
                return r.status_code == 200
        except Exception:
            return False

    async def list_ollama_models(self) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self.ollama_url}/api/tags")
                r.raise_for_status()
                data = r.json()
                return data.get("models", [])
        except Exception as e:
            logger.error("Failed to list Ollama models: %s", e)
            return []

    async def pull_ollama_model(self, name: str) -> AsyncGenerator[str, None]:
        try:
            async with (
                httpx.AsyncClient(timeout=None) as client,
                client.stream(
                    "POST",
                    f"{self.ollama_url}/api/pull",
                    json={"name": name},
                ) as r,
            ):
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if line:
                        yield line
        except Exception as e:
            logger.error("Failed to pull Ollama model %s: %s", name, e)
            yield json.dumps({"error": str(e)})

    async def delete_ollama_model(self, name: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.delete(
                    f"{self.ollama_url}/api/delete",
                    json={"name": name},
                )
                return r.status_code == 200
        except Exception as e:
            logger.error("Failed to delete Ollama model %s: %s", name, e)
            return False

    async def get_ollama_model_info(self, name: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(
                    f"{self.ollama_url}/api/show",
                    json={"name": name},
                )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.error("Failed to get Ollama model info %s: %s", name, e)
            return None

    async def get_storage_usage(self) -> dict:
        try:
            models = await self.list_ollama_models()
            total_size = sum(m.get("size", 0) for m in models)
            return {
                "ollama": {
                    "model_count": len(models),
                    "total_size_bytes": total_size,
                    "total_size_gb": round(total_size / (1024**3), 2),
                    "models": [
                        {
                            "name": m.get("name", ""),
                            "size_bytes": m.get("size", 0),
                            "size_gb": round(m.get("size", 0) / (1024**3), 2),
                        }
                        for m in models
                    ],
                }
            }
        except Exception as e:
            logger.error("Failed to get storage usage: %s", e)
            return {"ollama": {"error": str(e)}}
