import asyncio
import contextlib
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

JARVIS_SYSTEM_PROMPT = (
    "You are JARVIS, a voice-first AI assistant running on the user's personal computer. "
    "You respond concisely and naturally, as if speaking out loud. "
    "Keep responses to 1-3 sentences unless the user explicitly asks for detail. "
    "Never use markdown, bullet points, code blocks, or special formatting characters. "
    "Never emit tool-call tags or JSON. Just plain spoken text. "
    "When given system information, calendar, emails, or documents in context, use them to answer accurately. "
    "If a requested action was completed (e.g. a note saved or file written), confirm it briefly. "
    "If an action could not be performed, say so plainly."
)


class LLMProvider:
    """Abstracts LLM provider implementation.

    Supports two modes:
    - 'anthropic' (delegates to existing ClaudeAPI when available)
    - 'mistral' (HTTP client using MISTRAL_API_KEY)
    """

    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "mistral").lower()
        self.model = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

        if self.provider == "anthropic":
            try:
                from .claude_api import ClaudeAPI

                self.client = ClaudeAPI()
            except Exception as e:
                logger.error("Failed to initialize Anthropic client: %s", e)
                self.client = None
        elif self.provider == "mistral":
            self.api_key = os.getenv("MISTRAL_API_KEY")
            self.api_url = os.getenv("MISTRAL_API_URL", "https://api.mistral.ai")
            if self.api_key and self.api_key.startswith("nvapi-"):
                if not os.getenv("MISTRAL_API_URL"):
                    # NVIDIA-hosted models use the NVIDIA inference API base
                    # (the code appends /v1/chat/completions to this base URL)
                    self.api_url = "https://integrate.api.nvidia.com"
                logger.info("Detected NVIDIA API key; using NVIDIA inference API")
            if not self.api_key:
                logger.warning("MISTRAL_API_KEY not set; LLM calls will fail until provided")
        else:
            logger.error("Unsupported LLM_PROVIDER: %s", self.provider)

    def _build_messages(self, user_message, conversation_history, context, memory_results=None):
        """Build the chat message list including persona, memory, and context."""
        messages = [{"role": "system", "content": JARVIS_SYSTEM_PROMPT}]

        if memory_results:
            try:
                memory_text = "\n".join(
                    f"- [{r.get('role', 'user')}] {r.get('content', '')}"
                    for r in memory_results[:5]
                )
                messages.append(
                    {"role": "system", "content": f"Relevant past conversations:\n{memory_text}"}
                )
            except Exception:
                pass

        if context:
            try:
                messages.append({"role": "system", "content": json.dumps(context)})
            except Exception:
                messages.append({"role": "system", "content": "Context provided"})

        for m in conversation_history[-20:]:
            role = m.get("role", "user")
            if role not in ("user", "assistant", "system"):
                role = "user"
            messages.append({"role": role, "content": m.get("content", "")})

        messages.append({"role": "user", "content": user_message})
        return messages

    async def get_response(
        self,
        user_message: str,
        conversation_history: list[dict],
        context: dict | None = None,
        memory_results: list[dict] | None = None,
    ) -> str:
        """Return a single text response from the configured LLM provider."""
        if self.provider == "anthropic":
            if not self.client:
                return "Anthropic client unavailable"
            return await self.client.get_response(
                user_message, conversation_history, context, memory_results
            )

        if self.provider == "mistral":
            # Use chat-style payloads where possible for better instruction-following
            headers = {"Content-Type": "application/json"}
            if getattr(self, "api_key", None):
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Build messages: persona/memory/context -> conversation -> user
            messages = self._build_messages(
                user_message, conversation_history, context, memory_results
            )

            payload_chat = {"model": self.model, "messages": messages}

            async with httpx.AsyncClient(timeout=30.0) as client:
                last_err = None
                # Try up to 3 attempts with backoff on transient failures
                for attempt in range(3):
                    try:
                        # Prefer chat completions endpoint if available
                        url_chat = f"{self.api_url.rstrip('/')}/v1/chat/completions"
                        r = await client.post(url_chat, headers=headers, json=payload_chat)
                        if r.status_code == 404:
                            # Some Mistral deployments use /v1/generate
                            url_gen = f"{self.api_url.rstrip('/')}/v1/generate"
                            # try generate with 'input' as a fallback
                            payload_gen = {"model": self.model, "input": user_message}
                            r = await client.post(url_gen, headers=headers, json=payload_gen)

                        if r.status_code >= 500:
                            last_err = (r.status_code, r.text)
                            await asyncio.sleep(1 + attempt * 2)
                            continue

                        if r.status_code != 200:
                            # Non-retriable client error — return a string to honor the str contract
                            logger.error("LLM request failed %s %s", r.status_code, r.text)
                            try:
                                err = r.json()
                            except Exception:
                                err = r.text
                            return f"LLM request failed (HTTP {r.status_code}): {err}"

                        data = r.json()

                        # common Mistral-style response: data['outputs'][0]['content'][0]['text']
                        try:
                            return data["outputs"][0]["content"][0]["text"]
                        except Exception:
                            pass

                        # openai-like chat completion: choices[0].message.content or choices[0].text
                        try:
                            return data["choices"][0]["message"]["content"]
                        except Exception:
                            pass

                        try:
                            return data["choices"][0]["text"]
                        except Exception:
                            pass

                        # If the response contains 'generated_text' fields
                        try:
                            return data.get("generated_text") or json.dumps(data)
                        except Exception:
                            return json.dumps(data)

                    except Exception as e:
                        last_err = e
                        await asyncio.sleep(1 + attempt * 2)

                # exhausted attempts
                logger.error("LLM request ultimately failed: %s", last_err)
                return f"LLM request failed: {last_err}"

        return "No provider configured"

    async def get_response_stream(
        self,
        user_message: str,
        conversation_history: list[dict],
        context: dict | None = None,
        memory_results: list[dict] | None = None,
    ):
        """Stream text chunks from the configured LLM provider as they arrive."""
        if self.provider == "anthropic" and getattr(self, "client", None):
            try:
                async for chunk in self.client.stream_response(
                    user_message, conversation_history, context, memory_results
                ):
                    if chunk:
                        yield chunk
                return
            except Exception:
                pass

        if self.provider == "mistral":
            messages = self._build_messages(
                user_message, conversation_history, context, memory_results
            )

            headers = {"Content-Type": "application/json"}
            if getattr(self, "api_key", None):
                headers["Authorization"] = f"Bearer {self.api_key}"

            payload = {"model": self.model, "messages": messages, "stream": True}

            url_options = [
                f"{self.api_url.rstrip('/')}/v1/chat/completions",
                f"{self.api_url.rstrip('/')}/v1/generate",
                f"{self.api_url.rstrip('/')}/v1/streams",
            ]

            async with httpx.AsyncClient(timeout=None) as client:
                for url in url_options:
                    try:
                        async with client.stream("POST", url, headers=headers, json=payload) as r:
                            if r.status_code >= 400:
                                continue

                            async for line in r.aiter_lines():
                                if not line:
                                    continue
                                if line.startswith("data: "):
                                    line = line[len("data: ") :]
                                line = line.strip()
                                if line in ("[DONE]", "DONE"):
                                    return
                                try:
                                    payload_obj = json.loads(line)
                                except Exception:
                                    yield line
                                    continue

                                text_chunk = None
                                with contextlib.suppress(Exception):
                                    text_chunk = payload_obj["outputs"][0]["content"][0]["text"]
                                if not text_chunk:
                                    with contextlib.suppress(Exception):
                                        text_chunk = payload_obj["choices"][0]["delta"]["content"]
                                if not text_chunk:
                                    with contextlib.suppress(Exception):
                                        text_chunk = payload_obj["choices"][0]["text"]
                                if not text_chunk:
                                    with contextlib.suppress(Exception):
                                        text_chunk = payload_obj["generated_text"]

                                if text_chunk:
                                    yield text_chunk

                        return
                    except Exception:
                        await asyncio.sleep(0.1)
                        continue

        # fallback: non-streaming
        full = await self.get_response(user_message, conversation_history, context, memory_results)
        yield full

    async def rerank(self, query: str, passages: list[str], model: str | None = None) -> dict:
        """Call a reranking endpoint (e.g., NVIDIA reranker) and return JSON.

        Expects environment variables for credentials:
        - `NVIDIA_API_KEY` (or set `NVIDIA_API_AUTH_HEADER` to full header value)
        - `NVIDIA_RERANK_URL` optionally to override the default endpoint
        """
        model = model or os.getenv("NVIDIA_RERANK_MODEL", "nv-rerank-qa-mistral-4b:1")
        invoke_url = os.getenv(
            "NVIDIA_RERANK_URL", "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"
        )

        # Build passages payload structure matching your example
        payload = {
            "model": model,
            "query": {"text": query},
            "passages": [{"text": p} for p in passages],
        }

        # Authorization: allow user to provide raw header or just a bearer token
        raw_auth = os.getenv("NVIDIA_API_AUTH_HEADER")
        api_key = os.getenv("NVIDIA_API_KEY")

        headers = {"Accept": "application/json"}
        if raw_auth:
            headers["Authorization"] = raw_auth
        elif api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        else:
            logger.warning("No NVIDIA API auth configured; request may fail")

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(invoke_url, headers=headers, json=payload)
            try:
                r.raise_for_status()
            except Exception:
                logger.error("NVIDIA rerank request failed: %s %s", r.status_code, r.text)
                return {"error": r.text, "status_code": r.status_code}

            try:
                return r.json()
            except Exception:
                return {"raw": r.text}
