"""Project Manager — project detection, tech stack analysis, and recent file tracking."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProjectManager:
    """Detects projects and analyzes tech stacks."""

    TECH_SIGNATURES = {
        "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
        "node": ["package.json"],
        "rust": ["Cargo.toml"],
        "go": ["go.mod"],
        "java": ["pom.xml", "build.gradle"],
        "csharp": ["*.csproj", "*.sln"],
        "ruby": ["Gemfile"],
        "php": ["composer.json"],
        "elixir": ["mix.exs"],
        "haskell": ["package.yaml", "stack.yaml"],
    }

    def __init__(self, memory_manager: Any):
        self.memory = memory_manager

    async def detect_projects(self, scan_paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Detect projects under the given paths."""
        paths = scan_paths or [os.path.expanduser("~")]
        found: list[dict[str, Any]] = []
        seen: set[str] = set()

        for base in paths:
            if not os.path.isdir(base):
                continue
            for root, dirs, files in os.walk(base):
                if ".git" in dirs:
                    dirs.remove(".git")
                project_root = self._find_project_root(Path(root), files)
                if project_root and project_root not in seen:
                    seen.add(project_root)
                    found.append(await self.analyze_project(str(project_root)))
                if len(found) >= 20:
                    break
            if len(found) >= 20:
                break

        return found

    def _find_project_root(self, path: Path, files: list[str]) -> Path | None:
        for marker in [
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "setup.py",
            "requirements.txt",
        ]:
            if marker in files:
                return path
        return None

    async def analyze_project(self, project_path: str) -> dict[str, Any]:
        """Analyze a single project."""
        path = Path(project_path)
        if not path.exists():
            return {"error": "Path does not exist"}

        tech_stack = self._detect_tech_stack(path)
        git_info = self._get_git_info(path)
        recent_files = self._get_recent_files(path)

        return {
            "id": str(path.resolve()),
            "name": path.name,
            "path": str(path.resolve()),
            "tech_stack": tech_stack,
            "git": git_info,
            "recent_files": recent_files,
            "analyzed_at": datetime.now().isoformat(),
        }

    def _detect_tech_stack(self, path: Path) -> list[str]:
        detected = []
        for tech, markers in self.TECH_SIGNATURES.items():
            for marker in markers:
                if list(path.glob(marker)):
                    detected.append(tech)
                    break
        return detected or ["unknown"]

    def _get_git_info(self, path: Path) -> dict[str, Any]:
        try:
            branch = self._run_git(path, ["rev-parse", "--abbrev-ref", "HEAD"]) or ""
            status = self._run_git(path, ["status", "--short"]) or ""
            return {
                "branch": branch.strip(),
                "dirty": bool(status.strip()),
                "status": status.strip(),
            }
        except Exception:
            return {"branch": "", "dirty": False, "status": ""}

    def _get_recent_files(self, path: Path, limit: int = 10) -> list[str]:
        try:
            output = self._run_git(path, ["ls-files", "-m", "-t"]) or ""
            files = [line.split("\t")[-1] for line in output.strip().split("\n") if line]
            return files[:limit]
        except Exception:
            return []

    def _run_git(self, path: Path, args: list[str]) -> str:
        try:
            import subprocess

            result = subprocess.run(
                ["git"] + args,
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout
        except Exception:
            return ""
