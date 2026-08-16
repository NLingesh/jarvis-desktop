"""Tests for path confinement, symlink protection, and secret redaction."""

import os
from pathlib import Path

from modules.path_policy import (
    approved_roots,
    is_sensitive_path,
    redact_content,
    resolve_within_roots,
)


def _find_root() -> str:
    for root in approved_roots():
        if os.path.isdir(root):
            return root
    raise AssertionError("No approved root exists")


def test_resolves_path_within_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    target = tmp_path / "docs" / "notes.txt"
    target.parent.mkdir(parents=True)
    target.write_text("hi")
    resolved = resolve_within_roots(str(target))
    assert str(resolved).startswith(str(tmp_path))


def test_rejects_path_outside_approved_roots(tmp_path, monkeypatch):
    outside = tmp_path / ".." / "not_approved"
    outside.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    try:
        resolve_within_roots(str(outside))
        raise AssertionError("Expected PermissionError for path outside roots")
    except PermissionError:
        pass


def test_rejects_symlink_escape(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Symlink inside the root pointing outside the root.
    victim = tmp_path / "victim"
    victim.mkdir()
    link = home / "escape"
    link.symlink_to(victim)
    try:
        resolve_within_roots(str(link / "secret.txt"))
        raise AssertionError("Expected PermissionError for symlink escape")
    except PermissionError:
        pass


def test_rejects_sensitive_paths():
    assert is_sensitive_path(Path("~/.ssh/id_rsa").expanduser())
    assert is_sensitive_path(Path("/home/user/.gnupg/private.key"))
    assert is_sensitive_path(Path("/home/user/.aws/credentials"))
    assert is_sensitive_path(Path("/home/user/.env"))
    assert is_sensitive_path(Path("/home/user/.env.local"))
    assert not is_sensitive_path(Path("/home/user/Documents/notes.txt"))


def test_redact_content_hides_secrets():
    text = "Key: sk-abcdef123456 secret AKIAIOSFODNN7EXAMPLE password=hunter2 token=xoxb-foo12345"
    redacted = redact_content(text)
    assert "sk-abcdef123456" not in redacted
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "hunter2" not in redacted
    assert "xoxb-foo12345" not in redacted
    assert "Key:" in redacted


def test_redact_content_preserves_plain_text():
    text = "The weather is nice and the file has 123 numbers."
    assert redact_content(text) == text