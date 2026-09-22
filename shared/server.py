# -*- coding: utf-8 -*-
"""Novel Pipeline Studio - FastAPI 本地小说工作流引擎后端服务。

提供：
1. 小说项目与节点图读取/保存/脚手架初始化 (/api/projects, /api/graph, /api/graph/save, /api/projects/create, /api/projects/add)
2. 节点任务触发与 SSE 实时终端日志流 (/api/node/run, /api/node/logs/{task_id})
3. 正文草稿与审查报告双栏安全读取与保存 (/api/chapter/read, /api/chapter/save)
4. 静态 UI 页面托管与独立启动 (/)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from contextlib import asynccontextmanager, suppress
from urllib.parse import urlsplit
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# 路径计算
STUDIO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = STUDIO_ROOT / "shared"
PROJECTS_DIR = STUDIO_ROOT / "projects"
sys.path.insert(0, str(SHARED_DIR))

import pipeline
import scaffold_novel
import memory_engine
import subagent_registry
from studio_session import StudioScope, ReadySessions, contained_path

studio_scope = StudioScope()
ready_sessions = ReadySessions()
_graph_lock = threading.RLock()


@asynccontextmanager
async def studio_lifespan(application):
    _start_file_watcher()
    worker = asyncio.create_task(_broadcast_worker())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        _stop_file_watcher()


app = FastAPI(title="Novel Pipeline Studio API", version="1.0.0", lifespan=studio_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _allowed_local_request(headers):
    try:
        host = urlsplit('//' + headers.get('host', ''))
        if host.hostname not in ('127.0.0.1', 'localhost', '::1') or host.username or host.password:
            return False
        host.port  # 同时拒绝格式非法的端口。
        origin = headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc != host.netloc:
                return False
        return True
    except ValueError:
        return False


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    if studio_scope.project:
        if not _allowed_local_request(request.headers):
            return JSONResponse(status_code=403, content={'detail': '禁止跨站访问绑定工作台'})
        if request.url.path in ('/api/projects/create', '/api/projects/add', '/api/node/run'):
            return JSONResponse(status_code=403, content={'detail': '本工作台仅供编辑与查看，执行请在主对话确认'})
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

_TASKS: Dict[str, Dict[str, Any]] = {}
CUSTOM_PROJECTS_FILE = SHARED_DIR / "custom_projects.json"


# ---------------------------------------------------------------------------
# WebSocket 实时推送管理器
# ---------------------------------------------------------------------------

class LiveConnectionManager:
    """管理所有 WebSocket 连接，支持广播文件变更通知。"""

    def __init__(self):
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        print(f"[ws] 客户端已连接 (当前 {len(self._connections)} 个)")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        print(f"[ws] 客户端已断开 (当前 {len(self._connections)} 个)")

    async def broadcast(self, message: Dict[str, Any]):
        """向所有连接的客户端广播 JSON 消息。"""
        if not self._connections:
            return
        if studio_scope.project:
            if Path(message.get('path', '')).resolve() != studio_scope.project.resolve():
                return
            if message.get('workflow') not in (None, studio_scope.workflow):
                return
        data = json.dumps(message, ensure_ascii=False)
        dead: List[WebSocket] = []
        async with self._lock:
            for ws in self._connections:
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._connections.remove(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


live_manager = LiveConnectionManager()
_broadcast_loop: Optional[asyncio.AbstractEventLoop] = None
_pending_changes: queue.Queue = queue.Queue()


class _ProjectFileWatcher(FileSystemEventHandler):
    """只发送分类通知；监听器从不写状态文件。"""

    _DEBOUNCE_SEC = 0.5

    def __init__(self):
        super().__init__()
        self._debounce_timers = {}
        self._lock = threading.Lock()
        self._closed = False

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    on_created = on_modified
    on_deleted = on_modified

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.src_path)
            self._handle(event.dest_path)

    def close(self):
        with self._lock:
            self._closed = True
            for timer in self._debounce_timers.values():
                timer.cancel()
            self._debounce_timers.clear()

    def _handle(self, src_path: str):
        p = Path(src_path).resolve()
        if any(part.startswith(('.', '~')) or part == '__pycache__' for part in p.parts):
            return
        if p.suffix not in ('.md', '.json', '.yaml', '.yml'):
            return
        project_dir = None
        if studio_scope.project:
            try:
                p.relative_to(studio_scope.project.resolve())
            except ValueError:
                return
            project_dir = studio_scope.project.resolve()
        else:
            for parent in p.parents:
                if (parent / 'graph.yaml').is_file() or (parent / 'volume_graph.yaml').is_file():
                    project_dir = parent
                    break
        if project_dir is None:
            return
        is_graph = p.parent == project_dir and p.suffix in ('.yaml', '.yml')
        workflow = p.name if is_graph else None
        if p.parent == project_dir and p.name in ('pipeline.json', 'volume_pipeline.json'):
            workflow = 'volume_graph.yaml' if p.name == 'volume_pipeline.json' else 'graph.yaml'
        if studio_scope.project and workflow and workflow != studio_scope.workflow:
            return
        event_type = 'graph-changed' if is_graph else 'status-changed'
        message = dict(type=event_type, file=p.name, project=project_dir.name,
                       path=project_dir.as_posix(), workflow=workflow,
                       timestamp=time.time())
        key = (project_dir, workflow, event_type)
        with self._lock:
            if self._closed:
                return
            if key in self._debounce_timers:
                self._debounce_timers[key].cancel()

            def fire():
                with self._lock:
                    if not self._closed and self._debounce_timers.get(key) is timer:
                        self._debounce_timers.pop(key, None)
                        _pending_changes.put(message)

            timer = threading.Timer(self._DEBOUNCE_SEC, fire)
            timer.daemon = True
            self._debounce_timers[key] = timer
            timer.start()


_file_observer: Optional[Observer] = None
_file_handler: Optional[_ProjectFileWatcher] = None


def _start_file_watcher():
    global _file_observer, _file_handler
    if _file_observer is not None:
        return
    _file_observer = Observer()
    _file_handler = _ProjectFileWatcher()
    roots = ([studio_scope.project] if studio_scope.project else
             [PROJECTS_DIR] + [Path(p) for p in load_custom_projects()])
    for root in set(p.resolve() for p in roots if p.is_dir()):
        _file_observer.schedule(_file_handler, str(root), recursive=True)
    _file_observer.daemon = True
    _file_observer.start()


def _stop_file_watcher():
    global _file_observer, _file_handler
    if _file_handler is not None:
        _file_handler.close()
        _file_handler = None
    if _file_observer is not None:
        _file_observer.stop()
        _file_observer.join(timeout=5)
        _file_observer = None


async def _broadcast_worker():
    """后台协程：从队列中取出文件变更事件并广播给所有 WebSocket 客户端。"""
    while True:
        try:
            msg = await asyncio.to_thread(_pending_changes.get, timeout=0.3)
            await live_manager.broadcast(msg)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[ws-broadcast] 广播异常: {e}")
        await asyncio.sleep(0.05)


@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """WebSocket 实时通道：客户端连接后自动接收文件变更通知。"""
    if studio_scope.project and not _allowed_local_request(ws.headers):
        await ws.close(code=1008)
        return
    await live_manager.connect(ws)
    try:
        # 发送初始欢迎消息
        await ws.send_text(json.dumps({
            "type": "connected",
            "message": "笔心 Studio 实时通道已建立",
            "timestamp": time.time(),
        }, ensure_ascii=False))
        # 保持连接，等待客户端消息（心跳/关闭）
        while True:
            data = await ws.receive_text()
            # 客户端可发送 ping 心跳
            if data == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await live_manager.disconnect(ws)


def load_custom_projects() -> List[str]:
    if CUSTOM_PROJECTS_FILE.exists():
        try:
            with open(CUSTOM_PROJECTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def save_custom_projects(paths: List[str]):
    try:
        with open(CUSTOM_PROJECTS_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(set(paths))), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[warning] 保存 custom_projects 失败: {e}")


def find_project_dir(project_slug: str) -> Path:
    """按 slug 或路径定位小说项目目录，兼容绝对路径、'projects/xxx' 或直接 slug。"""
    if studio_scope.project:
        bound = studio_scope.project.resolve()
        candidates = [Path(project_slug), STUDIO_ROOT / project_slug, PROJECTS_DIR / project_slug]
        if project_slug == bound.name or any(p.resolve() == bound for p in candidates):
            return bound
        raise HTTPException(status_code=403, detail='此工作台只允许访问绑定小说')
    p = Path(project_slug)
    if p.is_dir():
        return p.resolve()

    cand1 = STUDIO_ROOT / project_slug
    if cand1.is_dir():
        return cand1.resolve()

    cand2 = PROJECTS_DIR / project_slug
    if cand2.is_dir():
        return cand2.resolve()

    for custom_path in load_custom_projects():
        cp = Path(custom_path)
        if cp.is_dir() and (cp.name == project_slug or str(cp.resolve()).replace("\\", "/").lower() == project_slug.replace("\\", "/").lower()):
            return cp.resolve()

    raise HTTPException(status_code=404, detail=f"未找到小说项目目录: {project_slug}")


def _safe_path(root: Path, value: str) -> Path:
    try:
        return contained_path(root, value)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=403, detail='禁止跨越项目目录')


def _validate_tree(root: Path, value: str):
    """跟随合法内部目录链接，同时逐层验证最终目标，避免嵌套链接漏检。"""
    pending = [_safe_path(root, value)]
    visited = set()
    while pending:
        target = _safe_path(root, str(pending.pop()))
        if target in visited:
            continue
        visited.add(target)
        if target.is_dir():
            pending.extend(target.iterdir())


def _workflow_path(root: Path, workflow: Optional[str]) -> Path:
    name = workflow or 'graph.yaml'
    if ('/' in name or '\\' in name or ':' in name or
            Path(name).suffix not in ('.yaml', '.yml')):
        raise HTTPException(status_code=403, detail='工作流必须是项目根目录 YAML 文件名')
    if studio_scope.project and name != studio_scope.workflow:
        raise HTTPException(status_code=403, detail='此工作台只允许访问绑定工作流')
    _safe_path(root, name)
    # 物理路径只用于包含校验；工作流名决定对应的 pipeline 状态身份。
    return root / name


def _chapter_override(chapter):
    if studio_scope.project:
        if chapter is not None and chapter != studio_scope.chapter:
            raise HTTPException(status_code=403, detail='此工作台只允许访问绑定章节')
        chapter = studio_scope.chapter
    return {'chapter_num': chapter} if chapter is not None else None


def _validate_graph_paths(graph, root):
    for node in graph['nodes'].values():
        for field in ('inputs', 'outputs', 'inplace'):
            for path in node.get(field) or []:
                _validate_tree(root, pipeline._expand_params(path, graph['params']))
    # 质量规则会额外读取设定，不能只检查节点显式输入。
    _validate_tree(root, '设定')


def _graph_snapshot(root, workflow, chapter=None):
    """一次读取对应一个 revision；推导状态不落盘，也不重建人工确认基线。"""
    path = _workflow_path(root, workflow)
    override = _chapter_override(chapter)
    try:
        raw = path.read_bytes()
        graph = pipeline.load_graph(raw.decode('utf-8-sig'), project_root=root, override_params=override)
        _validate_graph_paths(graph, root)
        _safe_path(root, pipeline.state_filename_for(path.name))
        old = pipeline.load_state(root, graph_file=path.name)
        state = pipeline.derive_status(graph, root, old)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail='工作流文件不存在')
    except (pipeline.ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail=f'工作流无效: {exc}')
    return graph, state, 'sha256:' + hashlib.sha256(raw).hexdigest()


def _session_snapshot():
    if not studio_scope.project:
        raise HTTPException(status_code=409, detail='渲染会话需要单项目工作台')
    _, _, revision = _graph_snapshot(studio_scope.project, studio_scope.workflow)
    return revision, dict(project=studio_scope.project.name,
                          project_path=str(studio_scope.project.resolve()),
                          workflow=studio_scope.workflow, chapter=studio_scope.chapter)


@app.get('/api/health')
def health():
    return dict(status='ok', service='novel-pipeline-studio', workspace=str(STUDIO_ROOT.resolve()),
                studio_protocol=1, bound_project=studio_scope.project.name if studio_scope.project else None,
                project_path=str(studio_scope.project.resolve()) if studio_scope.project else None,
                workflow=studio_scope.workflow, chapter=studio_scope.chapter)


@app.post('/api/ui/session')
def create_ui_session():
    revision, context = _session_snapshot()
    return ready_sessions.create(revision, context)


@app.get('/api/ui/session/{launch_id}')
def get_ui_session(launch_id: str):
    revision, _ = _session_snapshot()
    try:
        return ready_sessions.get(launch_id, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail='渲染会话不存在或已过期')


class ReadyRequest(BaseModel):
    launch_id: str
    revision: str


@app.post('/api/ui/ready')
def acknowledge_ui_ready(req: ReadyRequest):
    revision, _ = _session_snapshot()
    try:
        return ready_sessions.ack(req.launch_id, req.revision, revision)
    except KeyError:
        raise HTTPException(status_code=404, detail='渲染会话不存在或已过期')
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/projects")
def list_projects():
    """扫描项目目录并返回所有识别到的小说课题。"""
    discovered: Dict[str, Dict[str, Any]] = {}

    def inspect_dir(target_dir: Path):
        if not target_dir.is_dir() or target_dir.name.startswith((".", "_")):
            return
        has_graph = (target_dir / "graph.yaml").exists()
        has_outline = (target_dir / "outline.md").exists()
        has_world = (target_dir / "world.md").exists()
        if has_graph or has_outline or has_world:
            slug = target_dir.name
            discovered[slug] = {
                "slug": slug,
                "name": target_dir.name,
                "path": str(target_dir.resolve()).replace("\\", "/"),
                "hasGraph": has_graph,
                "hasOutline": has_outline,
            }

    if studio_scope.project:
        inspect_dir(studio_scope.project)
        return {'projects': list(discovered.values())}

    if PROJECTS_DIR.is_dir():
        for child in PROJECTS_DIR.iterdir():
            inspect_dir(child)

    for custom_path in load_custom_projects():
        cp = Path(custom_path)
        if cp.is_dir():
            inspect_dir(cp)

    return {"projects": sorted(list(discovered.values()), key=lambda x: x["slug"])}


class CreateProjectRequest(BaseModel):
    slug: str
    title: str = "未命名小说"
    genre: str = "科幻悬疑"
    protagonist: str = "林巡"
    logline: str = "这是一段故事核心悬念..."


@app.post("/api/projects/create")
def create_project(req: CreateProjectRequest):
    """脚手架创建新小说项目。"""
    slug = req.slug.strip().replace(" ", "-").lower()
    if not slug:
        raise HTTPException(status_code=400, detail="slug 不能为空")

    target_dir = PROJECTS_DIR / slug
    if target_dir.exists():
        raise HTTPException(status_code=400, detail=f"项目 [{slug}] 已存在")

    scaffold_novel.scaffold_novel(target_dir, req.title, req.genre, req.protagonist, req.logline)
    # 自动推导一次初始状态
    try:
        pipeline.cmd_status(str(target_dir))
    except Exception:
        pass

    return {"success": True, "slug": slug, "path": str(target_dir.resolve())}


class AddPathRequest(BaseModel):
    path: str


@app.post("/api/projects/add")
def add_custom_path(req: AddPathRequest):
    raw = req.path.strip()
    p = Path(raw)
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"该目录不存在: {raw}")
    norm = str(p.resolve()).replace("\\", "/")
    customs = load_custom_projects()
    if norm not in customs:
        customs.append(norm)
        save_custom_projects(customs)
    return {"success": True, "path": norm}


@app.get("/api/workflows")
def list_workflows(project: str = Query(...)):
    """扫描项目内的所有可用工作流定义文件（如 graph.yaml、volume_graph.yaml）。"""
    pdir = find_project_dir(project)
    workflows = []
    workflow_meta = {
        "graph.yaml": {
            "id": "graph.yaml",
            "name": "单章正文流水线",
            "icon": "📄",
            "desc": "单章细纲、节拍、初稿、润色、多维审计与入库流水线",
        },
        "volume_graph.yaml": {
            "id": "volume_graph.yaml",
            "name": "分卷大纲创世纪",
            "icon": "🗺️",
            "desc": "分卷立意、物理法则、势力暗算盘、反转阶梯与伏笔总账",
        },
    }

    for candidate, meta in workflow_meta.items():
        if (pdir / candidate).is_file():
            workflows.append(meta)

    for yf in sorted(pdir.glob("*.yaml")):
        fname = yf.name
        if fname not in workflow_meta:
            workflows.append({
                "id": fname,
                "name": fname.replace(".yaml", "").replace("_", " ").title(),
                "icon": "⚙️",
                "desc": f"自定义工作流: {fname}",
            })

    if studio_scope.project:
        workflows = [w for w in workflows if w['id'] == studio_scope.workflow]
    return {"project": project, "workflows": workflows}


def _read_graph_response(project, workflow, chapter, include_graph=True):
    pdir = find_project_dir(project)
    path = _workflow_path(pdir, workflow)
    _chapter_override(chapter)
    if not path.is_file() and not studio_scope.project:
        return dict(project=project, workflow=path.name, hasGraph=False, graph=None, state=None)
    with _graph_lock:
        graph, state, revision = _graph_snapshot(pdir, workflow, chapter)
    response = dict(project=project, workflow=path.name, state=state, revision=revision,
                    currentChapter=graph['params'].get('chapter_num', 1),
                    currentVolume=graph['params'].get('volume_num', 1),
                    host=subagent_registry.detect_host().get('host'))
    if include_graph:
        # 引擎推导附加的内部参数不是用户配置，不送回编辑器保存。
        for node in graph['nodes'].values():
            node.pop('_params', None)
        response.update(hasGraph=True, graph=graph)
    return response


@app.get('/api/graph')
def get_graph(project: str = Query(...), chapter: Optional[int] = Query(None),
              workflow: Optional[str] = Query('graph.yaml')):
    return _read_graph_response(project, workflow, chapter)


@app.get('/api/state')
def get_state(project: str = Query(...), chapter: Optional[int] = Query(None),
              workflow: Optional[str] = Query('graph.yaml')):
    return _read_graph_response(project, workflow, chapter, include_graph=False)


@app.get("/api/chapters")
def list_chapters(project: str = Query(...)):
    """扫描项目内所有已规划或已有工作区的章节列表。"""
    pdir = find_project_dir(project)
    chapters_found = set()
    for directory in ('工作区', '正文', 'chapters'):
        _validate_tree(pdir, directory)

    # 1. 扫描 工作区/第xx章
    workspace_dir = pdir / "工作区"
    if workspace_dir.is_dir():
        for sub in workspace_dir.iterdir():
            if sub.is_dir():
                m = re.search(r"第?(\d+)章?", sub.name)
                if m:
                    chapters_found.add(int(m.group(1)))

    # 2. 扫描 正文/ 深度目录
    for sdir in [pdir / "正文", pdir / "chapters"]:
        if sdir.is_dir():
            for f in sdir.rglob("*.md"):
                m = re.search(r"第?(\d+)章", f.name) or re.search(r"ch_?(\d+)", f.name, re.IGNORECASE)
                if m:
                    chapters_found.add(int(m.group(1)))

    # 3. 扫描 graph.yaml
    gpath = _workflow_path(pdir, studio_scope.workflow if studio_scope.project else 'graph.yaml')
    current_default = studio_scope.chapter or 1
    if gpath.is_file():
        try:
            with open(gpath, "r", encoding="utf-8") as f:
                gdata = yaml.safe_load(f)
                c = (gdata.get("params") or {}).get("chapter_num")
                if c is not None:
                    current_default = int(c)
                    chapters_found.add(current_default)
        except Exception:
            pass

    chapters_found.add(current_default)
    sorted_chapters = sorted(list(chapters_found))

    return {
        "project": project,
        "chapters": sorted_chapters,
        "current": current_default,
    }


@app.get("/api/skills")
def list_skills():
    """扫描系统全局小说技能库，返回技能列表及元数据。"""
    skills_dir = STUDIO_ROOT / "skills"
    results = []
    if not skills_dir.is_dir():
        return {"skills": []}

    for skill_path in sorted(skills_dir.iterdir(), key=lambda p: p.name):
        if not skill_path.is_dir():
            continue
        skill_file = skill_path / "SKILL.md"
        if not skill_file.is_file():
            continue

        item = {
            "id": skill_path.name,
            "name": skill_path.name,
            "description": "",
            "category": "通用技能",
        }

        try:
            content = skill_file.read_text(encoding="utf-8", errors="replace")
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm_text = parts[1]
                    fm = yaml.safe_load(fm_text)
                    if isinstance(fm, dict):
                        item["name"] = fm.get("name") or skill_path.name
                        item["description"] = (fm.get("description") or "").strip()
                        item["category"] = fm.get("category") or "通用技能"
        except Exception as e:
            item["description"] = f"解析异常: {e}"

        results.append(item)

    return {"skills": results}


def _memory_for_project(pdir):
    _validate_tree(pdir, '设定')
    return memory_engine.MemoryEngine(pdir, create_dirs=False)


@app.get("/api/memory")
def get_project_memory(project: str = Query(...)):
    """获取指定小说项目的 15 维实时事实快照。"""
    pdir = find_project_dir(project)
    engine = _memory_for_project(pdir)
    snapshot = engine.load_snapshot()
    return {
        "project": project,
        "snapshot": snapshot.to_dict(),
        "ledgerFile": str(engine.ledger_file).replace("\\", "/"),
    }


class ApplyChangesRequest(BaseModel):
    project: str
    chapter_num: int
    changes: Dict[str, Any]
    chapter_summary: str = ""
    ending_text: str = ""


@app.post("/api/memory/apply")
def apply_project_memory(req: ApplyChangesRequest):
    """回写章节 CHANGES 变更声明至全局事实账本。"""
    pdir = find_project_dir(req.project)
    _chapter_override(req.chapter_num)
    engine = _memory_for_project(pdir)
    updated_snap, issues = engine.apply_changes(
        changes=req.changes,
        chapter_num=req.chapter_num,
        chapter_summary=req.chapter_summary,
        ending_text=req.ending_text,
    )
    return {
        "status": "ok",
        "chapter_num": req.chapter_num,
        "issues": issues,
        "snapshot": updated_snap.to_dict(),
    }


class SaveGraphRequest(BaseModel):
    project: str
    graph: Dict[str, Any]
    workflow: Optional[str] = 'graph.yaml'
    revision: Optional[str] = None


@app.post('/api/graph/save')
def save_graph(req: SaveGraphRequest):
    """先校验再原子替换；乐观版本锁避免覆盖宿主刚更新的图。"""
    pdir = find_project_dir(req.project)
    graph_path = _workflow_path(pdir, req.workflow)
    temp_path = None
    with _graph_lock:
        try:
            yaml_content = yaml.safe_dump(req.graph, allow_unicode=True, sort_keys=False)
            graph = pipeline.load_graph(yaml_content, project_root=pdir,
                                        override_params=_chapter_override(None))
            _validate_graph_paths(graph, pdir)
            if studio_scope.project and req.graph.get('params', {}).get('chapter_num', studio_scope.chapter) != studio_scope.chapter:
                raise HTTPException(status_code=403, detail='不能在绑定工作台修改目标章节')
            previous = graph_path.read_bytes() if graph_path.exists() else b''
            revision = 'sha256:' + hashlib.sha256(previous).hexdigest()
            if req.revision is not None and req.revision != revision:
                raise HTTPException(status_code=409, detail='配置已被其他操作更新，请保留草稿并重新加载')
            _safe_path(pdir, pipeline.state_filename_for(graph_path.name))
            state = pipeline.derive_status(graph, pdir, pipeline.load_state(pdir, graph_file=graph_path.name))
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=pdir,
                                             prefix='.studio-', suffix='.tmp', delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(yaml_content)
            # 同进程请求由锁串行，外部编辑也在替换前重新检查一次。
            if (graph_path.read_bytes() if graph_path.exists() else b'') != previous:
                raise HTTPException(status_code=409, detail='配置在保存时变化，请重新加载')
            os.replace(temp_path, graph_path)
            revision = 'sha256:' + hashlib.sha256(graph_path.read_bytes()).hexdigest()
            return dict(success=True, state=state, revision=revision)
        except HTTPException:
            raise
        except (pipeline.ValidationError, ValueError, TypeError, OSError) as exc:
            raise HTTPException(status_code=400, detail=f'保存失败: {exc}')
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


class NodeStatusRequest(BaseModel):
    project: str
    node_id: str
    chapter: Optional[int] = None
    workflow: Optional[str] = "graph.yaml"


@app.post("/api/node/start")
def start_node(req: NodeStatusRequest):
    """供外部智能体/系统显式标记某节点正在执行中，触发 WebUI 画布秒级点亮。"""
    pdir = find_project_dir(req.project)
    override = _chapter_override(req.chapter)
    graph_file = _workflow_path(pdir, req.workflow).name
    _graph_snapshot(pdir, graph_file, req.chapter)
    pipeline.cmd_start(req.node_id, str(pdir), override_params=override, graph_file=graph_file)
    return {"status": "ok", "running_node": req.node_id, "workflow": graph_file}


@app.post("/api/node/finish")
def finish_node(req: NodeStatusRequest):
    """供外部智能体/系统显式标记某节点执行结束，恢复/更新为最新物理状态。"""
    pdir = find_project_dir(req.project)
    override = _chapter_override(req.chapter)
    graph_file = _workflow_path(pdir, req.workflow).name
    _graph_snapshot(pdir, graph_file, req.chapter)
    pipeline.cmd_finish(req.node_id, str(pdir), override_params=override, graph_file=graph_file)
    return {"status": "ok", "finished_node": req.node_id, "workflow": graph_file}


class RunNodeRequest(BaseModel):
    project: str
    node_id: Optional[str] = None
    action: str = "run_node"  # "run_node" | "run_all_stale" | "reconcile"
    chapter: Optional[int] = None
    workflow: Optional[str] = "graph.yaml"


@app.post("/api/node/run")
def run_node(req: RunNodeRequest):
    """异步执行节点任务或派发 Agent 任务，并返回 taskId。"""
    pdir = find_project_dir(req.project)
    task_id = str(uuid.uuid4())[:8]
    graph_file = req.workflow or "graph.yaml"

    log_q: queue.Queue = queue.Queue()
    _TASKS[task_id] = {
        "id": task_id,
        "project": req.project,
        "node_id": req.node_id,
        "action": req.action,
        "chapter": req.chapter,
        "workflow": graph_file,
        "status": "running",
        "started_at": time.time(),
        "queue": log_q,
    }

    def _worker():
        try:
            ch_str = f", chapter={req.chapter}" if req.chapter is not None else ""
            wf_str = f", workflow={graph_file}"
            log_q.put(f"[studio] 开始执行: {req.action} (node={req.node_id}, project={req.project}{ch_str}{wf_str})\n")

            if req.action == "run_node" and req.node_id:
                try:
                    pipeline.cmd_start(req.node_id, str(pdir),
                                       override_params={"chapter_num": req.chapter} if req.chapter is not None else None,
                                       graph_file=graph_file)
                except Exception:
                    pass

            if req.action == "reconcile":
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "reconcile", "--project", str(pdir), "--graph", graph_file]
            elif req.action == "run_node" and req.node_id:
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "run", req.node_id, "--project", str(pdir), "--graph", graph_file]
            else:
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "status", "--project", str(pdir), "--graph", graph_file]

            if req.chapter is not None:
                cmd.extend(["--chapter", str(req.chapter)])

            log_q.put(f"[cmd] {' '.join(cmd)}\n")
            proc = subprocess.Popen(
                cmd,
                cwd=str(STUDIO_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            for line in iter(proc.stdout.readline, ""):
                log_q.put(line)

            proc.stdout.close()
            proc.wait()
            _TASKS[task_id]["exit_code"] = proc.returncode
            _TASKS[task_id]["status"] = "finished" if proc.returncode in (0, 2) else "failed"
            log_q.put(f"\n[studio] 任务结束，返回码: {proc.returncode}\n")

            if req.action == "run_node" and req.node_id:
                try:
                    pipeline.cmd_finish(req.node_id, str(pdir),
                                        override_params={"chapter_num": req.chapter} if req.chapter is not None else None,
                                        graph_file=graph_file)
                except Exception:
                    pass
            else:
                try:
                    pipeline.cmd_status(str(pdir), graph_file=graph_file)
                except Exception:
                    pass

        except Exception as ex:
            log_q.put(f"\n[error] 发生异常: {str(ex)}\n")
            if req.action == "run_node" and req.node_id:
                try:
                    pipeline.cmd_finish(req.node_id, str(pdir), graph_file=graph_file)
                except Exception:
                    pass
            _TASKS[task_id]["status"] = "failed"
        finally:
            log_q.put(None)  # 结束标记

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    return {"taskId": task_id, "status": "running"}


@app.get("/api/node/logs/{task_id}")
async def stream_logs(task_id: str):
    """Server-Sent Events 实时推流日志。"""
    if task_id not in _TASKS:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = _TASKS[task_id]
    pdir = find_project_dir(task['project'])
    _workflow_path(pdir, task.get('workflow'))
    _chapter_override(task.get('chapter'))
    log_q = task["queue"]

    async def event_generator():
        while True:
            try:
                line = await asyncio.to_thread(log_q.get, timeout=0.2)
                if line is None:
                    yield f"data: {json.dumps({'type': 'end', 'status': task.get('status')})}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
            except queue.Empty:
                if task.get("status") in ("finished", "failed") and log_q.empty():
                    yield f"data: {json.dumps({'type': 'end', 'status': task.get('status')})}\n\n"
                    break
                await asyncio.sleep(0.1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/chapter/read")
def read_chapter_file(project: str = Query(...), file: str = Query(...)):
    """安全读取项目内的正文、草稿或报告文件。"""
    pdir = find_project_dir(project)
    target = _safe_path(pdir, file)

    if not target.is_file():
        return {"exists": False, "file": file, "content": ""}

    return {"exists": True, "file": file, "content": target.read_text(encoding="utf-8", errors="replace")}


class SaveFileRequest(BaseModel):
    project: str
    file: str
    content: str


@app.post("/api/chapter/save")
def save_chapter_file(req: SaveFileRequest):
    """保存正文或草稿；状态由后续只读查询推导。"""
    pdir = find_project_dir(req.project)
    target = _safe_path(pdir, req.file)
    # 配置和状态必须走各自的校验接口，不允许通过正文接口旁路覆盖。
    if target.suffix.lower() != '.md':
        raise HTTPException(status_code=403, detail='正文编辑接口只允许 Markdown 文件')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding='utf-8')
    return {"success": True, "message": f"{req.file} 已成功保存"}


# 静态文件托管
UI_DIR = SHARED_DIR / "ui"
if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def configure_scope(project=None, workflow='graph.yaml', chapter=None):
    global studio_scope, ready_sessions
    if project:
        from launch_studio import resolve_context
        context = resolve_context(project, workflow, chapter, workspace=STUDIO_ROOT)
        studio_scope = StudioScope(Path(context['project_path']), context['workflow'], context['chapter'])
    else:
        studio_scope = StudioScope()
    ready_sessions = ReadySessions()


def main():
    _reconfigure_stdio()
    import argparse
    parser = argparse.ArgumentParser(description='Novel Pipeline Studio Server')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址')
    parser.add_argument('--port', type=int, default=8766, help='监听端口 (默认 8766)')
    parser.add_argument('--project', help='仅绑定此小说目录；省略时兼容旧的多项目模式')
    parser.add_argument('--workflow', default='graph.yaml')
    parser.add_argument('--chapter', type=int)
    args = parser.parse_args()
    if args.project and args.host not in ('127.0.0.1', 'localhost', '::1'):
        parser.error('绑定工作台只允许监听回环地址')
    try:
        configure_scope(args.project, args.workflow, args.chapter)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))

    print(f"[server] Novel Pipeline Studio started: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
