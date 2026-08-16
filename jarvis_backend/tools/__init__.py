import abc
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TOOL_TIMEOUT = 30.0
DEFAULT_MAX_OUTPUT = 64 * 1024


class ToolError(Exception):
    """Raised for user-input / permission / capability errors in a tool.

    Distinguished from arbitrary exceptions so the caller can produce a typed
    client-safe error instead of leaking a raw traceback string.
    """

    def __init__(self, message: str, kind: str = "internal"):
        super().__init__(message)
        self.kind = kind  # user_input | permission | capability | timeout | internal


class ToolResult:
    def __init__(
        self,
        success: bool,
        data: Any = None,
        error: str | None = None,
        requires_confirmation: bool = False,
        confirmation_prompt: str | None = None,
    ):
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
    # Capability metadata (used by the centralized capability policy).
    capability: str = "general"
    risk_level: str = "read_only"  # read_only | reversible | destructive
    timeout: float = DEFAULT_TOOL_TIMEOUT
    max_output_bytes: int = DEFAULT_MAX_OUTPUT

    @abc.abstractmethod
    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        ...

    def validate_arguments(self, arguments: dict) -> str | None:
        """Validate arguments against the JSON schema.  Returns an error string or None."""
        args = arguments or {}
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])

        for field in required:
            if field not in args or args.get(field) in (None, ""):
                return f"Missing required argument: {field}"

        for field, value in args.items():
            if field not in props:
                return f"Unknown argument: {field}"
            prop = props.get(field, {})
            expected = prop.get("type")
            if expected == "string" and not isinstance(value, str):
                return f"Argument '{field}' must be a string"
            if expected == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    return f"Argument '{field}' must be an integer"
            if expected == "boolean" and not isinstance(value, bool):
                return f"Argument '{field}' must be a boolean"
            if expected in ("array", "object") and not isinstance(value, (list, dict)):
                return f"Argument '{field}' must be {expected}"
        return None

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "risk_level": self.risk_level,
            "capability": self.capability,
        }


def truncate_output(result: ToolResult, limit: int = DEFAULT_MAX_OUTPUT) -> ToolResult:
    """Cap tool output size so unbounded tool data never reaches the model."""
    if not isinstance(result.data, (dict, list, str)):
        return result
    if isinstance(result.data, str) and len(result.data) <= limit:
        return result
    try:
        if isinstance(result.data, (dict, list)):
            text = json.dumps(result.data, ensure_ascii=False, default=str)
        else:
            text = result.data
        if len(text) <= limit:
            return result
        truncated = text[:limit]
        if isinstance(result.data, dict):
            result.data = {"truncated": True, "preview": truncated}
        elif isinstance(result.data, list):
            result.data = {"truncated": True, "count": len(result.data), "preview": truncated}
        else:
            result.data = truncated
    except Exception:
        result.data = {"truncated": True}
    return result


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
        error = tool.validate_arguments(arguments or {})
        if error:
            return ToolResult(False, error=error)
        try:
            result = await tool.execute(arguments or {}, context=context)
            return truncate_output(result, tool.max_output_bytes)
        except ToolError as exc:
            return ToolResult(False, error=exc.message)
        except TimeoutError:
            return ToolResult(False, error="Tool timed out")
        except Exception as exc:
            logger.error("Tool %s failed: %s", name, exc)
            return ToolResult(False, error=f"Internal error in tool '{name}'")

    async def dispatch(self, tool_call: dict, context: dict | None = None) -> ToolResult:
        name = tool_call.get("name") or tool_call.get("tool")
        arguments = tool_call.get("arguments") or tool_call.get("parameters") or {}
        if not name:
            return ToolResult(False, error="Missing tool name")
        return await self.execute_tool(name, arguments, context=context)
