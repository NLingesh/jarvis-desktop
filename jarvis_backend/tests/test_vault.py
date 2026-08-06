"""Tests for the Markdown vault (store, codec, templates, manager)."""

import asyncio

from modules.vault.codec import extract_links, extract_tags, parse, serialize
from modules.vault.manager import VaultManager
from modules.vault.store import VaultStore
from modules.vault.templates import slugify


def run(coro):
    return asyncio.run(coro)


def make_manager(tmp_path):
    manager = VaultManager(str(tmp_path / "vault"))
    run(manager.initialize())
    return manager


# --- VaultStore -------------------------------------------------------------


def test_store_rejects_path_escape(tmp_path):
    store = VaultStore(str(tmp_path / "vault"))
    try:
        store.resolve("../escape")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_store_write_read_is_round_trip(tmp_path):
    store = VaultStore(str(tmp_path / "vault"))
    store.write("Knowledge/FastAPI.md", "hello")
    assert store.read("Knowledge/FastAPI.md") == "hello"
    assert store.list_files() == ["Knowledge/FastAPI.md"]


def test_store_init_folders(tmp_path):
    store = VaultStore(str(tmp_path / "vault"))
    store.init_folders()
    for folder in ("Daily Notes", "Projects", "Knowledge", "Archive"):
        assert store.exists(folder)


def test_store_move_creates_folders(tmp_path):
    store = VaultStore(str(tmp_path / "vault"))
    store.write("Ideas/one.md", "x")
    store.move("Ideas/one.md", "Knowledge/two.md")
    assert not store.exists("Ideas/one.md")
    assert store.read("Knowledge/two.md") == "x"


# --- codec ------------------------------------------------------------------


def test_parse_missing_frontmatter(tmp_path):
    frontmatter, body = parse("just a body")
    assert frontmatter == {}
    assert body == "just a body"


def test_parse_and_serialize_round_trip():
    frontmatter, body = parse(serialize({"title": "T", "tags": ["a"]}, "Body text"))
    assert frontmatter == {"title": "T", "tags": ["a"]}
    assert body == "Body text"


def test_extract_tags_merges_frontmatter_and_inline():
    content = serialize({"tags": ["work", "ai"]}, "A #quick note about #AI stuff")
    assert extract_tags(content) == ["work", "ai", "quick"]


def test_extract_links():
    content = "See [[FastAPI]] and [[Web Search|search tool]] plus [[Daily Notes/2026-08-06]]"
    assert extract_links(content) == ["FastAPI", "Web Search", "Daily Notes/2026-08-06"]


def test_slugify_sanitizes():
    assert slugify("My Great Note") == "My Great Note"
    assert slugify("a/b:c*d") == "abcd"
    assert slugify("   ") == "untitled"


# --- VaultManager -----------------------------------------------------------


def test_create_and_get_note(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("Weekly Review", content="Discuss the sprint", tags=["Work"]))
    assert note["title"] == "Weekly Review"
    assert note["tags"] == ["work"]
    assert note["type"] == "knowledge"
    assert note["id"]
    assert note["folder"] == ""

    fetched = run(manager.get_note(note["path"]))
    assert fetched["title"] == note["title"]
    assert fetched["body"] == "Discuss the sprint"


def test_create_note_in_folder(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("API Design", content="Spec", folder="Projects/Portal"))
    assert note["folder"] == "Projects/Portal"
    assert manager.store.exists(note["path"])


def test_create_duplicate_raises(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("Same", content="a"))
    try:
        run(manager.create_note("Same", content="b"))
        raise AssertionError("expected FileExistsError")
    except FileExistsError:
        pass


def test_update_note(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("Title", content="old body", tags=["a"]))
    updated = run(manager.update_note(note["path"], content="new body", tags=["b"], favorite=True))
    assert updated["body"] == "new body"
    assert updated["tags"] == ["b"]
    assert updated["favorite"] is True
    assert updated["modified"] >= note["modified"]


def test_append_note(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("Log", content="first line"))
    updated = run(manager.append_note(note["path"], "second line"))
    assert "second line" in updated["body"]


