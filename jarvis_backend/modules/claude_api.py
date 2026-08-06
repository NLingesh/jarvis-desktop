from __future__ import annotations

import json
import os
from collections.abc import Callable

import anthropic

from modules.llm_provider import JARVIS_SYSTEM_PROMPT


class ClaudeAPI:
    """Anthropic Claude provider using the async SDK.

    Never blocks the event loop: all network I/O runs through
    ``anthropic.AsyncAnthropic``.
    """

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-haiku-20240307")

    async def get_response(
        self,
        user_message: str,
        conversation_history: list[dict],
        context: dict | None = None,
        memory_results: list[dict] | None = None,
    ) -> str:
        """Get response from Claude with context awareness"""
        system_prompt = self._build_system_prompt(context, memory_results)
        messages = conversation_history + [{"role": "user", "content": user_message}]

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=500,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text
        except Exception as e:
            return f"I encountered an error: {str(e)}"

    def _build_system_prompt(
        self, context: dict | None, memory_results: list[dict] | None = None
    ) -> str:
        """Build dynamic system prompt based on available context."""
        base_prompt = JARVIS_SYSTEM_PROMPT

        if not context:
            return base_prompt

        context_parts = [base_prompt]

        if context.get("calendar"):
            context_parts.append(f"\n\nUpcoming events: {json.dumps(context['calendar'])}")
        if context.get("emails"):
            context_parts.append(f"\n\nRecent emails: {json.dumps(context['emails'][:3])}")
        if context.get("web_results"):
            context_parts.append(f"\n\nWeb results: {json.dumps(context['web_results'][:3])}")
        if context.get("system_info"):
            context_parts.append(f"\n\nSystem status: {json.dumps(context['system_info'])}")
        if context.get("documents"):
            context_parts.append(f"\n\nDocuments: {json.dumps(context['documents'])}")
        if context.get("notes"):
            context_parts.append(f"\n\nNotes: {json.dumps(context['notes'])}")

        if memory_results:
            memory_text = "\n".join(
                f"- [{r.get('role', 'user')}] {r.get('content', '')}" for r in memory_results[:5]
            )
            context_parts.append(f"\n\nRelevant past conversations:\n{memory_text}")

        return "\n".join(context_parts)

    async def stream_response(
        self,
        user_message: str,
        conversation_history: list[dict],
        context: dict | None = None,
        memory_results: list[dict] | None = None,
        on_text_chunk: Callable[[str], None] | None = None,
    ):
        """Stream response from Claude for real-time feedback."""
        system_prompt = self._build_system_prompt(context, memory_results)
        messages = conversation_history + [{"role": "user", "content": user_message}]

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=500,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    if on_text_chunk:
                        on_text_chunk(text)
                    yield text
