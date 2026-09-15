# -*- coding: utf-8 -*-
"""小说工业化节点图生产流水线编排核心。

本模块实现：
1. load_graph: graph.yaml 解析与强校验（支持 agent / command / human 三阶异构节点）
2. hash_file / hash_directory / hash_path: 基于文件内容的 SHA256 递归哈希，不依赖 mtime
3. derive_status: 增量状态机推导（current / stale / blocked / failed / pending-human）
4. evaluate_asserts: 小说质量硬断言（字数区间、章节标题格式、SCORES 结构化打分门禁）
5. generate_run_prompt: 面板一键派发给宿主 Agent (Antigravity) 的标准化执行指令
6. CLI 子命令: status / reconcile / run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

__all__ = [
    "ValidationError",
    "load_graph",
    "hash_file",
    "hash_directory",
    "hash_path",
    "derive_status",
    "generate_run_prompt",
    "evaluate_asserts",
    "count_text_words",
    "parse_scores_from_text",
    "build_command_argv",
    "utc_now_iso",
    "load_state",
    "write_state_atomic",
    "normalize_params",
    "cmd_status",
    "cmd_reconcile",
    "cmd_run",
    "main",
]

# 节点 id 命名规范：小写字母开头，由字母、数字与下划线组成
_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VALID_KINDS = {"command", "agent", "human"}
_SHELL_METACHARS = set(";|&<>`")

GRAPH_FILENAME = "graph.yaml"
STATE_FILENAME = "pipeline.json"
STATE_VERSION = 1
FAILURE_KEY = "failure"
_ACK_INVALIDATED_REASON = "该节点的上游输入或审核版本自上次确认后已变动，需重新人工核验"


class ValidationError(Exception):
    """graph.yaml 校验异常。"""


# ---------------------------------------------------------------------------
# 1. 哈希计算（基于内容，排序稳定聚合）
# ---------------------------------------------------------------------------

def hash_file(path: Path) -> str:
    """计算单个文件的 sha256 内容哈希，返回形如 'sha256:<hex>'。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def hash_directory(path: Path) -> str:
    """递归计算目录哈希：按排序后的相对正斜杠路径 + 各文件哈希复合聚合。"""
    h = hashlib.sha256()
    files = sorted(
        (p for p in path.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(path).as_posix(),
    )
    for file in files:
        rel = file.relative_to(path).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hash_file(file).encode("utf-8"))
        h.update(b"\0")
    return f"sha256:{h.hexdigest()}"


def hash_path(path: Path) -> str:
    """根据物理路径类型自动分派文件或目录哈希。"""
    if path.is_dir():
        return hash_directory(path)
    return hash_file(path)


# ---------------------------------------------------------------------------
# 2. 参数占位符展开与校验
# ---------------------------------------------------------------------------

def _lookup_param(params: Dict[str, Any], dotted: str) -> Tuple[bool, Any]:
    """按点号路径提取字典参数值，如 'review.min_score'。"""
    cur: Any = params
    for part in (dotted or "").split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _expand_params(text: str, params: Dict[str, Any]) -> str:
    """把 text 中已知存在的 {param} 占位符展开。"""
    if not isinstance(text, str) or "{" not in text:
        return text

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        found, val = _lookup_param(params, key)
        return str(val) if found and val is not None else match.group(0)

    return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\}", _replace, text)