def test_rename_updates_title_and_aliases(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("Old Name", content="body"))
    renamed = run(manager.rename_note(note["path"], "New Name"))
    assert renamed["title"] == "New Name"
    assert "Old Name" in renamed["aliases"]
    assert not manager.store.exists(note["path"])
    assert manager.store.exists(renamed["path"])


def test_rename_rewrites_wikilinks_to_target(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("Source", content="Mention [[Target]] in passing"))
    target = run(manager.create_note("Target", content="body"))
    run(manager.rename_note(target["path"], "Target Two"))
    source = run(manager.get_note("Source.md"))
    assert "[[Target Two]]" in source["body"]
    assert "[[Target]]" not in source["body"]


def test_move_and_archive_and_delete(tmp_path):
    manager = make_manager(tmp_path)
    note = run(manager.create_note("Wander", content="body", folder="Knowledge"))
    moved = run(manager.move_note(note["path"], "Projects"))
    assert moved["folder"] == "Projects"
    archived = run(manager.archive_note(moved["path"]))
    assert archived["folder"] == "Archive"
    run(manager.delete_note(archived["path"]))
    try:
        run(manager.get_note(archived["path"]))
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass


def test_list_notes_filters(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("Alpha", content="x", tags=["work"]))
    run(manager.create_note("Beta", content="y", folder="Knowledge"))
    assert {n["title"] for n in run(manager.list_notes())} == {"Alpha", "Beta"}
    assert {n["title"] for n in run(manager.list_notes(folder="Knowledge"))} == {"Beta"}
    assert {n["title"] for n in run(manager.list_notes(tag="work"))} == {"Alpha"}


def test_list_tags_counts(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("One", content="x", tags=["work", "ai"]))
    run(manager.create_note("Two", content="y", tags=["work"]))
    tags = {t["tag"]: t["count"] for t in run(manager.list_tags())}
    assert tags["work"] == 2
    assert tags["ai"] == 1


def test_search_matches_content_and_tags(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("Project kickoff", content="Discuss the deadline", tags=["work"]))
    run(manager.create_note("Groceries", content="Apples and bread"))

    by_content = run(manager.search("deadline"))
    assert {n["title"] for n in by_content} == {"Project kickoff"}

    by_tag = run(manager.search(tag="work"))
    assert {n["title"] for n in by_tag} == {"Project kickoff"}

    assert run(manager.search("zebra")) == []


def test_search_scan_fallback_when_index_empty(tmp_path):
    manager = VaultManager(str(tmp_path / "vault"))
    run(manager.initialize())
    run(manager.create_note("Fresh", content="unique phrase here"))
    hits = run(manager.search("unique phrase"))
    assert {n["title"] for n in hits} == {"Fresh"}


def test_scan_search_backend_falls_through_to_scan(tmp_path):
    from modules.vault.search import ScanSearchBackend

    manager = VaultManager(str(tmp_path / "vault"), search_backend=ScanSearchBackend())
    run(manager.initialize())
    run(manager.create_note("Scan Note", content="findable via scan only"))
    hits = run(manager.search("scan only"))
    assert {n["title"] for n in hits} == {"Scan Note"}


def test_get_links_and_backlinks(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("A", content="links to [[B]]"))
    b = run(manager.create_note("B", content="body"))
    assert run(manager.get_links("A.md")) == ["B"]
    backlinks = run(manager.get_backlinks(b["path"]))
    assert [x["path"] for x in backlinks] == ["A.md"]


def test_stats(tmp_path):
    manager = make_manager(tmp_path)
    run(manager.create_note("Idea A", content="x", note_type="idea", favorite=True))
    run(manager.create_note("Task B", content="y", note_type="task"))
    stats = run(manager.stats())
    assert stats["total"] == 2
    assert stats["by_type"] == {"idea": 1, "task": 1}
    assert stats["favorites"] == 1


def test_events_fire(tmp_path):
    manager = make_manager(tmp_path)
    events = []
    manager.on("created", lambda rel_path, meta: events.append(("created", rel_path)))
    manager.on("deleted", lambda rel_path: events.append(("deleted", rel_path)))
    note = run(manager.create_note("Eventful", content="x"))
    run(manager.delete_note(note["path"]))
    assert events == [("created", note["path"]), ("deleted", note["path"])]
