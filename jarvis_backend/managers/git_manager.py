"""Git Manager — Git operations, status, diff, commit, branch, PR creation."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GitManager:
    """Git operations for project management."""

    def __init__(self, memory_manager: Any):
        self.memory = memory_manager

    def _run(self, cwd: str, args: list[str]) -> str:
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout
        except Exception as e:
            logger.error("Git command failed: %s", e)
            return ""

    def get_status(self, project_path: str) -> dict[str, Any]:
        path = Path(project_path)
        if not path.exists():
            return {"error": "Path does not exist"}

        status_output = self._run(str(path), ["status", "--short", "--branch"])
        branch = ""
        changes = []

        for line in status_output.splitlines():
            if line.startswith("## "):
                branch = line[3:].split("...")[0].strip()
            else:
                changes.append(line)

        return {
            "project_path": str(path.resolve()),
            "branch": branch,
            "dirty": bool(changes),
            "changes": changes,
        }

    def get_diff(self, project_path: str, file_path: str | None = None) -> dict[str, Any]:
        path = Path(project_path)
        args = ["diff", "--no-ext-diff"]
        if file_path:
            args.append(file_path)
        diff = self._run(str(path), args)
        return {"project_path": str(path.resolve()), "file": file_path, "diff": diff}

    def get_log(self, project_path: str, limit: int = 20) -> dict[str, Any]:
        path = Path(project_path)
        args = ["log", f"--max-count={limit}", "--oneline", "--decorate"]
        log = self._run(str(path), args)
        return {"project_path": str(path.resolve()), "log": log}

    def create_commit(self, project_path: str, message: str) -> dict[str, Any]:
        path = Path(project_path)
        if not path.exists():
            return {"error": "Path does not exist"}

        self._run(str(path), ["add", "."])
        commit_output = self._run(str(path), ["commit", "-m", message])
        return {
            "project_path": str(path.resolve()),
            "message": message,
            "output": commit_output,
        }

    def create_branch(self, project_path: str, branch_name: str) -> dict[str, Any]:
        path = Path(project_path)
        output = self._run(str(path), ["checkout", "-b", branch_name])
        return {"project_path": str(path.resolve()), "branch": branch_name, "output": output}

    def get_branches(self, project_path: str) -> dict[str, Any]:
        path = Path(project_path)
        output = self._run(str(path), ["branch", "-a"])
        branches = [b.strip().lstrip("* ").strip() for b in output.splitlines() if b.strip()]
        return {"project_path": str(path.resolve()), "branches": branches}
