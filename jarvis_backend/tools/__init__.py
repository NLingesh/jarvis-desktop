import abc
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ToolResult:
    def __init__(self, success: bool, data: Any = None, error: str | None = None, requires_confirmation: bool = False, confirmation_prompt: str | None = None):
        self.success = success
        self.data = data
        self.error = error
        self.requires_confirmation = requires_confirmation
        self.confirmation_prompt = confirmation_prompt

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
        }


class BaseTool(abc.ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abc.abstractmethod
    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        ...

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._confirmation_handlers: dict[str, Callable] = {}
        self.pending_confirmations: dict[str, dict] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def register_confirmation_handler(self, session_id: str, payload: dict) -> None:
        self._confirmation_handlers[session_id] = payload

    def get_tool(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    async def execute_tool(self, name: str, arguments: dict, context: dict | None = None) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(False, error=f"Unknown tool: {name}")
        try:
            return await tool.execute(arguments, context=context)
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return ToolResult(False, error=str(exc))

    async def dispatch(self, tool_call: dict, context: dict | None = None) -> ToolResult:
        name = tool_call.get("name") or tool_call.get("tool")
        arguments = tool_call.get("arguments") or tool_call.get("parameters") or {}
        if not name:
            return ToolResult(False, error="Missing tool name")
        return await self.execute_tool(name, arguments, context=context)
