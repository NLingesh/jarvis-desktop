"""Tests for the desktop-open capability (folders, files, URLs, apps).

Covers the trusted tool path used by the conversational orchestrator:
* known-location resolution (Downloads/Desktop/Documents/Home/project),
* verified opening (only reports success when the desktop handler exited 0),
* URL scheme validation (no javascript:/file:),
* application allowlist + alias resolution,
* the no-shell guarantee for every opener,
* orchestrator tool-name aliases (so "open_browser" never becomes a false "can't do"),
* session-context capture of resolved paths for follow-ups.
"""

import asyncio
import time
from pathlib import Path

import pytest

from modules.capability import CapabilityPolicy
from modules.desktop_open import DesktopOpenError, desktop_open
from modules.orchestrator import Orchestrator
from modules.readme import find_readme
from modules.session_context import SessionContext
from tools import normalize_arguments
from tools.app_tools import (
    ALLOWED_APPS,
    LaunchApplicationTool,
    LaunchAppTool,
    resolve_launch_target,
)
from tools.desktop_tools import (
    ListRunningApplicationsTool,
    OpenUrlTool,
    ResolveKnownLocationTool,
)
from tools.file_tools import OpenFileTool, OpenFolderTool

run = asyncio.run


def _fake_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))


def _populate_home(tmp_path):
    for name in ("Downloads", "Desktop", "Documents", "Music", "Pictures", "Videos"):
        (tmp_path / name).mkdir(exist_ok=True)
    (tmp_path / "report.txt").write_text("hello", encoding="utf-8")


# ---------------------------------------------------------------- known locations