def normalize_params(params: Dict[str, Any], override_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """规范化参数字典并自动派生章节/分卷相关辅助占位符。"""
    merged = dict(params or {})
    if override_params:
        merged.update({k: v for k, v in override_params.items() if v is not None})

    if "chapter_num" in merged:
        try:
            c_num = int(merged["chapter_num"])
            merged["chapter_num"] = c_num
            merged["chapter_pad3"] = f"{c_num:03d}"
            if override_params and "chapter_num" in override_params:
                merged["chapter_pad"] = f"{c_num:02d}"
            elif "chapter_pad" not in merged:
                merged["chapter_pad"] = f"{c_num:02d}"
            
            # 派生前序章节占位符（供前情探索节点引用）
            prev_num = max(1, c_num - 1)
            merged["chapter_prev_num"] = prev_num
            merged["chapter_prev_pad"] = f"{prev_num:02d}"
            merged["chapter_prev_pad3"] = f"{prev_num:03d}"
        except (ValueError, TypeError):
            pass

    if "volume_num" in merged:
        try:
            v_num = int(merged["volume_num"])
            merged["volume_num"] = v_num
            if "volume_pad" not in merged:
                merged["volume_pad"] = f"{v_num:02d}"
        except (ValueError, TypeError):
            pass
    elif "volume_pad" not in merged:
        merged["volume_num"] = 1
        merged["volume_pad"] = "01"

    if "volume_name" not in merged:
        merged["volume_name"] = "第一卷"

    return merged


def _validate_containment(rel_path_str: str, project_root: Optional[Path]) -> None:
    """路径安全约束：禁止通过 '..' 跳出当前小说项目目录。"""
    if not rel_path_str:
        return
    norm = Path(rel_path_str).as_posix()
    if norm.startswith("/") or re.match(r"^[a-zA-Z]:", norm):
        raise ValidationError(f"路径必须为相对项目根目录的路径: {rel_path_str!r}")
    parts = norm.split("/")
    if ".." in parts:
        raise ValidationError(f"路径禁止包含父级目录跳转 '..' : {rel_path_str!r}")


# ---------------------------------------------------------------------------
# 3. graph.yaml 加载与拓扑检验
# ---------------------------------------------------------------------------

def load_graph(yaml_text: str, project_root: Optional[Path] = None,
               override_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """解析并严格校验 graph.yaml 配置。"""
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ValidationError(f"YAML 语法错误: {exc}") from exc

    if not isinstance(data, dict):
        raise ValidationError("graph.yaml 顶层必须是映射/字典结构")

    raw_params = data.get("params") or {}
    if not isinstance(raw_params, dict):
        raise ValidationError("params 字段若存在，必须是字典结构")

    params = normalize_params(raw_params, override_params)
    data["params"] = params

    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValidationError("nodes 必须为非空字典")

    # 1) 节点定义校验
    for nid, node in nodes.items():
        if not isinstance(nid, str) or not _NODE_ID_RE.match(nid):
            raise ValidationError(f"非法节点 ID: {nid!r}，必须为小写字母开头的 snake_case")
        if not isinstance(node, dict):
            raise ValidationError(f"节点 [{nid}] 的定义必须是字典")

        kind = node.get("kind")
        if kind not in _VALID_KINDS:
            raise ValidationError(f"节点 [{nid}] 的 kind 必须是 {sorted(_VALID_KINDS)} 之一，当前为: {kind!r}")

        # 依赖列表
        after = node.get("after") or []
        if not isinstance(after, list) or not all(isinstance(x, str) for x in after):
            raise ValidationError(f"节点 [{nid}] 的 after 必须是字符串列表")
        for dep in after:
            if dep == nid:
                raise ValidationError(f"节点 [{nid}] 不能自我依赖")

        # 路径安全检查
        for io_key in ("inputs", "outputs", "inplace"):
            items = node.get(io_key) or []
            if not isinstance(items, list):
                raise ValidationError(f"节点 [{nid}] 的 {io_key} 必须是列表")
            for item in items:
                if isinstance(item, str):
                    _validate_containment(_expand_params(item, params), project_root)

        # 校验各类型的特殊字段
        if kind == "command":
            run_cmd = node.get("run")
            if not isinstance(run_cmd, list) or not run_cmd:
                raise ValidationError(f"command 节点 [{nid}] 必须声明非空列表类型的 run 命令")
        elif kind == "agent":
            if not node.get("role"):
                node["role"] = f"智能体-{nid}"
            model = node.get("model")
            if model is not None and (not isinstance(model, str) or not model.strip()):
                raise ValidationError(f"节点 [{nid}] 的 model 属性若声明，必须是非空字符串，当前为: {model!r}")
        elif kind == "human":
            if not node.get("ask"):
                raise ValidationError(f"human 节点 [{nid}] 必须声明 ask (人工审查说明)")

    # 2) 拓扑有向无环图（DAG）与依赖合法性检查
    all_nids = set(nodes.keys())
    for nid, node in nodes.items():
        for dep in (node.get("after") or []):
            if dep not in all_nids:
                raise ValidationError(f"节点 [{nid}] 依赖了不存在的节点 [{dep}]")

    # 环检测
    visited: Dict[str, int] = {}  # 0: visiting, 1: visited

    def dfs(cur: str, path: List[str]):
        visited[cur] = 0
        for nxt in (nodes[cur].get("after") or []):
            if nxt in visited and visited[nxt] == 0:
                cycle_str = " -> ".join(path + [nxt])
                raise ValidationError(f"检测到有向循环依赖环: {cycle_str}")
            if nxt not in visited:
                dfs(nxt, path + [nxt])
        visited[cur] = 1

    for nid in all_nids:
        if nid not in visited:
            dfs(nid, [nid])

    return data


# ---------------------------------------------------------------------------
# 4. 字数统计与质量断言 (Asserts)
# ---------------------------------------------------------------------------

def count_text_words(text: str) -> int:
    """计算中文小说的有效字数。
    
    统计规则：中文字符数 + 英文连续单词数（跳过纯空白、YAML Frontmatter 与 Markdown 标题标记）。
    """
    if not text:
        return 0
    # 剔除 YAML Frontmatter
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    # 剔除 Markdown 标题符号
    clean_lines = [line.lstrip("# \t") for line in text.splitlines() if line.strip()]
    cleaned = "\n".join(clean_lines)
    # 中文字符匹配
    cjk_count = len(re.findall(r"[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]", cleaned))
    # 英文词匹配
    words_count = len(re.findall(r"\b[a-zA-Z0-9_-]+\b", cleaned))
    return cjk_count + words_count


def parse_scores_from_text(text: str) -> Optional[Dict[str, float]]:
    """从审查报告中寻找形如 SCORES: {"overall": 85, "ooc": 90} 的 JSON 结构。"""
    if not text:
        return None
    for line in reversed(text.splitlines()):
        line_s = line.strip()
        if line_s.startswith("SCORES:"):
            raw_json = line_s[len("SCORES:"):].strip()
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    return {k: float(v) for k, v in parsed.items() if isinstance(v, (int, float))}
            except Exception:
                continue
    return None


def evaluate_asserts(node: Dict[str, Any], project_root: Path) -> List[str]:
    """对节点声明的 assert 质量规则进行强校验，返回未通过的原因列表。"""
    asserts = node.get("assert") or {}
    if not isinstance(asserts, dict) or not asserts:
        return []

    failures: List[str] = []
    params = node.get("_params") or {}

    # 读取主要输出文件（优先 outputs[0]，其次 inplace[0]）
    target_files = (node.get("outputs") or []) + (node.get("inplace") or [])
    if not target_files:
        return ["assert 评估失败: 该节点未声明 outputs 或 inplace 产物文件"]

    primary_rel = _expand_params(target_files[0], params)
    primary_path = project_root / primary_rel

    if not primary_path.is_file():
        return [f"assert 评估未通过: 产物文件不存在 {primary_rel}"]

    try:
        content = primary_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [f"assert 评估未通过: 无法读取产物文件 {primary_rel} ({e})"]

    # 1) 字数断言
    words = count_text_words(content)
    if "min_words" in asserts:
        req_min = int(asserts["min_words"])
        if words < req_min:
            failures.append(f"字数未达标: 当前有效字数 {words} < 最低要求 {req_min} ({primary_rel})")

    if "max_words" in asserts:
        req_max = int(asserts["max_words"])
        if words > req_max:
            failures.append(f"字数超标: 当前有效字数 {words} > 最高允许 {req_max} ({primary_rel})")

    # 2) 评分断言 (针对 review 节点)
    if "min_score" in asserts:
        req_score = float(asserts["min_score"])
        score_field = asserts.get("score_field", "overall")
        scores = parse_scores_from_text(content)
        if not scores or score_field not in scores:
            failures.append(f"评分门禁未通过: 报告中未找到合法 SCORES JSON 或缺少 '{score_field}' 字段")
        elif scores[score_field] < req_score:
            failures.append(
                f"评分门禁未通过: {score_field} 得分 {scores[score_field]} < 最低门槛 {req_score}"
            )

    # 3) 必须包含的标记或伏笔
    if "contains_markers" in asserts:
        markers = asserts["contains_markers"]
        if isinstance(markers, str):
            markers = [markers]
        for m in markers:
            if m not in content:
                failures.append(f"关键情节点缺失: 文稿中未检测到指定伏笔/标记 {m!r}")

    return failures


# ---------------------------------------------------------------------------
# 5. 增量状态机与 SHA256 物理指纹 (State Engine)
# ---------------------------------------------------------------------------

def _collect_input_hashes(node: Dict[str, Any], params: Dict[str, Any],
                          project_root: Path) -> Dict[str, Optional[str]]:
    """收集节点声明的所有输入文件的 SHA256 哈希值。"""
    result: Dict[str, Optional[str]] = {}
    inputs = (node.get("inputs") or [])
    for rel_path in inputs:
        exp_rel = _expand_params(rel_path, params)
        p = project_root / exp_rel
        if p.exists():
            try:
                result[exp_rel] = hash_path(p)
            except Exception:
                result[exp_rel] = None
        else:
            result[exp_rel] = None
    return result


def derive_status(graph: Dict[str, Any], project_root: Path,
                  old_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """基于物理文件哈希与拓扑依赖，推导所有节点的实时状态。
    
    状态集合：
    - current: 所有输入就绪、产物已生成且哈希与基线一致，且 assert 校验全过
    - stale: 输入发生变动，或自身定义修改，需要重跑
    - blocked: 任意直接或间接上游处于非 current 状态，或者输入文件物理缺失
    - failed: 上次执行失败或未通过质量 assert
    - pending-human: 人工审核节点等待创作者确认
    """
    params = graph.get("params") or {}
    nodes: Dict[str, Dict[str, Any]] = graph.get("nodes") or {}
    old_nodes = (old_state or {}).get("nodes") or {}

    current_hashes: Dict[str, Dict[str, Optional[str]]] = {}
    for nid, node in nodes.items():
        node["_params"] = params
        current_hashes[nid] = _collect_input_hashes(node, params, project_root)

    status: Dict[str, str] = {}
    because: Dict[str, List[str]] = {nid: [] for nid in nodes}
    failed_reasons: Dict[str, str] = {}
    ack_times: Dict[str, Optional[str]] = {}

    # 1. 基础自身状态判定
    for nid, node in nodes.items():
        kind = node.get("kind")
        old_entry = old_nodes.get(nid) or {}
        inputs_missing = [p for p, h in current_hashes[nid].items() if h is None]

        # 产物缺失判定
        out_missing = []
        for o in (node.get("outputs") or []) + (node.get("inplace") or []):
            op = project_root / _expand_params(o, params)
            if not op.exists():
                out_missing.append(_expand_params(o, params))

        # 检查是否缺失直接输入
        if inputs_missing and node.get("inputs"):
            status[nid] = "blocked"
            because[nid].append(f"输入文件缺失: {', '.join(inputs_missing)}")
            continue

        # 检查是否产物缺失
        if out_missing:
            status[nid] = "stale"
            because[nid].append(f"产物文件尚未生成: {', '.join(out_missing)}")
            continue

        # 检查质量断言
        assert_failures = evaluate_asserts(node, project_root)
        if assert_failures:
            status[nid] = "failed"
            failed_reasons[nid] = "；".join(assert_failures)
            because[nid].extend(assert_failures)
            continue

        # 人工节点处理
        if kind == "human":
            old_ack = old_entry.get("ackAt")
            old_inputs = old_entry.get("inputs") or {}
            # 只有当旧输入与当前输入完全一致时，历史审批才算有效
            if old_ack and old_inputs == current_hashes[nid]:
                status[nid] = "current"
                ack_times[nid] = old_ack
            else:
                status[nid] = "pending-human"
                ack_times[nid] = None
                if old_ack:
                    because[nid].append(_ACK_INVALIDATED_REASON)
                else:
                    because[nid].append(node.get("ask") or "等待创作者人工审查与放行")
            continue

        # 对比基线哈希判定是否过期 (stale)
        baseline_inputs = old_entry.get("inputs") or {}
        if baseline_inputs != current_hashes[nid]:
            status[nid] = "stale"
            changed = [p for p in current_hashes[nid] if current_hashes[nid].get(p) != baseline_inputs.get(p)]
            because[nid].append(f"输入内容发生变动: {', '.join(changed) if changed else '首次运行'}")
        else:
            status[nid] = "current"

    # 2. 拓扑依赖传递（任何上游未 current，下游一律 blocked）
    while True:
        changed = False
        for nid, node in nodes.items():
            if status[nid] in ("blocked", "failed"):
                continue
            for dep in (node.get("after") or []):
                dep_status = status.get(dep, "blocked")
                if dep_status != "current":
                    status[nid] = "blocked"
                    because[nid].append(f"上游节点 [{dep}] 处于 {dep_status} 状态")
                    changed = True
                    break
        if not changed:
            break

    # 组装新状态字典
    new_state: Dict[str, Any] = {
        "version": STATE_VERSION,
        "updatedAt": utc_now_iso(),
        "params": params,
        "nodes": {},
    }
    for nid, node in nodes.items():
        entry: Dict[str, Any] = {
            "kind": node.get("kind"),
            "role": node.get("role"),
            "status": status[nid],
            "inputs": current_hashes[nid],
            "outputs": [_expand_params(o, params) for o in (node.get("outputs") or [])],
            "staleBecause": "；".join(because[nid]) if because[nid] else None,
        }
        if node.get("model"):
            entry["model"] = node.get("model")
        if node.get("inplace"):
            entry["inplace"] = [_expand_params(p, params) for p in node["inplace"]]
        if nid in failed_reasons:
            entry["failedBecause"] = failed_reasons[nid]
        if node.get("kind") == "human":
            entry["ask"] = node.get("ask")
            entry["ackAt"] = ack_times.get(nid)
        new_state["nodes"][nid] = entry

    return new_state


# ---------------------------------------------------------------------------
# 6. runPrompt 生成（派发给宿主 Agent，如 Antigravity）
# ---------------------------------------------------------------------------

def generate_run_prompt(node_id: str, node: Dict[str, Any], project_dir: str) -> str:
    """生成标准化结构化任务指令，供宿主 Agent (Antigravity) 消费并直接落盘。"""
    kind = node.get("kind")
    params = node.get("_params") or {}
    role = node.get("role") or "小说创作专家"
    prompt_text = node.get("prompt") or ""
    model = node.get("model")
    inputs = [_expand_params(p, params) for p in (node.get("inputs") or [])]
    outputs = [_expand_params(p, params) for p in (node.get("outputs") or [])]
    inplace = [_expand_params(p, params) for p in (node.get("inplace") or [])]
    skills = node.get("skills") or []
    asserts = node.get("assert") or {}

    if kind == "agent":
        lines = [
            f"【小说工作流任务派发】执行项目 [{project_dir}] 的节点 [{node_id}]：",
            f"- 担当角色：{role}",
        ]
        if model:
            lines.append(f"- 算力调度模型：【{model}】")
        lines.extend([
            f"- 关联技能：{', '.join(skills) if skills else '无'}",
            f"- 输入文件契约 (只读以下文件)：{', '.join(inputs) if inputs else '无'}",
            f"- 产出目标契约 (请写入)：{', '.join(outputs + inplace)}",
        ])
        if asserts:
            assert_items = [f"{k}={v}" for k, v in asserts.items()]
            lines.append(f"- 质量硬断言要求：{', '.join(assert_items)}")
        lines.append(f"\n【核心执行指令】：\n{prompt_text.strip()}")
        lines.append(
            f"\n请使用你的工具读取输入文件并生成符合要求的文本直接写入指定产出文件。"
            f"完成后运行 `python shared/pipeline.py status --project {project_dir}` 刷新状态。"
        )
        return "\n".join(lines)

    if kind == "command":
        run_cmd = " ".join(_expand_params(str(a), params) for a in (node.get("run") or []))
        return f"执行命令行节点 [{node_id}]：运行 `{run_cmd}`。"

    if kind == "human":
        ask = node.get("ask") or "请创作者人工审查并确认放行"
        return f"人工审核节点 [{node_id}]：{ask}。确认通过后调用 `run {node_id}` 记录确认时间戳。"

    return f"执行节点 [{node_id}]"


# ---------------------------------------------------------------------------
# 7. pipeline.json 原子读写与状态管理
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """返回规范的 UTC ISO 时间戳，如 2026-09-12T04:20:00Z。"""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def state_path_of(project_root: Path) -> Path:
    return Path(project_root) / STATE_FILENAME


def load_state(project_root: Path) -> Dict[str, Any]:
    """读取已有的 pipeline.json 状态基线。"""
    p = state_path_of(project_root)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state_atomic(path: Path, state: Dict[str, Any]) -> None:
    """原子更新 pipeline.json：先写临时文件再原子 replace，杜绝文件损坏。"""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".pipeline-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def build_command_argv(node: Dict[str, Any], params: Dict[str, Any]) -> List[str]:
    """展开 command 节点的 run 数组。"""
    return [_expand_params(str(a), params) for a in (node.get("run") or [])]


# ---------------------------------------------------------------------------
# 8. 核心 CLI 命令实现 (status / reconcile / run)
# ---------------------------------------------------------------------------

def _load_project_graph(project_root: Path,
                        override_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    gpath = project_root / GRAPH_FILENAME
    if not gpath.is_file():
        raise ValidationError(f"项目目录缺失 {GRAPH_FILENAME}: {project_root}")
    return load_graph(gpath.read_text(encoding="utf-8"), project_root=project_root,
                      override_params=override_params)


def cmd_status(project_dir: str, override_params: Optional[Dict[str, Any]] = None) -> int:
    """计算哈希、评估 assert，并重写更新 pipeline.json。支持动态指定章节参数。"""
    project_root = Path(project_dir).resolve()
    try:
        graph = _load_project_graph(project_root, override_params=override_params)
    except ValidationError as e:
        print(f"[status] 校验失败: {e}")
        return 1

    old_state = load_state(project_root)
    new_state = derive_status(graph, project_root, old_state)
    write_state_atomic(state_path_of(project_root), new_state)

    curr_ch = (graph.get("params") or {}).get("chapter_num")
    ch_info = f" [第 {curr_ch} 章]" if curr_ch is not None else ""

    print(f"[status] 状态已更新{ch_info}: {state_path_of(project_root)}")
    for nid, entry in (new_state.get("nodes") or {}).items():
        reason = f" ({entry['staleBecause']})" if entry.get("staleBecause") else ""
        print(f"  {nid:<20} {entry['status']}{reason}")
    return 0


def cmd_reconcile(project_dir: str, override_params: Optional[Dict[str, Any]] = None) -> int:
    """强制重新扫盘，清除不一致并全量重写状态基线。"""
    project_root = Path(project_dir).resolve()
    try:
        graph = _load_project_graph(project_root, override_params=override_params)
    except ValidationError as e:
        print(f"[reconcile] 校验失败: {e}")
        return 1

    new_state = derive_status(graph, project_root, None)
    write_state_atomic(state_path_of(project_root), new_state)
    print(f"[reconcile] 基线已重新校准: {state_path_of(project_root)}")
    return 0


def cmd_run(node_id: str, project_dir: str, override_params: Optional[Dict[str, Any]] = None) -> int:
    """执行单个节点：command 直接子进程运行；human 记录确认时间戳；agent 输出 runPrompt。"""
    project_root = Path(project_dir).resolve()
    project_label = Path(project_dir).as_posix()
    try:
        graph = _load_project_graph(project_root, override_params=override_params)
    except ValidationError as e:
        print(f"[run] 校验失败: {e}")
        return 1

    node = (graph.get("nodes") or {}).get(node_id)
    if not node:
        print(f"[run] 节点不存在: {node_id}")
        return 1

    kind = node.get("kind")
    params = graph.get("params") or {}
    node["_params"] = params

    if kind == "command":
        argv = build_command_argv(node, params)
        print(f"[run] 执行 command 节点 [{node_id}]: {' '.join(argv)}")
        res = subprocess.run(argv, cwd=str(project_root))
        cmd_status(project_dir, override_params=override_params)
        return res.returncode

    if kind == "human":
        # 如果声明了 outputs 且输入有源文件，在放行时自动帮创作者归档到 outputs[0]
        outputs = [_expand_params(o, params) for o in (node.get("outputs") or [])]
        inputs = [_expand_params(i, params) for i in (node.get("inputs") or [])]
        if outputs and inputs:
            src = project_root / inputs[0]
            dst = project_root / outputs[0]
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                print(f"[run] 自动归档入库: {inputs[0]} -> {outputs[0]}")

        state = load_state(project_root)
        nodes_state = state.setdefault("nodes", {})
        entry = nodes_state.setdefault(node_id, {})
        entry["ackAt"] = utc_now_iso()
        entry["inputs"] = _collect_input_hashes(node, params, project_root)
        write_state_atomic(state_path_of(project_root), state)
        cmd_status(project_dir, override_params=override_params)
        print(f"[run] 人工节点 [{node_id}] 已审批放行 (ackAt={entry['ackAt']})")
        return 0

    if kind == "agent":
        prompt = generate_run_prompt(node_id, node, project_label)
        print(f"[run] [{node_id}] 为 Agent 智能体节点，请复制以下指令交给宿主 Agent (Antigravity) 执行：\n")
        print("-" * 60)
        print(prompt)
        print("-" * 60)
        return 2

    return 1


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(prog="pipeline.py", description="小说生产流水线引擎")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="重算哈希与状态")
    p_status.add_argument("--project", required=True, help="小说课题项目目录")
    p_status.add_argument("--chapter", type=int, default=None, help="动态指定章节序号 (如 11)")

    p_rec = sub.add_parser("reconcile", help="校准物理基线")
    p_rec.add_argument("--project", required=True, help="小说课题项目目录")
    p_rec.add_argument("--chapter", type=int, default=None, help="动态指定章节序号 (如 11)")

    p_run = sub.add_parser("run", help="运行单节点")
    p_run.add_argument("node_id", help="节点 ID")
    p_run.add_argument("--project", required=True, help="小说课题项目目录")
    p_run.add_argument("--chapter", type=int, default=None, help="动态指定章节序号 (如 11)")

    args = parser.parse_args(argv)
    override = {"chapter_num": args.chapter} if getattr(args, "chapter", None) is not None else None

    if args.command == "status":
        return cmd_status(args.project, override_params=override)
    if args.command == "reconcile":
        return cmd_reconcile(args.project, override_params=override)
    if args.command == "run":
        return cmd_run(args.node_id, args.project, override_params=override)
    return 0


if __name__ == "__main__":
    sys.exit(main())
