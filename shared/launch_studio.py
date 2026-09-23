# -*- coding: utf-8 -*-
"""Open a bound studio and wait for this launch's browser render receipt.

UI readiness is not permission to run a workflow. This module never runs nodes
or reconciles pipeline state; pipeline.load_graph is used only for validation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.client import HTTPException
from pathlib import Path
from typing import Any, Optional

SERVICE = "novel-pipeline-studio"
STUDIO_PROTOCOL = 1
WORKSPACE = Path(__file__).resolve().parent.parent


def _canonical_absolute(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value or "\0" in value:
        return None
    try:
        path = Path(value)
        if not path.is_absolute():
            return None
        return os.path.normcase(str(path.resolve()))
    except (OSError, RuntimeError, ValueError):
        return None


def matches_service(data: Any, expected: dict) -> bool:
    """Do not confuse a slug, an unbound server, or another workspace with ours."""
    required = {"status", "service", "workspace", "studio_protocol",
                "bound_project", "project_path", "workflow", "chapter"}
    if not isinstance(data, dict) or not required.issubset(data):
        return False
    if (data["status"] != "ok" or data["service"] != SERVICE
            or type(data["studio_protocol"]) is not int
            or data["studio_protocol"] != STUDIO_PROTOCOL
            or expected.get("studio_protocol", STUDIO_PROTOCOL) != STUDIO_PROTOCOL):
        return False
    for field in ("workspace", "project_path"):
        target = _canonical_absolute(expected.get(field))
        if target is None or _canonical_absolute(data[field]) != target:
            return False
    project = expected.get("bound_project", Path(expected["project_path"]).name)
    if not project or data["bound_project"] != project:
        return False
    if not expected.get("workflow") or data["workflow"] != expected["workflow"]:
        return False
    if "chapter" not in expected:
        return False
    chapter = data["chapter"]
    return (chapter is None or type(chapter) is int) and (
        type(chapter) is type(expected["chapter"]) and chapter == expected["chapter"]
    )


class LaunchError(Exception):
    """An actionable launch error, not workflow execution permission."""


def resolve_context(project: str, workflow: str = "graph.yaml",
                    chapter: Optional[int] = None, *, workspace: Optional[Path] = None) -> dict:
    """Resolve an existing project and validate its graph without touching state."""
    root = Path(workspace or WORKSPACE).resolve()
    if (not workflow or "/" in workflow or "\\" in workflow
            or Path(workflow).suffix.lower() not in {".yaml", ".yml"}
            or Path(workflow).is_absolute() or ":" in workflow):
        raise LaunchError("Workflow must be a project-root YAML filename")
    candidates = [Path(project).expanduser(), root / project, root / "projects" / project]
    registry = root / "shared" / "custom_projects.json"
    if registry.is_file():
        try:
            registered = json.loads(registry.read_text(encoding="utf-8"))
            if isinstance(registered, list):
                candidates.extend(Path(p) for p in registered
                                  if isinstance(p, str) and Path(p).name == project)
        except (OSError, ValueError):
            pass  # Explicit paths remain usable with a damaged optional registry.
    pdir = next((p.resolve() for p in candidates if p.is_dir()), None)
    if pdir is None:
        raise LaunchError(f"Project directory not found: {project}")
    graph_path = pdir / workflow
    try:
        graph_path.resolve().relative_to(pdir)
        text = graph_path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError, RuntimeError) as exc:
        raise LaunchError(f"Cannot read workflow {graph_path}: {exc}") from exc
    try:
        import pipeline
    except ImportError as exc:
        raise LaunchError(f"Graph validation dependency missing: {exc}") from exc
    try:
        import yaml
        source = yaml.safe_load(text)
        if isinstance(source, dict) and source.get('kind') == 'production':
            import production
            if chapter is not None:
                raise ValueError('生产任务启动外层概览，不使用 --chapter；在工作台内选择章节')
            production.validate_document(source, pdir)
            return {
                "workspace": str(root), "bound_project": pdir.name, "project_path": str(pdir),
                "workflow": workflow, "chapter": None, "studio_protocol": STUDIO_PROTOCOL,
            }
        graph = pipeline.load_graph(text, project_root=pdir,
                                    override_params={"chapter_num": chapter} if chapter is not None else None)
    except (pipeline.ValidationError, ValueError, TypeError, RecursionError, yaml.YAMLError) as exc:
        raise LaunchError(f"Invalid workflow {graph_path}: {exc}") from exc
    # load_graph rejects lexical traversal; also check physical symlink targets.
    for node in graph["nodes"].values():
        for field in ("inputs", "outputs", "inplace"):
            for item in node.get(field) or []:
                if isinstance(item, str):
                    try:
                        expanded = pipeline._expand_params(item, graph["params"])
                        (pdir / expanded).resolve().relative_to(pdir)
                    except (OSError, ValueError, RuntimeError) as exc:
                        raise LaunchError(f"Node path escapes project: {item}") from exc
    actual_chapter = graph["params"].get("chapter_num", 1)
    if actual_chapter is not None and type(actual_chapter) is not int:
        raise LaunchError("Graph chapter_num must normalize to an integer")
    return {
        "workspace": str(root), "bound_project": pdir.name, "project_path": str(pdir),
        "workflow": workflow, "chapter": actual_chapter, "studio_protocol": STUDIO_PROTOCOL,
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never turn a loopback identity probe into a remote request.


def request_json(url: str, *, method: str = "GET", timeout: float = 1.0) -> dict:
    """Only loopback HTTP, no environment proxies, redirects, or POST body."""
    request = urllib.request.Request(url, method=method, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise LaunchError("Service JSON response is too large")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise LaunchError(f"Invalid JSON from {url}") from exc
    if not isinstance(data, dict):
        raise LaunchError(f"Expected a JSON object from {url}")
    return data


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def spawn_server(context: dict, port: int):
    """Own only this Popen handle; logs never go in the novel directory."""
    log_dir = Path(context["workspace"]) / "shared" / "__pycache__" / "studio-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", str(WORKSPACE / "shared" / "server.py"),
               "--host", "127.0.0.1", "--port", str(port),
               "--project", context["project_path"], "--workflow", context["workflow"]]
    if context["chapter"] is not None:
        command.extend(["--chapter", str(context["chapter"])])
    options = {"cwd": str(WORKSPACE), "stdin": subprocess.DEVNULL,
               "stderr": subprocess.STDOUT, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True
    with tempfile.NamedTemporaryFile(mode="wb", prefix=f"studio-{port}-", suffix=".log",
                                     dir=log_dir, delete=False) as log:
        process = subprocess.Popen(command, stdout=log, **options)
        return process, Path(log.name)


def _stop_owned(process) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Could not finish cleaning up the launched server: {exc}", file=sys.stderr)


def _remaining(deadline: float, cap: float = 1.0) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LaunchError("Timed out waiting for this launch's studio/UI readiness")
    return min(remaining, cap)


def _pause(deadline: float) -> None:
    time.sleep(_remaining(deadline, 0.1))


def _probe(base: str, deadline: float):
    timeout = _remaining(deadline, 0.25)
    try:
        return request_json(base + "/api/health", timeout=timeout)
    except (OSError, HTTPException, LaunchError):
        return None


def _validate_session(data: Any, context: dict, original: Optional[dict] = None) -> None:
    required = {"launch_id", "revision", "project", "project_path", "workflow", "chapter", "status"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise LaunchError("Invalid UI session response")
    identity = dict(data, status="ok", service=SERVICE, workspace=context["workspace"],
                    studio_protocol=STUDIO_PROTOCOL, bound_project=data["project"])
    if not matches_service(identity, context):
        raise LaunchError("UI session identity does not match the requested project/workflow/chapter")
    if (not isinstance(data["launch_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+", data["launch_id"])
            or not isinstance(data["revision"], str) or not data["revision"].strip()):
        raise LaunchError("UI session must contain a launch_id and revision")
    if original is None:
        if data["status"] != "pending":
            raise LaunchError("A new UI session must be pending; an old ready receipt cannot be reused")
    elif (data["launch_id"] != original["launch_id"] or data["revision"] != original["revision"]
          or data["status"] not in ("pending", "ready")):
        raise LaunchError("Stale or invalid UI receipt: launch_id/revision/status mismatch")


def _check_child(process) -> None:
    if process is not None and process.poll() is not None:
        raise LaunchError(f"Launched server exited unexpectedly (exit code {process.returncode})")


def _log_detail(log_path: Optional[Path]) -> str:
    if log_path is None:
        return ""
    detail = f"\nServer log: {log_path}"
    try:
        with log_path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 4096))
            detail += "\n" + stream.read().decode("utf-8", errors="replace").strip()
    except OSError:
        pass
    return detail


def launch(context: dict, *, port: int = 8766, timeout: float = 120,
           no_open: bool = False) -> dict:
    """Scan first, then launch if needed, and wait for one fresh render receipt."""
    if type(port) is not int or not 1 <= port <= 65516:
        raise LaunchError("Starting port must be between 1 and 65516 (20-port scan)")
    if not math.isfinite(timeout) or timeout <= 0:
        raise LaunchError("Timeout must be a positive finite number")
    deadline = time.monotonic() + timeout
    ports = range(port, port + 20)
    owned = None
    log_path = None
    succeeded = False
    base = None
    reused = True
    try:
        # A later matching instance wins over every earlier vacant port.
        for candidate in ports:
            address = f"http://127.0.0.1:{candidate}"
            if matches_service(_probe(address, deadline), context):
                base = address
                break
        if base is None:
            for candidate in ports:
                _remaining(deadline)
                address = f"http://127.0.0.1:{candidate}"
                if not port_available(candidate):
                    if matches_service(_probe(address, deadline), context):
                        base = address
                        reused = True
                        break
                    continue
                owned, log_path = spawn_server(context, candidate)
                while True:
                    health = _probe(address, deadline)
                    if matches_service(health, context):
                        reused = owned.poll() is not None
                        if reused:
                            owned = None  # A matching concurrent launcher won the bind.
                        base = address
                        break
                    if health is not None:
                        # A foreign listener won the probe/spawn race; never kill it.
                        _stop_owned(owned)
                        owned = None
                        break
                    if owned.poll() is not None:
                        if not port_available(candidate):
                            owned = None
                            break
                        _check_child(owned)
                    _pause(deadline)
                if base is not None:
                    break
        if base is None:
            raise LaunchError("No matching studio or available port in the 20-port range")
        if not matches_service(_probe(base, deadline), context):
            raise LaunchError("Service identity changed before creating a UI session")
        # 会话接口会验证完整生产快照，不能套用轻量健康探测的一秒上限。
        session = request_json(base + "/api/ui/session", method="POST", timeout=_remaining(deadline, 30.0))
        _validate_session(session, context)
        url = base + "/?" + urllib.parse.urlencode({"launch_id": session["launch_id"]})
        print(url, file=sys.stderr, flush=True)
        if not no_open:
            try:
                opened = webbrowser.open(url)
            except Exception as exc:
                raise LaunchError(f"Browser could not open {url}: {exc}") from exc
            if not opened:
                raise LaunchError(f"Browser refused to open {url}; use --no-open with a host browser")
        while True:
            _check_child(owned)
            request_timeout = _remaining(deadline, 30.0)
            try:
                receipt = request_json(base + "/api/ui/session/" + session["launch_id"],
                                       timeout=request_timeout)
            except urllib.error.HTTPError as exc:
                raise LaunchError(f"UI session rejected (HTTP {exc.code}): {exc.reason}") from exc
            except (OSError, HTTPException):
                _pause(deadline)
                continue
            _remaining(deadline)
            _check_child(owned)
            _validate_session(receipt, context, session)
            if receipt["status"] == "ready":
                if not matches_service(_probe(base, deadline), context):
                    raise LaunchError("Service identity changed before UI readiness")
                _remaining(deadline)
                _check_child(owned)
                succeeded = True
                return dict(context, status="ready", awaiting_confirmation=True, url=url,
                            launch_id=session["launch_id"], revision=session["revision"],
                            project=context["bound_project"], reused=reused)
            _pause(deadline)
    except (LaunchError, OSError, HTTPException) as exc:
        raise LaunchError(str(exc) + _log_detail(log_path)) from exc
    finally:
        if not succeeded:
            _stop_owned(owned)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Open a novel studio; readiness is not execution approval")
    parser.add_argument("--project", required=True, help="Existing project slug or path")
    parser.add_argument("--workflow", default="graph.yaml", help="Project-root workflow YAML")
    parser.add_argument("--chapter", type=int, default=None, help="Defaults to the graph's chapter_num")
    parser.add_argument("--port", type=int, default=8766, help="First of 20 ports (default: 8766)")
    parser.add_argument("--timeout", type=float, default=120, help="Launch/UI deadline in seconds")
    parser.add_argument("--no-open", action="store_true", help="Print URL for a host browser; still wait for UI")
    args = parser.parse_args(argv)
    try:
        context = resolve_context(args.project, args.workflow, args.chapter)
        result = launch(context, port=args.port, timeout=args.timeout, no_open=args.no_open)
    except (LaunchError, OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        message = str(exc) or "Launch interrupted"
        print(message, file=sys.stderr)
        print(json.dumps({"status": "error", "error": message}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    raise SystemExit(main())