def test_resolve_known_location_exact(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    from modules.known_locations import resolve_known_location

    assert resolve_known_location("downloads") == tmp_path / "Downloads"
    assert resolve_known_location("Desktop") == tmp_path / "Desktop"
    assert resolve_known_location("home") == tmp_path


def test_resolve_known_location_fuzzy(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    from modules.known_locations import resolve_known_location

    assert resolve_known_location("my downloads folder") == tmp_path / "Downloads"
    assert resolve_known_location("the documents directory") == tmp_path / "Documents"


def test_resolve_known_location_project(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    from modules.known_locations import resolve_known_location

    assert resolve_known_location("the jarvis project") == tmp_path
    assert resolve_known_location("this project") == tmp_path


def test_resolve_known_location_unknown(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    from modules.known_locations import resolve_known_location

    assert resolve_known_location("blahblah") is None
    assert resolve_known_location("") is None


# ------------------------------------------------------------------ open_folder


def test_open_folder_known_name(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda target: opened.append(target))
    result = run(OpenFolderTool().execute({"path": "downloads"}))
    assert result.success
    assert result.data["opened"] == str(tmp_path / "Downloads")
    assert opened == [str(tmp_path / "Downloads")]


def test_open_folder_absolute(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    target = tmp_path / "some_dir"
    target.mkdir()
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenFolderTool().execute({"path": str(target)}))
    assert result.success
    assert result.data["opened"] == str(target)


def test_open_folder_missing(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    result = run(OpenFolderTool().execute({"path": str(tmp_path / "nope")}))
    assert not result.success
    assert "not found" in result.error


def test_open_folder_outside_roots(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    result = run(OpenFolderTool().execute({"path": "/etc"}))
    assert not result.success
    assert "outside the approved roots" in result.error


def test_open_folder_handler_failure_is_honest(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    monkeypatch.setattr(
        "tools.file_tools.desktop_open",
        lambda target: (_ for _ in ()).throw(OSError("xdg-open exited with code 3")),
    )
    result = run(OpenFolderTool().execute({"path": "downloads"}))
    assert not result.success
    assert "code 3" in result.error


# -------------------------------------------------------------------- open_file


def test_open_file_success(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenFileTool().execute({"path": str(tmp_path / "report.txt")}))
    assert result.success
    assert result.data["opened"] == str(tmp_path / "report.txt")


def test_open_file_missing(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    result = run(OpenFileTool().execute({"path": str(tmp_path / "missing.txt")}))
    assert not result.success
    assert "not found" in result.error


def test_open_file_sensitive_refused(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    (tmp_path / "id_rsa").write_text("secret", encoding="utf-8")
    result = run(OpenFileTool().execute({"path": str(tmp_path / "id_rsa")}))
    assert not result.success
    assert "Refusing to open a sensitive file" in result.error


# ---------------------------------------------------------------------- open_url


def test_open_url_https(monkeypatch):
    opened = []
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenUrlTool().execute({"url": "https://example.com"}))
    assert result.success
    assert result.data["opened"] == "https://example.com"
    assert opened == ["https://example.com"]


def test_open_url_domain_gets_https(monkeypatch):
    opened = []
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenUrlTool().execute({"url": "example.com/page"}))
    assert result.success
    assert result.data["opened"] == "https://example.com/page"


def test_open_url_mailto(monkeypatch):
    opened = []
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenUrlTool().execute({"url": "mailto:me@example.com"}))
    assert result.success
    assert result.data["opened"] == "mailto:me@example.com"


def test_open_url_rejects_javascript_and_file(monkeypatch):
    for url in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,x"):
        result = run(OpenUrlTool().execute({"url": url}))
        assert not result.success, url
        assert "Refusing" in result.error or "valid web address" in result.error


def test_open_url_rejects_spaces_and_missing(monkeypatch):
    assert not run(OpenUrlTool().execute({"url": "not a url"})).success
    result = run(OpenUrlTool().execute({}))
    assert not result.success
    assert "Missing url" in result.error


def test_open_url_handler_failure_is_honest(monkeypatch):
    monkeypatch.setattr(
        "tools.desktop_tools.desktop_open",
        lambda t: (_ for _ in ()).throw(OSError("xdg-open is not installed")),
    )
    result = run(OpenUrlTool().execute({"url": "https://example.com"}))
    assert not result.success
    assert "not installed" in result.error


def test_tools_accept_name_argument_alias(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: None)
    assert run(OpenFolderTool().execute({"name": "downloads"})).success
    assert run(OpenUrlTool().execute({"name": "https://example.com"})).success
    assert run(ResolveKnownLocationTool().execute({"location": "Downloads"})).success
    assert run(ResolveKnownLocationTool().execute({"path": "Home"})).success


def test_launch_application_accepts_name_alias(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda _e: "/usr/bin/firefox")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [])
    monkeypatch.setattr("tools.app_tools.time.sleep", lambda _s: None)
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", _FakeProc)
    result = run(LaunchApplicationTool().execute({"name": "firefox"}))
    assert result.success
    assert result.data["executable"] == "/usr/bin/firefox"
    assert result.data["pid"] == _FakeProc.pid


def test_resolve_known_location_tool_accepts_name_alias(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    result = run(ResolveKnownLocationTool().execute({"name": "Downloads"}))
    assert result.success
    assert result.data["path"] == str(tmp_path / "Downloads")


# ------------------------------------------------------------------ applications


class _FakeProc:
    pid = 4242

    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def poll(self):
        return None


class _DeadProc(_FakeProc):
    def poll(self):
        return 1


def test_launch_application_allowed_installed(monkeypatch):
    procs = []
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [])
    monkeypatch.setattr(
        "tools.app_tools.subprocess.Popen", lambda *a, **k: procs.append(a) or _FakeProc(*a, **k)
    )
    result = run(LaunchApplicationTool().execute({"app": "firefox"}))
    assert result.success
    assert result.data["verified"] is True
    assert result.data["pid"] == 4242
    assert procs and procs[0] == (["/usr/bin/firefox"],)


def test_launch_application_alias_vscode(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [])
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))
    result = run(LaunchApplicationTool().execute({"app": "vscode"}))
    assert result.success
    assert result.data["executable"] == "/usr/bin/code"


def test_launch_application_already_running_truthful(monkeypatch):
    """An already-running app must be reported truthfully and not relaunched."""
    procs = []
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [9123])
    monkeypatch.setattr("tools.app_tools._focus_running_app", lambda _p: False)
    monkeypatch.setattr(
        "tools.app_tools.subprocess.Popen", lambda *a, **k: procs.append(a) or _FakeProc(*a, **k)
    )
    result = run(LaunchApplicationTool().execute({"app": "vscode"}))
    assert result.success
    assert result.data["already_running"] is True
    assert result.data["focused"] is False
    assert result.data["verified"] is True
    assert result.data["pids"] == [9123]
    assert procs == []


def test_launch_application_already_running_focus(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [9123])
    monkeypatch.setattr("tools.app_tools._focus_running_app", lambda _p: True)
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))
    result = run(LaunchApplicationTool().execute({"app": "code"}))
    assert result.success
    assert result.data["already_running"] is True
    assert result.data["focused"] is True


