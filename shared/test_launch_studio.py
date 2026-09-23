# -*- coding: utf-8 -*-
"""Launcher regressions: no live browser, server, or writing pipeline commands."""
import builtins
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

import pytest

import launch_studio as launcher


def test_identity_requires_the_complete_bound_context(tmp_path):
    from launch_studio import matches_service

    project = tmp_path / "projects" / "novel"
    expected = {
        "workspace": str(tmp_path), "project_path": str(project),
        "workflow": "graph.yaml", "chapter": 51,
    }
    health = dict(expected, status="ok", service="novel-pipeline-studio",
                  studio_protocol=1, bound_project="novel")
    assert matches_service(health, expected)
    for field, value in [
        ("workspace", str(tmp_path / "other-workspace")),
        ("project_path", str(tmp_path / "elsewhere" / "novel")),
        ("project_path", "projects/novel"),
        ("workflow", "volume_graph.yaml"), ("chapter", 52),
        ("chapter", "51"), ("studio_protocol", 2),
        ("studio_protocol", True), ("bound_project", None),
        ("bound_project", "other"), ("service", "other-service"),
        ("status", "error"),
    ]:
        assert not matches_service(dict(health, **{field: value}), expected), field
    for field in health:
        missing = dict(health)
        del missing[field]
        assert not matches_service(missing, expected), field
    assert not matches_service(None, expected)
    assert not matches_service([], expected)
    assert matches_service(dict(health, project_path=str(project / ".." / "novel")), expected)
    assert matches_service(dict(health, chapter=None), dict(expected, chapter=None))
    assert not matches_service(dict(health, chapter=True), dict(expected, chapter=1))


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "projects" / "novel"
    root.mkdir(parents=True)
    (root / "graph.yaml").write_text(
        "params: {chapter_num: '051'}\nnodes:\n"
        "  gate: {kind: human, ask: Confirm, outputs: ['chapter-{chapter_pad}.txt']}\n",
        encoding="utf-8",
    )
    (root / "pipeline.json").write_text('{"humanAck": "keep"}', encoding="utf-8")
    return root


def test_graph_validation_is_read_only_and_uses_normalized_chapter(project, tmp_path, monkeypatch):
    import pipeline

    def forbidden(*args, **kwargs):
        pytest.fail("Launcher must never execute or reconcile pipeline state")

    for name in ("cmd_status", "cmd_reconcile", "cmd_run", "cmd_start", "cmd_finish",
                 "write_state_atomic", "derive_status"):
        monkeypatch.setattr(pipeline, name, forbidden)
    before = {p.name: p.read_bytes() for p in project.iterdir()}
    context = launcher.resolve_context("novel", workspace=tmp_path)
    assert context["project_path"] == str(project.resolve())
    assert context["workspace"] == str(tmp_path.resolve())
    assert context["bound_project"] == "novel"
    assert context["chapter"] == 51
    assert launcher.resolve_context(str(project), chapter=7, workspace=tmp_path)["chapter"] == 7
    assert {p.name: p.read_bytes() for p in project.iterdir()} == before


