"""Code Manager — code search, explanation, and documentation lookup."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CodeManager:
    """Code search and explanation."""

    def __init__(self, memory_manager: Any, llm_provider: Any):
        self.memory = memory_manager
        self.llm = llm_provider

    def search_code(
        self, query: str, search_paths: list[str] | None = None, limit: int = 20
    ) -> dict[str, Any]:
        """Search code using ripgrep."""
        paths = search_paths or [os.path.expanduser("~")]
        results: list[dict[str, Any]] = []

        for base in paths:
            if not os.path.isdir(base):
                continue
            try:
                proc = subprocess.run(
                    ["rg", "--no-heading", "--line-number", "--max-count", str(limit), query, base],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                for line in proc.stdout.splitlines():
                    parts = line.split(":", 2)
                    if len(parts) >= 3:
                        results.append(
                            {
                                "file": parts[0],
                                "line": parts[1],
                                "content": parts[2],
                            }
                        )
            except FileNotFoundError:
                logger.warning("ripgrep not installed; falling back to basic search")
                results.extend(self._basic_search(base, query, limit))
            except Exception as e:
                logger.error("Code search failed: %s", e)
            if len(results) >= limit:
                break

        return {"query": query, "results": results[:limit]}

    def _basic_search(self, base: str, query: str, limit: int) -> list[dict[str, Any]]:
        results = []
        query_lower = query.lower()
        for root, dirs, files in os.walk(base):
            if ".git" in dirs:
                dirs.remove(".git")
            for fname in files:
                if not fname.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".md")):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    text = Path(fpath).read_text(errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if query_lower in line.lower():
                            results.append(
                                {
                                    "file": fpath,
                                    "line": str(i),
                                    "content": line.strip(),
                                }
                            )
                            if len(results) >= limit:
                                return results
                except Exception:
                    continue
        return results

    async def explain_code(
        self, file_path: str, line_start: int | None = None, line_end: int | None = None
    ) -> dict[str, Any]:
        """Explain code using LLM."""
        path = Path(file_path)
        if not path.exists():
            return {"error": "File not found"}

        try:
            lines = path.read_text(errors="ignore").splitlines()
            if line_start is not None and line_end is not None:
                snippet = "\n".join(lines[line_start - 1 : line_end])
            elif line_start is not None:
                snippet = lines[line_start - 1]
            else:
                snippet = "\n".join(lines[:200])

            if not self.llm:
                return {"error": "LLM not configured"}

            explanation = await self.llm.get_response(
                f"Explain the following code concisely:\n```\n{snippet}\n```",
                [],
                {"task": "explain_code"},
            )
            return {"file": str(path.resolve()), "snippet": snippet, "explanation": explanation}
        except Exception as e:
            logger.error("Code explanation failed: %s", e)
            return {"error": str(e)}
