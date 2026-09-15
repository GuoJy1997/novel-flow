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
import json
import os
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
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 路径计算
STUDIO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = STUDIO_ROOT / "shared"
PROJECTS_DIR = STUDIO_ROOT / "projects"
sys.path.insert(0, str(SHARED_DIR))

import pipeline
import scaffold_novel
import memory_engine

app = FastAPI(title="Novel Pipeline Studio API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_TASKS: Dict[str, Dict[str, Any]] = {}
CUSTOM_PROJECTS_FILE = SHARED_DIR / "custom_projects.json"


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


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "novel-pipeline-studio", "workspace": str(STUDIO_ROOT)}


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


@app.get("/api/graph")
def get_graph(project: str = Query(...), chapter: Optional[int] = Query(None)):
    """获取项目的 graph.yaml 与 pipeline.json 状态，支持指定章节。"""
    pdir = find_project_dir(project)
    graph_path = pdir / "graph.yaml"
    if not graph_path.is_file():
        return {"project": project, "hasGraph": False, "graph": None, "state": None}

    override_params = {"chapter_num": chapter} if chapter is not None else None

    # 自动刷新推导状态
    try:
        pipeline.cmd_status(str(pdir), override_params=override_params)
    except Exception as e:
        print(f"[warning] cmd_status: {e}")

    try:
        graph_data = pipeline._load_project_graph(pdir, override_params=override_params)
    except Exception:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_data = yaml.safe_load(f)

    state_data = pipeline.load_state(pdir)
    curr_chapter = (graph_data.get("params") or {}).get("chapter_num", 1)

    return {
        "project": project,
        "hasGraph": True,
        "graph": graph_data,
        "state": state_data,
        "currentChapter": curr_chapter,
    }


@app.get("/api/chapters")
def list_chapters(project: str = Query(...)):
    """扫描项目内所有已规划或已有工作区的章节列表。"""
    pdir = find_project_dir(project)
    chapters_found = set()

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
    gpath = pdir / "graph.yaml"
    current_default = 1
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


@app.get("/api/memory")
def get_project_memory(project: str = Query(...)):
    """获取指定小说项目的 15 维实时事实快照。"""
    pdir = find_project_dir(project)
    engine = memory_engine.MemoryEngine(pdir)
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
    engine = memory_engine.MemoryEngine(pdir)
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


@app.post("/api/graph/save")
def save_graph(req: SaveGraphRequest):
    """保存并原子更新 graph.yaml，随后自动重算状态。"""
    pdir = find_project_dir(req.project)
    graph_path = pdir / "graph.yaml"

    try:
        yaml_content = yaml.dump(req.graph, allow_unicode=True, sort_keys=False)
        temp_path = graph_path.with_suffix(".yaml.tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
        temp_path.replace(graph_path)

        pipeline.cmd_status(str(pdir))
        state_data = pipeline.load_state(pdir)

        return {"success": True, "message": "graph.yaml 已成功保存", "state": state_data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存失败: {str(e)}")


class RunNodeRequest(BaseModel):
    project: str
    node_id: Optional[str] = None
    action: str = "run_node"  # "run_node" | "run_all_stale" | "reconcile"
    chapter: Optional[int] = None


@app.post("/api/node/run")
def run_node(req: RunNodeRequest):
    """异步执行节点任务或派发 Agent 任务，并返回 taskId。"""
    pdir = find_project_dir(req.project)
    task_id = str(uuid.uuid4())[:8]

    log_q: queue.Queue = queue.Queue()
    _TASKS[task_id] = {
        "id": task_id,
        "project": req.project,
        "node_id": req.node_id,
        "action": req.action,
        "chapter": req.chapter,
        "status": "running",
        "started_at": time.time(),
        "queue": log_q,
    }

    def _worker():
        try:
            ch_str = f", chapter={req.chapter}" if req.chapter is not None else ""
            log_q.put(f"[studio] 开始执行: {req.action} (node={req.node_id}, project={req.project}{ch_str})\n")
            if req.action == "reconcile":
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "reconcile", "--project", str(pdir)]
            elif req.action == "run_node" and req.node_id:
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "run", req.node_id, "--project", str(pdir)]
            else:
                cmd = [sys.executable, str(SHARED_DIR / "pipeline.py"), "status", "--project", str(pdir)]

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

            try:
                pipeline.cmd_status(str(pdir))
            except Exception:
                pass

        except Exception as ex:
            log_q.put(f"\n[error] 发生异常: {str(ex)}\n")
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
    target = (pdir / file).resolve()

    if not str(target).startswith(str(pdir.resolve())):
        raise HTTPException(status_code=403, detail="禁止跨越项目目录")

    if not target.is_file():
        return {"exists": False, "file": file, "content": ""}

    return {"exists": True, "file": file, "content": target.read_text(encoding="utf-8", errors="replace")}


class SaveFileRequest(BaseModel):
    project: str
    file: str
    content: str


@app.post("/api/chapter/save")
def save_chapter_file(req: SaveFileRequest):
    """保存正文或草稿，并触发一次状态哈希刷新。"""
    pdir = find_project_dir(req.project)
    target = (pdir / req.file).resolve()

    if not str(target).startswith(str(pdir.resolve())):
        raise HTTPException(status_code=403, detail="禁止跨越项目目录")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")

    try:
        pipeline.cmd_status(str(pdir))
    except Exception:
        pass

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


def main():
    _reconfigure_stdio()
    import argparse
    parser = argparse.ArgumentParser(description="Novel Pipeline Studio Server")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8766, help="监听端口 (默认 8766)")
    args = parser.parse_args()

    print(f"[server] Novel Pipeline Studio started: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