def test_registered_external_project_resolution_does_not_rewrite_registry(project, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    registry = shared / "custom_projects.json"
    registry.write_text(json.dumps([str(project)]), encoding="utf-8")
    # An external workspace can use the same existing registry without registering anything.
    other = tmp_path / "other"
    (other / "shared").mkdir(parents=True)
    other_registry = other / "shared" / "custom_projects.json"
    other_registry.write_bytes(registry.read_bytes())
    before = other_registry.read_bytes()
    assert launcher.resolve_context("novel", workspace=other)["project_path"] == str(project)
    assert other_registry.read_bytes() == before


@pytest.mark.parametrize("workflow", ["../graph.yaml", "sub/graph.yaml", "sub\\graph.yaml", "graph.json"])
def test_workflow_must_be_a_root_yaml_file(project, tmp_path, workflow):
    with pytest.raises(launcher.LaunchError):
        launcher.resolve_context(str(project), workflow=workflow, workspace=tmp_path)


@pytest.mark.parametrize("text", ["nodes: {}", "nodes: [", "nodes:\n  a: {kind: agent, after: [a]}"])
def test_invalid_graph_fails_before_network_or_process(project, tmp_path, text, monkeypatch):
    (project / "graph.yaml").write_text(text, encoding="utf-8")
    monkeypatch.setattr(launcher, "request_json", Mock(side_effect=AssertionError("network")))
    monkeypatch.setattr(launcher, "spawn_server", Mock(side_effect=AssertionError("spawn")))
    with pytest.raises(launcher.LaunchError):
        launcher.resolve_context(str(project), workspace=tmp_path)


def test_missing_graph_fails_readably(project, tmp_path):
    (project / "graph.yaml").unlink()
    with pytest.raises(launcher.LaunchError, match="graph.yaml"):
        launcher.resolve_context(str(project), workspace=tmp_path)


def test_missing_yaml_dependency_is_a_readable_error(project, tmp_path, monkeypatch):
    original = builtins.__import__

    def without_pipeline(name, *args, **kwargs):
        if name == "pipeline":
            raise ModuleNotFoundError("No module named 'yaml'")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_pipeline)
    with pytest.raises(launcher.LaunchError, match="yaml"):
        launcher.resolve_context(str(project), workspace=tmp_path)


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False
        self.stubborn = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.returncode = -15

    def wait(self, timeout=None):
        if self.stubborn and not self.killed:
            raise subprocess.TimeoutExpired("server", timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """Fake only the external boundaries; launch/session/identity logic stays real."""
    class Rig:
        now = 0.0
        context = {
            "workspace": str(tmp_path), "project_path": str(tmp_path / "novel"),
            "bound_project": "novel", "workflow": "graph.yaml", "chapter": 51,
            "studio_protocol": 1,
        }

        def __init__(self):
            self.services = {}
            self.calls = []
            self.spawned = []
            self.sessions = []
            self.opened = []
            self.poll_result = lambda session: dict(session, status="ready")
            self.creation_result = lambda session: session
            self.on_spawn = None

        def health(self, **changes):
            return dict(self.context, status="ok", service="novel-pipeline-studio", **changes)

        def tick(self, seconds):
            self.now += seconds

        def request(self, url, *, method="GET", timeout=1):
            assert 0 < timeout <= 2
            parsed = urlparse(url)
            self.calls.append((parsed.port, method, parsed.path))
            if parsed.path == "/api/health":
                if parsed.port not in self.services:
                    raise URLError("no listener")
                return self.services[parsed.port]
            if parsed.path == "/api/ui/session":
                assert method == "POST"
                session = {
                    "launch_id": "new-launch-" + str(len(self.sessions) + 1),
                    "revision": "a" * 64, "project": "novel",
                    "project_path": self.context["project_path"],
                    "workflow": "graph.yaml", "chapter": 51, "status": "pending",
                }
                self.sessions.append(session)
                return self.creation_result(session)
            assert method == "GET"
            assert parsed.path == "/api/ui/session/" + self.sessions[-1]["launch_id"]
            return self.poll_result(self.sessions[-1])

        def spawn(self, context, port):
            assert context == self.context
            process = FakeProcess()
            self.spawned.append((port, process))
            if self.on_spawn:
                self.on_spawn(port, process)
            else:
                self.services[port] = self.health()
            return process, tmp_path / "server.log"

        def open_browser(self, url):
            self.opened.append(url)
            return True

        def run(self, **options):
            return launcher.launch(self.context, timeout=2, **options)

    r = Rig()
    monkeypatch.setattr(launcher.time, "monotonic", lambda: r.now)
    monkeypatch.setattr(launcher.time, "sleep", r.tick)
    monkeypatch.setattr(launcher, "request_json", r.request)
    monkeypatch.setattr(launcher, "port_available", lambda port: port not in r.services)
    monkeypatch.setattr(launcher, "spawn_server", r.spawn)
    monkeypatch.setattr(launcher.webbrowser, "open", r.open_browser)
    return r


def test_scans_for_existing_match_before_starting_on_an_earlier_free_port(rig):
    rig.services[8766] = dict(rig.health(), project_path=str(Path(rig.context["workspace"]) / "other" / "novel"))
    rig.services[8785] = rig.health()
    result = rig.run()
    assert result["reused"] is True
    assert result["status"] == "ready"
    assert result["awaiting_confirmation"] is True
    assert result["url"] == "http://127.0.0.1:8785/?launch_id=new-launch-1"
    assert result["project_path"] == rig.context["project_path"]
    assert result["chapter"] == 51
    assert result["project"] == "novel"
    assert not rig.spawned
    assert rig.opened == [result["url"]]


@pytest.mark.parametrize('slow_path', ['/api/ui/session', '/api/ui/session/new-launch-1'])
def test_snapshot_session_requests_can_exceed_one_second_within_launch_deadline(rig, monkeypatch, slow_path):
    rig.services[8766] = rig.health()
    request = rig.request

    def slow_snapshot(url, *, method='GET', timeout=1):
        if urlparse(url).path == slow_path:
            rig.tick(min(1.2, timeout))
            if timeout < 1.2:
                raise TimeoutError('snapshot still computing')
        return request(url, method=method, timeout=timeout)

    monkeypatch.setattr(launcher, 'request_json', slow_snapshot)
    result = rig.run()
    assert result['status'] == 'ready'
    assert rig.now == 1.2
    assert len(rig.sessions) == 1


def test_every_reuse_creates_a_new_session_and_never_posts_ready(rig):
    rig.services[8766] = rig.health()
    first = rig.run()
    second = rig.run()
    assert first["launch_id"] != second["launch_id"]
    assert first["url"] != second["url"]
    assert sum(method == "POST" for _, method, _ in rig.calls) == 2
    assert all(path != "/api/ui/ready" for _, _, path in rig.calls)


def test_no_open_prints_url_on_stderr_then_waits_for_ui_receipt(rig, capsys):
    rig.services[8766] = rig.health()
    polls = []

    def pending_then_ready(session):
        polls.append(session["launch_id"])
        assert "http://127.0.0.1:8766/?launch_id=new-launch-1" in capsys.readouterr().err or len(polls) > 1
        return dict(session, status="ready" if len(polls) == 2 else "pending")

    rig.poll_result = pending_then_ready
    assert rig.run(no_open=True)["status"] == "ready"
    assert len(polls) == 2
    assert not rig.opened
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("owned", [False, True])
def test_timeout_never_accepts_pending_and_only_cleans_owned_process(rig, owned):
    if not owned:
        rig.services[8766] = rig.health()
    rig.poll_result = lambda session: session
    with pytest.raises(launcher.LaunchError, match="[Tt]imeout|[Tt]imed out"):
        rig.run(no_open=True)
    assert rig.now >= 2
    if owned:
        assert rig.spawned[0][1].terminated
    else:
        assert not rig.spawned


@pytest.mark.parametrize("bad", [
    {"launch_id": "old-launch"}, {"revision": "b" * 64},
    {"project_path": "/elsewhere/novel"}, {"project": "other"},
    {"workflow": "volume_graph.yaml"}, {"chapter": 52}, {"chapter": "51"},
    {"status": "unknown"},
])
def test_rejects_stale_or_wrong_identity_receipt(rig, bad):
    rig.services[8766] = rig.health()
    rig.poll_result = lambda session: dict(session, **dict({"status": "ready"}, **bad))
    with pytest.raises(launcher.LaunchError):
        rig.run()


@pytest.mark.parametrize("bad", [{"status": "ready"}, {"launch_id": ""}, {"revision": ""}, {"project": "other"}])
def test_session_creation_must_return_a_fresh_pending_identity(rig, bad):
    rig.creation_result = lambda session: dict(session, **bad)
    with pytest.raises(launcher.LaunchError):
        rig.run()
    assert not rig.opened
    assert rig.spawned[0][1].terminated


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("behavior", ["false", "exception"])
def test_browser_failure_is_nonzero_and_preserves_reused_service(rig, monkeypatch, owned, behavior):
    if not owned:
        rig.services[8766] = rig.health()

    def broken_browser(url):
        if behavior == "exception":
            raise OSError("browser missing")
        return False

    monkeypatch.setattr(launcher.webbrowser, "open", broken_browser)
    with pytest.raises(launcher.LaunchError, match="[Bb]rowser|browser"):
        rig.run()
    assert bool(rig.spawned) == owned
    if owned:
        assert rig.spawned[0][1].terminated


def test_starts_only_after_scanning_twenty_ports_and_keeps_successful_child(rig):
    def on_spawn(port, process):
        assert [port for port, _, _ in rig.calls] == list(range(8766, 8786))
        rig.services[port] = rig.health()

    rig.on_spawn = on_spawn
    result = rig.run()
    assert not result["reused"]
    assert len(rig.spawned) == 1
    assert not rig.spawned[0][1].terminated


def test_all_ports_occupied_fails_without_spawning_or_killing(rig):
    for port in range(8766, 8786):
        rig.services[port] = {"service": "some-other-app"}
    with pytest.raises(launcher.LaunchError, match="port"):
        rig.run()
    assert not rig.spawned


def test_concurrent_foreign_listener_moves_to_next_port_and_cleans_only_own_child(rig):
    def on_spawn(port, process):
        if port == 8766:
            rig.services[port] = {"service": "foreign-winner"}
        else:
            rig.services[port] = rig.health()

    rig.on_spawn = on_spawn
    result = rig.run()
    assert result["url"].startswith("http://127.0.0.1:8767/")
    assert rig.spawned[0][1].terminated
    assert not rig.spawned[1][1].terminated


def test_concurrent_matching_listener_can_be_reused_after_owned_child_exits(rig):
    def on_spawn(port, process):
        process.returncode = 1
        rig.services[port] = rig.health()

    rig.on_spawn = on_spawn
    result = rig.run()
    assert result["reused"] is True
    assert len(rig.spawned) == 1
    assert not rig.spawned[0][1].terminated


def test_early_child_exit_reports_startup_failure(rig):
    rig.on_spawn = lambda port, process: setattr(process, "returncode", 1)
    with pytest.raises(launcher.LaunchError, match="exit|start"):
        rig.run()
    assert not rig.sessions
    assert len(rig.spawned) == 1


def test_startup_health_timeout_cleans_own_child(rig):
    rig.on_spawn = lambda port, process: None
    with pytest.raises(launcher.LaunchError, match="[Tt]imeout|[Tt]imed out"):
        rig.run()
    assert rig.spawned[0][1].terminated


def test_child_exit_while_waiting_for_ui_is_not_success(rig):
    def exit_before_receipt(session):
        rig.spawned[0][1].returncode = 1
        return dict(session, status="ready")

    rig.poll_result = exit_before_receipt
    with pytest.raises(launcher.LaunchError, match="exit"):
        rig.run()


def test_service_identity_is_checked_again_before_ready(rig):
    rig.services[8766] = rig.health()

    def replaced(session):
        rig.services[8766] = dict(rig.health(), workspace=str(Path(rig.context["workspace"]) / "other"))
        return dict(session, status="ready")

    rig.poll_result = replaced
    with pytest.raises(launcher.LaunchError, match="identity"):
        rig.run()


def test_expired_session_fails_instead_of_creating_another(rig):
    rig.services[8766] = rig.health()
    rig.poll_result = Mock(side_effect=HTTPError("local", 404, "expired", {}, None))
    with pytest.raises(launcher.LaunchError, match="404|expired"):
        rig.run()
    assert len(rig.sessions) == 1


def test_interrupt_cleans_owned_child_with_kill_fallback(rig):
    def interrupt(session):
        rig.spawned[0][1].stubborn = True
        raise KeyboardInterrupt

    rig.poll_result = interrupt
    with pytest.raises(KeyboardInterrupt):
        rig.run()
    assert rig.spawned[0][1].terminated
    assert rig.spawned[0][1].killed


def test_spawn_uses_current_python_and_workspace_cache_not_novel(project, tmp_path, monkeypatch):
    context = launcher.resolve_context(str(project), workspace=tmp_path)
    popen = Mock(return_value=FakeProcess())
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    before = {p.name: p.read_bytes() for p in project.iterdir()}
    _, log = launcher.spawn_server(context, 8888)
    command = popen.call_args.args[0]
    assert command[0] == sys.executable
    assert str(launcher.WORKSPACE / "shared" / "server.py") in command
    for flag, expected in [("--host", "127.0.0.1"), ("--port", "8888"),
                           ("--project", str(project)), ("--workflow", "graph.yaml"),
                           ("--chapter", "51")]:
        assert command[command.index(flag) + 1] == expected
    assert not popen.call_args.kwargs.get("shell")
    assert Path(log).parent == tmp_path / "shared" / "__pycache__" / "studio-logs"
    assert popen.call_args.kwargs["stdout"].closed
    assert popen.call_args.kwargs["stderr"] == subprocess.STDOUT
    assert {p.name: p.read_bytes() for p in project.iterdir()} == before


def test_http_session_creation_is_bodyless_and_bypasses_proxies(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b'{"status":"pending"}'
    opener = Mock()
    opener.open.return_value = response
    factory = Mock(return_value=opener)
    monkeypatch.setattr(launcher.urllib.request, "build_opener", factory)
    assert launcher.request_json("http://127.0.0.1:8766/api/ui/session", method="POST", timeout=0.5) == {"status": "pending"}
    request = opener.open.call_args.args[0]
    assert request.get_method() == "POST"
    assert request.data is None
    assert opener.open.call_args.kwargs["timeout"] == 0.5
    assert any(isinstance(handler, launcher.urllib.request.ProxyHandler) and handler.proxies == {}
               for handler in factory.call_args.args)


def test_cli_emits_only_final_json_and_leaves_confirmation_to_supervisor(rig, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "resolve_context", lambda *args, **kwargs: rig.context)
    assert launcher.main(["--project", "novel", "--timeout", "2", "--no-open"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["awaiting_confirmation"] is True
    assert result["status"] == "ready"
    assert result["url"] in captured.err


def test_cli_reports_failure_as_json_and_nonzero(rig, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "resolve_context", lambda *args, **kwargs: rig.context)
    rig.poll_result = lambda session: session
    assert launcher.main(["--project", "novel", "--timeout", "2", "--no-open"]) != 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "error"
    assert result["error"]
    assert "http://127.0.0.1:" in captured.err


@pytest.mark.parametrize("options", [{"port": 0}, {"port": 65536}, {"timeout": 0}, {"timeout": float("nan")}])
def test_invalid_launch_limits_fail_before_io(rig, options):
    with pytest.raises(launcher.LaunchError):
        launcher.launch(rig.context, **options)
    assert not rig.calls
    assert not rig.spawned


def test_matching_service_appearing_after_scan_is_reused_without_duplicate_spawn(rig, monkeypatch):
    def became_occupied(port):
        rig.services[port] = rig.health()
        return False

    monkeypatch.setattr(launcher, "port_available", became_occupied)
    result = rig.run()
    assert result["reused"] is True
    assert not rig.spawned


@pytest.mark.parametrize("status", [[], {}, None, 1])
def test_malformed_receipt_status_is_a_readable_failure(rig, status):
    rig.poll_result = lambda session: dict(session, status=status)
    with pytest.raises(launcher.LaunchError):
        rig.run()
    assert rig.spawned[0][1].terminated


@pytest.mark.parametrize("field", ["inputs", "outputs", "inplace"])
def test_node_paths_cannot_escape_through_symlinks(project, tmp_path, field):
    external = tmp_path / "outside"
    external.mkdir()
    link = project / "linked"
    try:
        link.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are unavailable on this host")
    (project / "graph.yaml").write_text(
        "params: {chapter_num: 51}\nnodes:\n"
        f"  a: {{kind: agent, {field}: ['linked/chapter-{{chapter_num}}.txt']}}\n",
        encoding="utf-8",
    )
    with pytest.raises(launcher.LaunchError, match="path|outside|escape"):
        launcher.resolve_context(str(project), workspace=tmp_path)
    assert list(external.iterdir()) == []


def test_missing_configured_chapter_uses_existing_graph_default(project, tmp_path):
    (project / "graph.yaml").write_text("nodes:\n  a: {kind: agent}\n", encoding="utf-8")
    assert launcher.resolve_context(str(project), workspace=tmp_path)["chapter"] == 1


def test_ready_arriving_after_deadline_is_not_success(rig):
    rig.services[8766] = rig.health()

    def late(session):
        rig.now += 3
        return dict(session, status="ready")

    rig.poll_result = late
    with pytest.raises(launcher.LaunchError, match="Timed out"):
        rig.run()


def test_transient_get_failure_retries_same_session(rig):
    rig.services[8766] = rig.health()
    polls = []

    def transient(session):
        polls.append(session["launch_id"])
        if len(polls) == 1:
            raise URLError("temporary disconnect")
        return dict(session, status="ready")

    rig.poll_result = transient
    assert rig.run()["status"] == "ready"
    assert polls == ["new-launch-1", "new-launch-1"]
    assert len(rig.sessions) == 1


def test_creation_http_failure_cleans_owned_process(rig):
    rig.creation_result = Mock(side_effect=HTTPError("local", 503, "not ready", {}, None))
    with pytest.raises(launcher.LaunchError, match="503"):
        rig.run()
    assert rig.spawned[0][1].terminated


def test_startup_error_includes_dependency_error_from_cache_log(rig, tmp_path):
    (tmp_path / "server.log").write_text("ModuleNotFoundError: No module named 'fastapi'\n", encoding="utf-8")
    rig.on_spawn = lambda port, process: setattr(process, "returncode", 1)
    with pytest.raises(launcher.LaunchError, match="fastapi"):
        rig.run()


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"null", b"x" * (1024 * 1024 + 1)],
                         ids=["invalid", "array", "null", "oversized"])
def test_http_rejects_malformed_or_oversized_json(monkeypatch, payload):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = payload
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(launcher.urllib.request, "build_opener", lambda *handlers: opener)
    with pytest.raises(launcher.LaunchError):
        launcher.request_json("http://127.0.0.1:8766/api/health")


def test_socket_probe_does_not_enable_shared_bind_and_always_closes(monkeypatch):
    sock = Mock()
    sock.__enter__ = Mock(return_value=sock)
    sock.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(launcher.socket, "socket", lambda *args: sock)
    assert launcher.port_available(8888)
    sock.bind.assert_called_with(("127.0.0.1", 8888))
    assert not any(call.args[1] == launcher.socket.SO_REUSEADDR for call in sock.setsockopt.call_args_list)
    sock.bind.side_effect = OSError("already bound")
    assert not launcher.port_available(8888)
    assert sock.__exit__.call_count == 2
