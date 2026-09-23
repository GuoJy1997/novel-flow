# -*- coding: utf-8 -*-
"""唯一单章模板：原始快照、项目引用与独立实例化（不依赖 pipeline）。

这里只生成普通 graph 字典，不解析具体模型、不读写项目状态、不执行节点。
快照的哈希与信任校验由生产清单持有者负责；实例化始终深复制快照。
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import sys

import yaml

_TEMPLATE_ID = "chapter-v1"
_CHAIN = (
    "explore_context", "scene_beats", "draft_chapter", "deai_polish",
    "check_zhuque", "zhuque_api_final", "audit_persona", "review_qc",
    "author_accept", "novel_stats",
)
_PARAM_KEYS = frozenset({
    "chapter_num", "chapter_title", "volume_name", "genre", "tone", "target_words",
    "chapter_workspace", "chapter_output", "voice_sample",
})
_PATH_KEYS = frozenset({"chapter_workspace", "chapter_output", "voice_sample"})
_ENGINE_KEYS = frozenset({"python_executable", "engine_shared"})
_TOKEN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _check_id(template_id):
    if not isinstance(template_id, str) or template_id != _TEMPLATE_ID:
        raise ValueError(f"未知单章模板: {template_id!r}")


def _mapping(value, label):
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} 必须是字符串键的字典")
    return value


def _check_template(data):
    _mapping(data, "template snapshot")
    if data.get("version") != 1:
        raise ValueError("单章模板 version 必须为 1")
    _mapping(data.get("params"), "template params")
    nodes = _mapping(data.get("nodes"), "template nodes")
    if set(nodes) != set(_CHAIN):
        raise ValueError("单章模板必须包含固定的十个节点")
    for index, nid in enumerate(_CHAIN):
        node = _mapping(nodes[nid], f"template nodes.{nid}")
        if "model" in node:
            raise ValueError("单章模板不得保存具体 model")
        if node.get("after", []) != ([] if index == 0 else [_CHAIN[index - 1]]):
            raise ValueError(f"单章模板节点 {nid} 的依赖链不正确")
        expected_kind = ("human" if nid == "author_accept" else
                         "command" if nid in {"check_zhuque", "zhuque_api_final", "novel_stats"} else "agent")
        if node.get("kind") != expected_kind:
            raise ValueError(f"单章模板节点 {nid} 必须保留 {expected_kind} 类型")
        if expected_kind == "agent":
            skills = node.get("skills")
            if not isinstance(skills, list) or not skills or not all(isinstance(s, str) and s.strip() for s in skills):
                raise ValueError(f"单章模板节点 {nid} 必须保留技能配置")
        if nid not in {"author_accept", "novel_stats"}:
            rules = _mapping(node.get("assert"), f"{nid}.assert")
            key = "min_words" if index < 4 else "min_score"
            value = rules.get(key)
            word_param = {"draft_chapter": "{draft_min_words}", "deai_polish": "{polish_min_words}"}.get(nid)
            if not (type(value) in (int, float) and value > 0) and not (word_param and value == word_param):
                raise ValueError(f"单章模板节点 {nid} 不可移除 {key} 门禁")
    archive = nodes["author_accept"]
    polished = nodes["deai_polish"].get("outputs", [])
    if (not polished or archive.get("inputs", [])[:1] != polished[:1]
            or archive.get("outputs") != ["{chapter_output}"] or not archive.get("ask")):
        raise ValueError("人工归档必须审阅润色稿并写入正式章路径")
    return data


def load_template(template_id="chapter-v1") -> dict:
    """读取可供哈希锁定的原始 YAML 字典，不注入本机路径或具体模型。"""
    _check_id(template_id)
    path = Path(__file__).resolve().parent / "templates" / f"{template_id}.yaml"
    return _check_template(yaml.safe_load(path.read_text(encoding="utf-8")))


def _text(value, label):
    if (not isinstance(value, str) or not value.strip()
            or any(ord(char) < 32 for char in value)):
        raise ValueError(f"{label} 必须是非空且不含控制字符的字符串")
    return value


def _safe_path(value, label, *, placeholders=False):
    """跨平台词法检查，不依赖文件存在；实际符号链接包含性由项目加载器负责。"""
    value = _text(value, label).replace("\\", "/")
    if (value != value.strip() or value.startswith(("/", "~"))
            or re.search(r'[:<>"|?*]', value)):
        raise ValueError(f"{label} 必须为项目内相对路径: {value!r}")
    parts = value.rstrip("/").split("/")
    for part in parts:
        if not part or part in (".", "..") or part != part.rstrip(" ."):
            raise ValueError(f"{label} 禁止目录跳转或不安全路径段: {value!r}")
        if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I):
            raise ValueError(f"{label} 禁止设备路径: {value!r}")
    remainder = _TOKEN.sub("parameter", value) if placeholders else value
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{label} 含有未解析的参数: {value!r}")
    return value


def _params(defaults, params):
    _mapping(defaults, "template params")
    supplied = {} if params is None else _mapping(params, "params")
    unknown = (set(defaults) | set(supplied)) - _PARAM_KEYS
    if unknown:
        raise ValueError(f"不允许覆盖这些章级参数: {', '.join(sorted(unknown))}")
    raw = deepcopy(defaults)
    raw.update(deepcopy(supplied))
    if set(raw) != _PARAM_KEYS:
        raise ValueError("模板缺少必要的章级默认参数")
    for key in ("chapter_num", "target_words"):
        if type(raw[key]) is not int or raw[key] <= 0:
            raise ValueError(f"{key} 必须是正整数")
    if not 500 <= raw["target_words"] <= 20000:
        raise ValueError("target_words 必须在 500 到 20000 之间")
    for key in ("chapter_title", "volume_name", "genre", "tone"):
        _text(raw[key], key)
        if "{" in raw[key] or "}" in raw[key]:
            raise ValueError(f"{key} 不允许嵌套参数")
    for key in ("chapter_title", "volume_name"):
        _safe_path(raw[key], key)
        if "/" in raw[key] or "\\" in raw[key]:
            raise ValueError(f"{key} 不得包含路径分隔符")
    for key in _PATH_KEYS:
        raw[key] = _safe_path(raw[key], key, placeholders=True)

    expanded = deepcopy(raw)
    number = raw["chapter_num"]
    previous = max(1, number - 1)
    target = raw["target_words"]
    expanded.update({
        "chapter_pad": f"{number:02d}", "chapter_pad3": f"{number:03d}",
        "chapter_prev_num": previous, "chapter_prev_pad": f"{previous:02d}",
        "chapter_prev_pad3": f"{previous:03d}",
        "draft_min_words": target * 80 // 100,
        "polish_min_words": target * 75 // 100,
        "chapter_max_words": (target * 140 + 99) // 100,
        "engine_shared": Path(__file__).resolve().parent.as_posix(),
        "python_executable": Path(sys.executable).resolve().as_posix(),
    })
    resolved = set()

    def resolve(key, stack=()):
        if key not in expanded or key in _ENGINE_KEYS:
            raise ValueError(f"路径中不允许使用参数: {key}")
        if key not in _PATH_KEYS or key in resolved:
            return str(expanded[key])
        if key in stack:
            raise ValueError("路径参数不能循环引用")
        value = _TOKEN.sub(lambda m: resolve(m[1], (*stack, key)), raw[key])
        expanded[key] = _safe_path(value, key)
        resolved.add(key)
        return expanded[key]

    for key in _PATH_KEYS:
        resolve(key)
    return raw, expanded


def _expand(value, params):
    """仅替换已知的单层标识符，保留 SCORES JSON；整值数字保持原类型。"""
    if isinstance(value, str):
        match = _TOKEN.fullmatch(value)
        if match and match[1] in params:
            return params[match[1]]
        return _TOKEN.sub(lambda m: str(params[m[1]]) if m[1] in params else m[0], value)
    if isinstance(value, list):
        return [_expand(item, params) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, params) for key, item in value.items()}
    return value


def _apply_overrides(nodes, overrides, params):
    supplied = {} if overrides is None else _mapping(overrides, "overrides")
    for nid, patch in supplied.items():
        if nid not in nodes:
            raise ValueError(f"overrides 未知节点: {nid}")
        _mapping(patch, f"overrides.{nid}")
        unknown = set(patch) - {"prompt_append", "inputs_add"}
        if unknown:
            raise ValueError(f"overrides.{nid} 不允许字段: {', '.join(sorted(unknown))}")
        node = nodes[nid]
        if "prompt_append" in patch:
            text = patch["prompt_append"]
            if node["kind"] != "agent" or not isinstance(text, str):
                raise ValueError("prompt_append 仅允许 agent 节点使用字符串")
            if text:
                node["prompt"] += "\n\n" + text
        if "inputs_add" in patch:
            additions = patch["inputs_add"]
            if not isinstance(additions, list):
                raise ValueError(f"overrides.{nid}.inputs_add 必须为字符串列表")
            for item in additions:
                path = _safe_path(item, f"overrides.{nid}.inputs_add", placeholders=True)
                for key in _TOKEN.findall(path):
                    if key not in params or key in _ENGINE_KEYS:
                        raise ValueError(f"inputs_add 中不允许使用参数: {key}")
                _safe_path(_expand(path, params), f"overrides.{nid}.inputs_add")
                node.setdefault("inputs", []).append(path)


def instantiate(template_id="chapter-v1", params=None, overrides=None, snapshot=None) -> dict:
    """生成独立普通图；只接受内容参数与追加式覆盖，不执行或导入流水线。"""
    _check_id(template_id)
    raw = deepcopy(load_template(template_id) if snapshot is None else _check_template(snapshot))
    _, expanded = _params(raw["params"], params)
    nodes = {nid: raw["nodes"][nid] for nid in _CHAIN}
    _apply_overrides(nodes, overrides, expanded)
    nodes = _expand(nodes, expanded)
    for nid, node in nodes.items():
        for key in ("inputs", "outputs"):
            node[key] = [_safe_path(path, f"{nid}.{key}") for path in node.get(key, [])]
    return {"version": raw["version"], "name": raw["name"], "params": expanded, "nodes": nodes}


def reference(params=None) -> dict:
    """脚手架默认引用：项目资料以 inputs_add 接入，模板本身不假定这些资料存在。"""
    raw = load_template()
    supplied, _ = _params(raw["params"], params)
    return {
        "version": raw["version"], "name": raw["name"], "template": _TEMPLATE_ID,
        "params": supplied,
        "overrides": {
            "explore_context": {"inputs_add": ["设定/世界观/", "设定/人物/", "设定/大纲/"]},
            "scene_beats": {"inputs_add": ["设定/大纲/"]},
            "draft_chapter": {"inputs_add": ["设定/人物/", "设定/世界观/"]},
            "audit_persona": {"inputs_add": ["设定/人物/", "设定/大纲/"]},
            "review_qc": {"inputs_add": ["设定/世界观/", "设定/人物/"]},
        },
    }
