"""Tests for DocumentsModule — safe file CRUD inside a documents root."""

import pytest

from modules.documents_module import DocumentsModule


def make_module(tmp_path):
    root = str(tmp_path / "docs")
    return DocumentsModule(root=root)


def test_create_and_read_document(tmp_path):
    module = make_module(tmp_path)
    result = module.create_document("hello.txt", "Hello world")
    assert result.success is True
    assert result.filename == "hello.txt"

    read = module.read_document("hello.txt")
    assert read.success is True
    assert read.content.startswith("Hello world")


def test_create_document_without_extension_rejected(tmp_path):
    module = make_module(tmp_path)
    result = module.create_document("readme", "content")
    assert result.success is False
    assert "Unsupported" in result.error


def test_create_document_no_overwrite_by_default(tmp_path):
    module = make_module(tmp_path)
    module.create_document("a.txt", "first")
    result = module.create_document("a.txt", "second")
    assert result.success is False
    assert "already exists" in (result.error or "").lower()
    assert module.read_document("a.txt").content.startswith("first")


def test_create_document_overwrite(tmp_path):
    module = make_module(tmp_path)
    module.create_document("a.txt", "first")
    result = module.create_document("a.txt", "second", overwrite=True)
    assert result.success is True
    assert module.read_document("a.txt").content.startswith("second")


def test_read_missing_document(tmp_path):
    module = make_module(tmp_path)
    result = module.read_document("nope.txt")
    assert result.success is False
    assert result.error == "File not found"


def test_unsupported_extension_rejected(tmp_path):
    module = make_module(tmp_path)
    result = module.create_document("evil.sh", "rm -rf /")
    assert result.success is False


def test_append_document(tmp_path):
    module = make_module(tmp_path)
    module.create_document("log.txt", "line1\n")
    result = module.append_document("log.txt", "line2\n")
    assert result.success is True
    content = module.read_document("log.txt").content
    assert "line1" in content and "line2" in content


def test_append_missing_document(tmp_path):
    module = make_module(tmp_path)
    result = module.append_document("ghost.txt", "data")
    assert result.success is False


def test_replace_document(tmp_path):
    module = make_module(tmp_path)
    module.create_document("note.txt", "old")
    result = module.replace_document("note.txt", "brand new")
    assert result.success is True
    assert module.read_document("note.txt").content.startswith("brand new")


def test_delete_document(tmp_path):
    module = make_module(tmp_path)
    module.create_document("temp.txt", "x")
    assert module.delete_document("temp.txt").success is True
    assert module.delete_document("temp.txt").success is False


def test_list_documents_with_and_without_query(tmp_path):
    module = make_module(tmp_path)
    module.create_document("alpha.txt", "1")
    module.create_document("beta.md", "2")
    assert module.list_documents() == ["alpha.txt", "beta.md"]
    assert module.list_documents("alpha") == ["alpha.txt"]


def test_path_traversal_blocked(tmp_path):
    module = make_module(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        module.read_document("../secret.txt")


def test_token_budget_truncation(monkeypatch, tmp_path):
    import modules.documents_module as documents_module

    module = make_module(tmp_path)
    monkeypatch.setattr(documents_module, "MAX_READ_CHARS", 10)
    text, truncated = module._token_budget_truncate("x" * 100)
    assert truncated is True
    assert len(text) == 10
    short, short_truncated = module._token_budget_truncate("hi")
    assert short_truncated is False
