"""Low-level filesystem access for the Markdown memory vault.

:class:`VaultStore` is the only object that touches vault files directly. It
guarantees:

* every path resolves inside the vault root (no path traversal),
* writes are atomic (temp file + ``os.replace``), so a crash or a concurrent
  editor never leaves a torn note,
* it is Markdown-agnostic — it deals in raw text and paths.

Higher-level notes (:class:`~modules.vault.manager.VaultManager`) go through
this class exclusively.
"""

import contextlib
import logging
import os
import shutil
import tempfile

logger = logging.getLogger(__name__)


class VaultStore:
    def __init__(self, root: str):
        self.root = os.path.realpath(os.path.abspath(os.path.expanduser(root)))

    def resolve(self, rel_path: str) -> str:
        """Resolve a vault-relative path, raising if it escapes the root."""
        rel_path = (rel_path or "").replace("\\", "/").lstrip("/")
        path = os.path.realpath(os.path.join(self.root, rel_path))
        if path != self.root and not path.startswith(self.root + os.sep):
            raise ValueError("Path escapes the vault root")
        return path

    def read(self, rel_path: str) -> str:
        with open(self.resolve(rel_path), encoding="utf-8") as f:
            return f.read()

    def write(self, rel_path: str, content: str) -> None:
        path = self.resolve(rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def append(self, rel_path: str, text: str) -> None:
        if not self.exists(rel_path):
            raise FileNotFoundError(rel_path)
        with open(self.resolve(rel_path), "a", encoding="utf-8") as f:
            f.write(text)

    def exists(self, rel_path: str) -> bool:
        return os.path.exists(self.resolve(rel_path))

    def list_files(self, folder: str | None = None) -> list[str]:
        """Return all ``.md`` relative paths under root (or a subfolder)."""
        base = self.resolve(folder or "")
        if not os.path.isdir(base):
            return []
        result: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if not name.lower().endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root)
                result.append(rel.replace(os.sep, "/"))
        return sorted(result)

    DEFAULT_FOLDERS = (
        "Daily Notes",
        "Conversations",
        "Projects",
        "Knowledge",
        "People",
        "Tasks",
        "Ideas",
        "Journal",
        "Notes",
        "Archive",
        "Attachments",
    )

    def init_folders(self) -> None:
        for folder in self.DEFAULT_FOLDERS:
            os.makedirs(self.resolve(folder), exist_ok=True)

    def list_folders(self) -> list[str]:
        folders: list[str] = []
        for dirpath, dirnames, _files in os.walk(self.root):
            for d in sorted(dirnames):
                if d.startswith("."):
                    continue
                full = os.path.join(dirpath, d)
                rel = os.path.relpath(full, self.root)
                folders.append(rel.replace(os.sep, "/"))
        return sorted(folders)

    def mkdir(self, rel_dir: str) -> None:
        os.makedirs(self.resolve(rel_dir), exist_ok=True)

    def move(self, src: str, dst: str) -> None:
        src_path, dst_path = self.resolve(src), self.resolve(dst)
        if os.path.exists(dst_path):
            raise FileExistsError(dst)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        os.replace(src_path, dst_path)

    def delete(self, rel_path: str) -> None:
        path = self.resolve(rel_path)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.remove(path)