def test_launch_application_not_allowed(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    result = run(LaunchApplicationTool().execute({"app": "hackertools"}))
    assert not result.success
    assert "not installed" in result.error or "allowed" in result.error


def test_launch_application_not_installed(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: None)
    result = run(LaunchApplicationTool().execute({"app": "firefox"}))
    assert not result.success
    assert "not installed" in result.error


def test_launch_application_exits_immediately(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [])
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _DeadProc(*a, **k))
    result = run(LaunchApplicationTool().execute({"app": "firefox"}))
    assert not result.success
    assert "exited immediately" in result.error


def test_launch_app_legacy_name_still_works(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.find_running_app", lambda _e: [])
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))
    result = run(LaunchAppTool().execute({"app": "code"}))
    assert result.success


def test_allowed_apps_is_the_single_source():
    from routes.tools import ALLOWED_APPS as routes_allowed

    assert routes_allowed is ALLOWED_APPS


def test_resolve_launch_target_rejects_traversal(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    assert resolve_launch_target("../../etc/passwd") is None
    assert resolve_launch_target("firefox --new-window") is None


# ---------------------------------------------------------- running applications


def test_list_running_applications(monkeypatch):
    class _Proc:
        def __init__(self, name, pid):
            self.info = {"name": name, "pid": pid}

    procs = [_Proc("firefox", 100), _Proc("bash", 101), _Proc("discord", 102)]
    monkeypatch.setattr("tools.desktop_tools.psutil.process_iter", lambda *a, **k: iter(procs))
    result = run(ListRunningApplicationsTool().execute({}))
    assert result.success
    names = [a["name"] for a in result.data["applications"]]
    assert "firefox" in names and "discord" in names
    assert "bash" not in names


# --------------------------------------------------------------- no-shell rule


def test_no_shell_anywhere(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc(args, **kwargs)

    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: None)
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: None)
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", fake_popen)

    run(OpenFolderTool().execute({"path": "downloads"}))
    run(OpenUrlTool().execute({"url": "https://example.com"}))
    run(LaunchApplicationTool().execute({"app": "firefox"}))

    assert calls, "expected subprocess invocations"
    for args, kwargs in calls:
        assert isinstance(args, (list, tuple)) and args, f"expected argv list, got {args!r}"
        assert kwargs.get("shell", False) is False, f"shell must never be True: {kwargs}"
        assert "shlex" not in str(kwargs) or kwargs.get("shell", False) is False


# ---------------------------------------------------- orchestrator tool aliases


class _FakeLLM:
    provider = "mistral"
    api_key = "test"
    api_url = "http://127.0.0.1:9"
    model = "x"
    responses = []

    async def get_response(self, *a, **k):
        raise NotImplementedError


def _make_orch(*tools):
    class _Registry:
        def __init__(self):
            self.t = {t.name: t for t in tools}

        def get_tool(self, name):
            return self.t.get(name)

        def list_tools(self):
            return [t.to_schema() for t in self.t.values()]

        async def execute_tool(self, name, args, context=None):
            return await self.t[name].execute(args, context=context)

    return Orchestrator(_FakeLLM(), _Registry(), CapabilityPolicy())


def test_orchestrator_resolves_open_browser_alias(monkeypatch):
    async def fake_chat(self, messages):
        return '{"tool": "open_browser", "arguments": {"url": "example.com"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: None)
    orch = _make_orch(OpenUrlTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("open example.com", "s1", ctx, {}))
    # The alias resolves to the real tool, runs once, and a repeated identical
    # call is short-circuited into a reply (no duplicate open).
    assert [r["tool"] for r in ctx.tool_results] == ["open_url"]
    assert decision.kind == "reply"


