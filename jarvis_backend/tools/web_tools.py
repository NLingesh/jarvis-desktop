import logging

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(BaseTool):
    risk_level = "read_only"
    capability = "web"
    name = "web_search"
    description = "Search the web using DuckDuckGo"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results", "default": 5},
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult:
        try:
            from modules.web_browse import WebBrowseModule
            module = WebBrowseModule()
            results = await module.search(arguments.get("query", ""))
            return ToolResult(True, data={"results": results[: int(arguments.get("max_results", 5))]})
        except Exception as exc:
            return ToolResult(False, error=str(exc))