def test_orchestrator_unknown_tool_still_honest(monkeypatch):
    async def fake_chat(self, messages):
        return '{"tool": "teleport", "arguments": {}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(OpenUrlTool())
    decision = run(orch.run("teleport me", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "don't have a way" in decision.text or "way to do that" in decision.text


# -------------------------------------------------------- fake-success guards


def test_orchestrator_reroutes_fake_reply_claim_to_tool(monkeypatch, tmp_path):
    """A reply claiming an open without a tool must be re-prompted into a tool call."""
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    responses = [
        '{"reply": "Your Downloads folder is now open."}',
        '{"tool": "open_folder", "arguments": {"path": "Downloads"}}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: None)
    orch = _make_orch(OpenFolderTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("please open my downloads", "s1", ctx, {}))
    assert calls["n"] >= 2
    assert ctx.tool_results and ctx.tool_results[0]["tool"] == "open_folder"
    assert decision.kind == "reply"


def test_claims_action_heuristic():
    from modules.orchestrator import Orchestrator

    assert Orchestrator._claims_action("Your Downloads folder is now open.")
    assert Orchestrator._claims_action("The terminal is already open.")
    assert Orchestrator._claims_action("I opened the file for you.")
    assert Orchestrator._claims_action("Your file is located at /home/user/x.")
    assert Orchestrator._claims_action("The server is running.")
    assert Orchestrator._claims_action(
        "What applications are running?"
    ), "question must be honest too"
    assert not Orchestrator._claims_action("Hello there, how can I help?")
    assert not Orchestrator._claims_action("I'll open that for you.")
    assert not Orchestrator._claims_action("I'm running out of patience.")


# ------------------------------------------------------- session-context capture


def test_session_context_remembers_resolved_path(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    ctx = SessionContext("s1")
    ctx.record_tool_result(
        "open_folder",
        {"path": "Downloads"},
        {
            "success": True,
            "data": {
                "opened": str(tmp_path / "Downloads"),
                "resolved": str(tmp_path / "Downloads"),
            },
        },
    )
    assert str(tmp_path / "Downloads") in ctx.recent_paths
    assert ctx.resolve_path("downloads") == str(tmp_path / "Downloads")


# ------------------------------------------------------------ resolve tool


def test_resolve_known_location_tool(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    result = run(ResolveKnownLocationTool().execute({"name": "Downloads"}))
    assert result.success
    assert result.data["path"] == str(tmp_path / "Downloads")


def test_resolve_known_location_tool_unknown(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    result = run(ResolveKnownLocationTool().execute({"name": "nonsense"}))
    assert not result.success
    assert "Unknown location" in result.error


# ------------------------------------------------ NL tool-selection regressions


def test_normalize_arguments_maps_compat_keys():
    assert normalize_arguments("open_folder", {"name": "Downloads"}) == {"path": "Downloads"}
    assert normalize_arguments("open_file", {"name": "README"}) == {"path": "README"}
    assert normalize_arguments("launch_application", {"name": "code"}) == {"app": "code"}
    assert normalize_arguments("launch_app", {"name": "code"}) == {"app": "code"}
    assert normalize_arguments("open_url", {"name": "example.com"}) == {"url": "example.com"}
    assert normalize_arguments("resolve_known_location", {"location": "Downloads"}) == {
        "name": "Downloads"
    }
    assert normalize_arguments("resolve_known_location", {"path": "Downloads"}) == {
        "name": "Downloads"
    }
    assert normalize_arguments("list_running_applications", {"format": "text"}) == {}


def test_normalize_arguments_keeps_unknown_keys_for_rejection():
    assert normalize_arguments("open_folder", {"path": "Downloads", "frobnicate": "x"}) == {
        "path": "Downloads",
        "frobnicate": "x",
    }


def test_validate_arguments_unknown_key_hint():
    err = OpenFolderTool().validate_arguments({"path": "Downloads", "frobnicate": "x"})
    assert err is not None and "frobnicate" in err and "'path'" in err


def test_validate_arguments_string_type_checked():
    err = OpenFolderTool().validate_arguments({"path": 123})
    assert err is not None and "must be a string" in err


def test_nl_list_apps_ignores_format_hint(monkeypatch):
    class _Proc:
        def __init__(self, name, pid):
            self.info = {"name": name, "pid": pid}

    monkeypatch.setattr(
        "tools.desktop_tools.psutil.process_iter",
        lambda *a, **k: iter([_Proc("firefox", 1)]),
    )

    async def fake_chat(self, messages):
        return '{"tool": "list_running_applications", "arguments": {"format": "text"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ListRunningApplicationsTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("what applications are running?", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["list_running_applications"]
    assert ctx.tool_results[0]["args"] == {}
    assert decision.kind == "reply"


def test_nl_open_folder_name_arg_normalized_to_path(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))

    async def fake_chat(self, messages):
        return '{"tool": "open_folder", "arguments": {"name": "Downloads"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(OpenFolderTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("please open my downloads", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["open_folder"]
    assert ctx.tool_results[0]["args"] == {"path": "Downloads"}
    assert opened == [str(tmp_path / "Downloads")]
    assert decision.kind == "reply"


def test_nl_unknown_arg_rejected_with_hint(monkeypatch):
    async def fake_chat(self, messages):
        return '{"tool": "open_folder", "arguments": {"path": "Downloads", "frobnicate": "x"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(OpenFolderTool())
    decision = run(orch.run("please open downloads", "s1", SessionContext("s1"), {}))
    assert decision.kind == "reply"
    assert "frobnicate" in decision.text
    assert "'path'" in decision.text


def test_nl_question_as_url_is_honest(monkeypatch):
    async def fake_chat(self, messages):
        return '{"tool": "open_url", "arguments": {"url": "What applications are running?"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    monkeypatch.setattr("tools.desktop_tools.desktop_open", lambda t: None)
    orch = _make_orch(OpenUrlTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("what applications are running?", "s1", ctx, {}))
    assert decision.kind == "reply"
    assert ctx.tool_results and not ctx.tool_results[0]["result"].get("success")
    assert "doesn't look like a valid web address" in decision.text


def test_nl_mangled_path_rejected_honestly(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)

    async def fake_chat(self, messages):
        return '{"tool": "open_folder", "arguments": {"path": "resolve known location"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: None)
    orch = _make_orch(OpenFolderTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("please open my downloads", "s1", ctx, {}))
    assert decision.kind == "reply"
    error = ctx.tool_results[0]["result"]["error"].lower()
    assert not ctx.tool_results[0]["result"]["success"]
    assert "not found" in error or "outside the approved roots" in error


def test_nl_two_step_resolve_then_open_folder(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    download_path = str(tmp_path / "Downloads")
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "Downloads"}}',
        '{"tool": "open_folder", "arguments": {"path": "' + download_path + '"}}',
        '{"reply": "Your Downloads folder is open."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFolderTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("please open my downloads", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_folder"]
    assert ctx.tool_results[1]["args"]["path"] == download_path
    assert opened == [download_path]
    assert decision.kind == "reply"


def test_nl_open_readme_two_step(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    readme = tmp_path / "README.md"
    readme.write_text("# JARVIS\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "open_file", "arguments": {"path": "' + str(readme) + '"}}',
        '{"reply": "Opened the README."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("open the readme", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_file"]
    assert ctx.tool_results[1]["args"]["path"] == str(readme)
    assert opened == [str(readme)]
    assert decision.kind == "reply"


def test_nl_launch_vs_code_via_launch_application(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))

    async def fake_chat(self, messages):
        return '{"tool": "launch_application", "arguments": {"app": "vs code"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(LaunchApplicationTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("open vs code", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["launch_application"]
    assert ctx.tool_results[0]["args"]["app"] == "vs code"
    assert ctx.tool_results[0]["result"]["success"] is True
    assert decision.kind == "reply"


def test_nl_legacy_launch_app_name_maps_to_canonical(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))

    async def fake_chat(self, messages):
        return '{"tool": "launch_app", "arguments": {"app": "firefox"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(LaunchApplicationTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("launch firefox", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["launch_application"]
    assert decision.kind == "reply"


def test_nl_repeated_launch_suppressed(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("tools.app_tools.subprocess.Popen", lambda *a, **k: _FakeProc(*a, **k))

    async def fake_chat(self, messages):
        return '{"tool": "launch_application", "arguments": {"app": "firefox"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(LaunchApplicationTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("launch firefox", "s1", ctx, {}))
    assert len(ctx.tool_results) == 1
    assert decision.kind == "reply"


def test_nl_bare_string_argument_coerced(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))

    async def fake_chat(self, messages):
        return '{"tool": "open_folder", "arguments": "Downloads"}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(OpenFolderTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("please open downloads", "s1", ctx, {}))
    assert ctx.tool_results and ctx.tool_results[0]["tool"] == "open_folder"
    assert ctx.tool_results[0]["args"] == {"path": "Downloads"}
    assert opened == [str(tmp_path / "Downloads")]
    assert decision.kind == "reply"


def test_nl_followup_resolves_recent_path(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    ctx = SessionContext("s1")
    ctx.record_tool_result(
        "resolve_known_location",
        {"name": "Downloads"},
        {"success": True, "data": {"path": str(tmp_path / "Downloads")}},
    )
    assert ctx.resolve_path("the downloads folder") == str(tmp_path / "Downloads")

    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))

    async def fake_chat(self, messages):
        text = "".join(str(m.get("content", "")) for m in messages)
        assert str(tmp_path / "Downloads") in text
        return (
            '{"tool": "open_folder", "arguments": {"path": "' + str(tmp_path / "Downloads") + '"}}'
        )

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(OpenFolderTool())
    decision = run(orch.run("open that folder", "s1", ctx, {}))
    assert ctx.tool_results[-1]["tool"] == "open_folder"
    assert decision.kind == "reply"


# ------------------------------------------------------- README-open steering


def test_find_readme_single_candidate(tmp_path):
    (tmp_path / "README.md").write_text("# hello", encoding="utf-8")
    assert find_readme(tmp_path) == [tmp_path / "README.md"]


def test_find_readme_case_and_txt_variants(tmp_path):
    (tmp_path / "README.TXT").write_text("x", encoding="utf-8")
    (tmp_path / "readme").write_text("y", encoding="utf-8")
    names = sorted(f.name for f in find_readme(tmp_path))
    assert names == ["README.TXT", "readme"]


def test_find_readme_docs_subdir(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("d", encoding="utf-8")
    assert find_readme(tmp_path) == [tmp_path / "docs" / "README.md"]


def test_find_readme_no_candidate(tmp_path):
    (tmp_path / "AGENTS.md").write_text("a", encoding="utf-8")
    assert find_readme(tmp_path) == []


def test_find_readme_multiple_candidates(tmp_path):
    (tmp_path / "README.md").write_text("r", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README").write_text("d", encoding="utf-8")
    assert len(find_readme(tmp_path)) == 2


def test_find_readme_non_dir(tmp_path):
    assert find_readme(tmp_path / "nope") == []


def test_is_readme_open_request_heuristic():
    assert Orchestrator._is_readme_open_request("Open the README.")
    assert Orchestrator._is_readme_open_request("Please read the README")
    assert not Orchestrator._is_readme_open_request("Open this URL: https://example.com/readme")
    assert not Orchestrator._is_readme_open_request("What is my Downloads folder?")


def test_readme_open_flow_single_candidate(monkeypatch, tmp_path):
    """Model resolves the project then stops -> orchestrator must steer to open_file."""
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    readme = tmp_path / "README.md"
    readme.write_text("# JARVIS\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"reply": "Done."}',  # the model stopping after resolving must be overridden
        '{"tool": "open_file", "arguments": {"path": "' + str(readme) + '"}}',
        '{"reply": "Opened the README."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_file"]
    assert ctx.tool_results[1]["args"]["path"] == str(readme)
    assert ctx.tool_results[1]["result"]["success"] is True
    assert opened == [str(readme)]
    assert decision.kind == "reply"
    assert not any(
        "can't" in (r.get("error") or "")
        for _, r in [(t["tool"], t["result"]) for t in ctx.tool_results]
    )


def test_readme_open_no_candidate_truthful(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    (tmp_path / "AGENTS.md").write_text("a", encoding="utf-8")
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"reply": "Done."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location"]
    assert decision.kind == "reply"
    assert "couldn't find a README" in decision.text
    assert not any(
        r["result"].get("success")
        for r in ctx.tool_results
        if r["tool"] != "resolve_known_location"
    )


def test_readme_open_repeated_resolve_still_steers(monkeypatch, tmp_path):
    """The model re-emitting resolve after it already succeeded must be steered, not 'Done.'."""
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    readme = tmp_path / "README.md"
    readme.write_text("# JARVIS\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "open_file", "arguments": {"path": "' + str(readme) + '"}}',
        '{"reply": "Opened the README."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_file"]
    assert ctx.tool_results[1]["result"]["success"] is True
    assert opened == [str(readme)]
    assert decision.kind == "reply"
    assert decision.text != "Done."


def test_readme_open_multiple_candidates_clarifies(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    (tmp_path / "README.md").write_text("r", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("d", encoding="utf-8")
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"reply": "Done."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location"]
    assert decision.kind == "reply"
    assert "README" in decision.text and "which one" in decision.text.lower()


def test_readme_no_candidate_when_model_stops_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))

    async def fake_chat(self, messages):
        return '{"reply": "Sure, I can help with that."}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert decision.kind == "reply"
    assert "couldn't find a README" in decision.text
    assert not ctx.tool_results


def test_readme_open_outside_root_rejected(monkeypatch):
    async def fake_chat(self, messages):
        return '{"tool": "open_file", "arguments": {"path": "/etc/README.md"}}'

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: None)
    orch = _make_orch(OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert decision.kind == "reply"
    assert not ctx.tool_results[0]["result"]["success"]
    assert "outside the approved roots" in ctx.tool_results[0]["result"]["error"].lower()


def test_resolve_result_intermediate_fields(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    result = run(ResolveKnownLocationTool().execute({"name": "Downloads"}))
    assert result.success
    assert result.data["canonical_path"] == str(tmp_path / "Downloads")
    assert result.data["target_type"] == "folder"
    assert result.data["exists"] is True
    assert result.data["continue_required"] is True


def test_resolve_result_project_type(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    result = run(ResolveKnownLocationTool().execute({"name": "the jarvis project"}))
    assert result.success
    assert result.data["target_type"] == "project"


def test_open_file_result_complete_fields(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    target = tmp_path / "report.txt"
    target.write_text("hi", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    result = run(OpenFileTool().execute({"path": str(target)}))
    assert result.success
    assert result.data["opened"] == str(target)
    assert result.data["canonical_path"] == str(target)
    assert result.data["exists"] is True
    assert result.data["complete"] is True
    assert result.data["target_type"] == "file"


def test_open_file_missing_result_fields(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    missing = tmp_path / "nope.md"
    result = run(OpenFileTool().execute({"path": str(missing)}))
    assert not result.success
    assert result.data is not None
    assert result.data["exists"] is False
    assert result.data["complete"] is True
    assert result.data["target_type"] == "file"


def test_readme_open_after_failed_guess_steers_to_candidate(monkeypatch, tmp_path):
    """A failed open_file guess on a README request is not the final answer:
    the orchestrator searches deterministically and re-opens the real candidate."""
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    readme = tmp_path / "README.md"
    readme.write_text("# JARVIS\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    wrong = str(tmp_path / "README")
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "open_file", "arguments": {"path": "'
        + wrong
        + '"}}',  # model guesses a wrong path
        '{"tool": "open_file", "arguments": {"path": "'
        + str(readme)
        + '"}}',  # steered to the real candidate
        '{"reply": "Opened the README."}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == [
        "resolve_known_location",
        "open_file",
        "open_file",
    ]
    assert opened == [str(readme)]
    assert ctx.tool_results[2]["result"]["success"] is True
    assert decision.kind == "reply"


def test_readme_open_after_failed_guess_no_candidate_truthful(monkeypatch, tmp_path):
    """A failed open_file guess with no real README must yield a truthful not-found."""
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "open_file", "arguments": {"path": "' + str(tmp_path / "README") + '"}}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        text = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return text

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_file"]
    assert not ctx.tool_results[1]["result"]["success"]
    assert decision.kind == "reply"
    assert "couldn't find a README" in decision.text


def test_readme_open_provider_error_after_open_reports_verified(monkeypatch, tmp_path):
    """If the provider fails while confirming an already-verified README open,
    the orchestrator reports the real opened path instead of a generic error."""
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("JARVIS_APPROVED_ROOTS", str(tmp_path))
    readme = tmp_path / "README.md"
    readme.write_text("# JARVIS\n", encoding="utf-8")
    opened = []
    monkeypatch.setattr("tools.file_tools.desktop_open", lambda t: opened.append(t))
    responses = [
        '{"tool": "resolve_known_location", "arguments": {"name": "the jarvis project"}}',
        '{"tool": "open_file", "arguments": {"path": "' + str(readme) + '"}}',
    ]
    calls = {"n": 0}

    async def fake_chat(self, messages):
        idx = calls["n"]
        calls["n"] += 1
        if idx >= len(responses):
            raise RuntimeError("provider down")
        return responses[idx]

    monkeypatch.setattr(Orchestrator, "_openai_chat", fake_chat)
    orch = _make_orch(ResolveKnownLocationTool(), OpenFileTool())
    ctx = SessionContext("s1")
    decision = run(orch.run("Open the README.", "s1", ctx, {}))
    assert [r["tool"] for r in ctx.tool_results] == ["resolve_known_location", "open_file"]
    assert opened == [str(readme)]
    assert decision.kind == "reply"
    assert "I've opened the README at" in decision.text


# ------------------------------------------------------------------ diagnostics


def _fake_opener(monkeypatch, tmp_path, body: str) -> str:
    """Point modules.desktop_open at a real, runnable fake xdg-open script."""
    script = tmp_path / "xdg-open"
    script.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setattr("modules.desktop_open.shutil.which", lambda _name: str(script))
    return str(script)


def test_slow_but_successful_opener_is_not_a_false_failure(monkeypatch, tmp_path):
    """A slow desktop handoff (cold app start, busy D-Bus) must not be reported
    as 'cannot open': the old 2.0s hard timeout killed a 2.2s successful open."""
    _fake_opener(monkeypatch, tmp_path, "sleep 2.2\nexit 0")
    desktop_open(str(tmp_path))


def test_desktop_open_exit_code_diagnostics(monkeypatch, tmp_path):
    _fake_opener(monkeypatch, tmp_path, "echo 'no method available' >&2\nexit 3")
    with pytest.raises(DesktopOpenError) as excinfo:
        desktop_open(str(tmp_path), action_type="folder", permission_result="approved")
    assert "code 3" in str(excinfo.value)
    diag = excinfo.value.diagnostics
    assert diag["action_type"] == "folder"
    assert diag["target"] == str(tmp_path)
    assert diag["resolved_executable"] == str(tmp_path / "xdg-open")
    assert diag["canonical_path"] == str(tmp_path)
    assert isinstance(diag["user_id"], int)
    assert diag["user_name"] == "wiz"
    assert isinstance(diag["gui_env"], dict)
    assert isinstance(diag["gui_env"].get("DISPLAY"), bool)
    assert diag["exit_code"] == 3
    assert diag["stderr_category"] == "no-application-registered"
    assert diag["timed_out"] is False
    assert diag["timeout_seconds"] == 5.0
    assert diag["permission_result"] == "approved"


def test_desktop_open_timeout_is_truthful_and_metadata(monkeypatch, tmp_path):
    _fake_opener(monkeypatch, tmp_path, "sleep 30")
    t0 = time.monotonic()
    with pytest.raises(DesktopOpenError) as excinfo:
        desktop_open(str(tmp_path), timeout=1.0)
    assert "may still have opened" in str(excinfo.value)
    diag = excinfo.value.diagnostics
    assert diag["timed_out"] is True
    assert diag["stderr_category"] == "timeout"
    assert diag["exit_code"] is None
    assert time.monotonic() - t0 < 5.0


def test_desktop_open_no_graphical_session_precheck(monkeypatch, tmp_path):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    _fake_opener(monkeypatch, tmp_path, "exit 0")
    with pytest.raises(DesktopOpenError) as excinfo:
        desktop_open(str(tmp_path))
    assert "without a graphical session" in str(excinfo.value)
    diag = excinfo.value.diagnostics
    assert diag["stderr_category"] == "no-graphical-session"
    assert diag["gui_env"]["DISPLAY"] is False
    assert diag["gui_env"]["WAYLAND_DISPLAY"] is False


def test_desktop_open_missing_opener_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setattr("modules.desktop_open.shutil.which", lambda _name: None)
    with pytest.raises(DesktopOpenError) as excinfo:
        desktop_open(str(tmp_path))
    assert "not installed" in str(excinfo.value)
    diag = excinfo.value.diagnostics
    assert diag["resolved_executable"] is None
    assert diag["exit_code"] is None


def test_classify_stderr_categories():
    from modules.desktop_open import classify_stderr

    assert classify_stderr("no method available for opening") == "no-application-registered"
    assert classify_stderr("cannot open display: :0") == "no-graphical-session"
    assert classify_stderr("Permission denied") == "permission-denied"
    assert classify_stderr("") is None
    assert classify_stderr("random error") == "other"


def test_open_folder_failure_embeds_diagnostics(monkeypatch, tmp_path):
    _fake_home(monkeypatch, tmp_path)
    _populate_home(tmp_path)
    monkeypatch.setattr(
        "tools.file_tools.desktop_open",
        lambda target: (_ for _ in ()).throw(OSError("xdg-open exited with code 3")),
    )
    result = run(OpenFolderTool().execute({"path": "downloads"}))
    assert not result.success
    assert "code 3" in result.error
    diag = result.data["diagnostics"]
    assert diag["action_type"] == "folder"
    assert diag["target"] == str(tmp_path / "Downloads")
    assert "gui_env" in diag
    assert diag["permission_result"] == "approved"


def test_launch_not_allowed_embeds_diagnostics(monkeypatch):
    monkeypatch.setattr("tools.app_tools.shutil.which", lambda _name: None)
    result = run(LaunchApplicationTool().execute({"app": "hackertools"}))
    assert not result.success
    diag = result.data["diagnostics"]
    assert diag["action_type"] == "application"
    assert diag["target"] == "hackertools"
    assert diag["permission_result"] == "not-allowlisted-or-not-installed"
