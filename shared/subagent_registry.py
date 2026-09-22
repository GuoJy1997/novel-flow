# -*- coding: utf-8 -*-
"""小说流水线核心专家 Subagent 规格资产库与动态注册引擎。

本模块实现：
1. load_manifest: 读取子智能体拓扑清单与预设配置
2. load_subagent_specs: 加载独立的 YAML 规格定义
3. resolve_bindings: 解析预设方案或自定义节点模型绑定
4. save_bindings_to_project: 将用户绑定的模型配置持久化至 subagents_config.json 并同步 graph.yaml
5. export_subagents_for_workspace: 导出至 .agents/ 规范目录，供宿主 Agent (Antigravity) 原生识别
6. get_registration_definitions: 生成注册规格包，其中模型已按当前宿主解析成真实可用 ID
7. 宿主感知: detect_host / load_host_profile / host_tier_model / host_role_model /
   host_registration / resolve_node_model —— 角色在不同宿主下用哪套模型标识，
   提前写在 manifest.json 的 host_profiles.<host> 里，用户与宿主 Agent 均可编辑
8. build_registration_spec: 打包「宿主 + 注册契约 + 各角色解析后的模型」交接物。
   注意：**注册动作由宿主 Agent 自己完成**（Antigravity 调 define_subagent 工具，
   Qoder 写 .qoder/agents/*.md 定义文件），本模块只感知与解析，不代替宿主注册
9. CLI 交互式与批处理命令行工具（list / configure / export / register-spec）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

DEFAULT_SUBAGENTS_DIR = Path(__file__).resolve().parent.parent / "subagents"
CONFIG_FILENAME = "subagents_config.json"


def load_manifest(subagents_dir: Optional[Path] = None) -> Dict[str, Any]:
    """加载 subagents/manifest.json 清单。"""
    sdir = subagents_dir or DEFAULT_SUBAGENTS_DIR
    manifest_path = sdir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"找不到子智能体清单文件: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_subagent_specs(subagents_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """加载所有子智能体的 YAML 完整规格配置。返回以 name 为键的字典。"""
    sdir = subagents_dir or DEFAULT_SUBAGENTS_DIR
    manifest = load_manifest(sdir)
    specs: Dict[str, Dict[str, Any]] = {}

    for entry in manifest.get("subagents", []):
        spec_file = sdir / entry.get("spec_file", "")
        if not spec_file.exists():
            raise FileNotFoundError(f"找不到子智能体规格文件: {spec_file}")
        with open(spec_file, "r", encoding="utf-8") as f:
            spec_data = yaml.safe_load(f)
        if not isinstance(spec_data, dict):
            raise ValueError(f"规格文件必须为有效 YAML 映射: {spec_file}")
        name = spec_data.get("name") or entry.get("name")
        spec_data["_spec_file"] = str(spec_file)
        specs[name] = spec_data

    return specs


# ---------------------------------------------------------------------------
# 宿主感知 (Host Awareness) 与模型解析
# ---------------------------------------------------------------------------
# 设计原则: **模型的唯一来源是"感知到的宿主"**。graph.yaml / yaml 规格 / 预设
# 里都不再写死任何"默认生效模型名"；tier(flash/pro) 是唯一跨宿主抽象。
# 具体模型名只存在于 host_profiles.<host> 里 (qoder 用内置 ID, antigravity 用
# gemini/claude)，各宿主彼此对等——没有哪个宿主是"出厂默认"。运行时解析链:
#   感知宿主 -> (显式钉死且宿主认识) / role_models[角色] / tiers[档位] -> 真实模型。
# 换宿主时无需改写工作流文件; 宿主未配置则明确报"未配置", 绝不回落到别家模型名。

# 人工强制指定宿主的环境变量 (取值: qoder / antigravity / generic)
HOST_OVERRIDE_ENV = "NOVELFLOW_HOST"

# 宿主环境指纹: 环境变量名前缀 -> 宿主 profile key (大小写不敏感, 按序匹配)
HOST_FINGERPRINTS: List[Tuple[str, str]] = [
    ("QODER", "qoder"),
    ("ANTIGRAVITY", "antigravity"),
]


def detect_host(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """探测当前运行宿主。

    优先级: NOVELFLOW_HOST 显式指定 > 环境变量指纹 > unknown (调用方透传兜底)。
    返回 {"host": str|None, "source": "env-override"|"fingerprint"|"unknown",
          "matched": 命中的环境变量名或 None}。
    """
    env_map = dict(env if env is not None else os.environ)
    forced = env_map.get(HOST_OVERRIDE_ENV, "").strip().lower()
    if forced:
        return {"host": forced, "source": "env-override", "matched": HOST_OVERRIDE_ENV}
    for prefix, key in HOST_FINGERPRINTS:
        for name in env_map:
            if name.upper().startswith(prefix):
                return {"host": key, "source": "fingerprint", "matched": name}
    return {"host": None, "source": "unknown", "matched": None}


def load_host_profile(host: Optional[str],
                      subagents_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """按宿主 key 加载 manifest.json 的 host_profiles 档案; 未知宿主返回 None。"""
    try:
        profiles = load_manifest(subagents_dir).get("host_profiles") or {}
    except FileNotFoundError:
        return None
    return profiles.get((host or "").strip().lower())


def host_tier_model(profile: Optional[Dict[str, Any]], tier: str) -> Optional[str]:
    """从宿主档案取某档位的首选模型名; 无映射返回 None。"""
    models = ((profile or {}).get("tiers") or {}).get((tier or "").strip().lower()) or []
    return models[0] if models else None


def host_role_model(profile: Optional[Dict[str, Any]], role: Optional[str]) -> Optional[str]:
    """从宿主档案的 role_models 取某角色(子智能体 name)预先写定的模型。

    这是"宿主感知"的核心落点: 同一个角色在不同宿主下用不同的模型标识,
    映射表提前写在 manifest.json 的 host_profiles.<host>.role_models 里,
    用户与宿主 Agent 都可以直接编辑。无该角色或无该表时返回 None。
    """
    if not role:
        return None
    return ((profile or {}).get("role_models") or {}).get(role.strip())


def host_registration(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """取宿主档案的注册契约 (registration 块)。

    注册动作由宿主 Agent 自己完成——不同宿主注册子智能体的方式不同
    (Antigravity 调 define_subagent 工具; Qoder 写 .qoder/agents/*.md 定义文件)。
    本仓库代码只负责把契约与解析好的模型交出去, 不代替宿主注册。
    """
    return dict((profile or {}).get("registration") or {})


def default_tier_for_role(role: Optional[str],
                          subagents_dir: Optional[Path] = None) -> Optional[str]:
    """取某角色(子智能体 name)规格里的 default_tier，作为节点未标注 model_tier 时的兜底。"""
    if not role:
        return None
    try:
        spec = load_subagent_specs(subagents_dir).get(role.strip()) or {}
    except (FileNotFoundError, ValueError):
        return None
    return (spec.get("model_config") or {}).get("default_tier")


def resolve_node_model(node: Dict[str, Any],
                       host: Optional[str],
                       subagents_dir: Optional[Path] = None) -> Dict[str, Any]:
    """解析 agent 节点在当前宿主下实际使用的模型。

    **模型的唯一来源是"感知到的宿主"**：规格/图谱里不再有任何"默认生效模型名"，
    gemini/claude 之类只是某个宿主 profile 里的取值，彼此对等。解析链 (高 -> 低):
      1. 节点带 subagent_type 且宿主 role_models 里有该角色 -> 角色绑定 (role-mapped)。
         这是权威路径：要为某角色在某宿主换模型，就改 host_profiles.<host>.role_models；
         graph.yaml 里遗留的 model 名（哪怕恰好是本宿主认识的）一律忽略，只作提示;
      2. 无角色绑定时，节点显式 model 且它正是当前宿主认识的模型 -> 尊重显式值
         (explicit-matched)，这是无角色节点为该宿主钉死模型的逃生舱;
      3. 节点 model_tier (或由角色规格 default_tier 兜底) 在宿主 tiers 里有映射
         -> 档位映射 (tier-mapped);
      4. 宿主有档案但上述都没命中 -> 未配置 (host-unmapped)，model=None，
         提示去 host_profiles 补该角色/档位;
      5. 未识别宿主 / 无档案 / 档案无任何映射 -> no-host，model=None。
    任何情况下都**不会**回落到某个具体宿主的模型名。
    """
    raw_model = (node.get("model") or "").strip() or None
    raw_tier = (node.get("model_tier") or "").strip() or None
    raw_role = (node.get("subagent_type") or "").strip() or None
    profile = load_host_profile(host, subagents_dir)

    result: Dict[str, Any] = {
        "model": None, "tier": raw_tier, "origin": "no-host", "note": None,
    }
    if profile is None:
        result["note"] = (f"未识别宿主 (可用 {HOST_OVERRIDE_ENV}=qoder|antigravity|generic 指定)；"
                          f"模型由宿主决定，请先感知宿主或在 manifest.json 的 host_profiles 里补该宿主")
        return result

    tiers = profile.get("tiers") or {}
    role_models = profile.get("role_models") or {}
    # generic 等空档案: 没有任何映射 -> 视为未配置
    if not tiers and not role_models:
        result["origin"] = "host-unmapped"
        result["note"] = (f"宿主 {host} 未配置任何模型映射；请先在 subagents/manifest.json 的 "
                          f"host_profiles.{host} 里补 role_models 或 tiers")
        return result

    known_models = ({m for models in tiers.values() for m in models}
                    | {m for m in role_models.values() if m})

    # 1) 角色级宿主绑定 (权威): graph.yaml 的 model 名一律忽略
    bound = host_role_model(profile, raw_role)
    if bound:
        result["model"] = bound
        result["origin"] = "role-mapped"
        if raw_model and raw_model != bound:
            result["note"] = (f"角色 {raw_role} 在宿主 {host} 由 role_models 绑定为 {bound}，"
                              f"已忽略图谱里遗留的模型名 {raw_model}")
        return result

    # 2) 无角色绑定时, 显式 model 且宿主认识 -> 尊重 (无角色节点的宿主钉死逃生舱)
    if raw_model and raw_model in known_models:
        result["model"] = raw_model
        result["origin"] = "explicit-matched"
        return result

    # 3) 档位映射 (节点 model_tier 优先, 否则用角色规格 default_tier 兜底)
    tier = raw_tier or default_tier_for_role(raw_role, subagents_dir)
    mapped = host_tier_model(profile, tier) if tier else None
    if mapped:
        result["model"] = mapped
        result["tier"] = tier
        result["origin"] = "tier-mapped"
        if raw_model and raw_model != mapped:
            result["note"] = (f"宿主 {host} 按档位 {tier} 解析为 {mapped}，"
                              f"已忽略图谱里遗留的模型名 {raw_model}")
        return result

    # 4) 宿主有档案但未覆盖该角色/档位
    result["origin"] = "host-unmapped"
    result["tier"] = tier
    result["note"] = (f"宿主 {host} 未给角色 {raw_role or '?'}/档位 {tier or '?'} 配置模型；"
                      f"请编辑 subagents/manifest.json 的 host_profiles.{host}.role_models")
    return result


def describe_host(host_info: Dict[str, Any],
                  subagents_dir: Optional[Path] = None) -> str:
    """生成 cmd_status 打印的宿主感知摘要行。"""
    host = host_info.get("host")
    if not host:
        return ("[host] 未识别宿主环境 (可用 NOVELFLOW_HOST=qoder|antigravity|generic 指定)，"
                "模型名按 graph.yaml 原样透传")
    profile = load_host_profile(host, subagents_dir)
    if not profile:
        return f"[host] 宿主 {host} 无档案，模型名原样透传"
    mapping = ", ".join(
        f"{t}→{models[0]}"
        for t, models in (profile.get("tiers") or {}).items()
        if models and t != "inherit"
    )
    source_label = {"env-override": "手动指定",
                    "fingerprint": f"指纹 {host_info.get('matched')}"}.get(
        host_info.get("source"), host_info.get("source"))
    role_models = profile.get("role_models") or {}
    role_part = (f" | 角色级绑定: {len(role_models)} 个"
                 if role_models else " | 角色级绑定: 无 (仅按档位映射)")
    return f"[host] 已感知宿主: {host} ({source_label}) | 档位映射: {mapping}{role_part}"


def get_preset_bindings(preset_name: str = "recommended",
                        subagents_dir: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """获取指定预设方案的模型绑定表。"""
    manifest = load_manifest(subagents_dir)
    presets = manifest.get("presets", {})
    if preset_name not in presets:
        available = list(presets.keys())
        raise ValueError(f"未知预设方案: {preset_name!r}，可选预设: {available}")
    return presets[preset_name].get("bindings", {})


def resolve_bindings(preset: Optional[str] = None,
                     custom_tiers: Optional[Dict[str, str]] = None,
                     subagents_dir: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """解析最终的节点绑定配置（预设 + 自定义覆盖）。

    预设只声明 **tier**（跨宿主抽象），不再写死任何具体模型名——具体模型
    运行时由所在宿主的 host_profiles 解析。仅当用户显式钉死某个模型串时，
    才在绑定里保留 model 字段作为该宿主的 explicit pin。
    """
    manifest = load_manifest(subagents_dir)
    presets = manifest.get("presets", {})
    preset_key = preset or "recommended"

    if preset_key in presets:
        base = {nid: dict(b) for nid, b in (presets[preset_key].get("bindings", {}) or {}).items()}
    else:
        base = {}

    # 如果有自定义覆盖
    if custom_tiers:
        for node_id, tier_or_model in custom_tiers.items():
            v = (tier_or_model or "").strip()
            if v.lower() in ("flash", "flash_lite", "pro", "inherit"):
                # 只声明档位, 具体模型交给宿主解析
                base[node_id] = {"tier": v.lower()}
            else:
                # 用户为该宿主钉死了具体模型串 -> 保留为 explicit pin, 并粗判档位
                inferred = "pro" if any(k in v.lower() for k in ("pro", "opus", "sonnet", "deep", "max")) else "flash"
                base[node_id] = {"tier": inferred, "model": v}

    return base


def save_bindings_to_project(project_dir: Path,
                             bindings: Dict[str, Dict[str, str]],
                             preset_name: Optional[str] = None,
                             subagents_dir: Optional[Path] = None) -> Path:
    """将子智能体模型绑定持久化至项目的 subagents_config.json，并同步注入 graph.yaml。"""
    manifest = load_manifest(subagents_dir)
    specs = load_subagent_specs(subagents_dir)

    # 映射 node_id -> subagent name
    node_to_subagent: Dict[str, str] = {}
    for name, spec in specs.items():
        nid = spec.get("node_id")
        if nid:
            node_to_subagent[nid] = name

    # 1. 写入 subagents_config.json
    config_data = {
        "version": "1.0",
        "preset": preset_name or "custom",
        "bindings": bindings,
        "nodes": {}
    }
    for nid, binfo in bindings.items():
        sname = node_to_subagent.get(nid, "")
        config_data["nodes"][nid] = {
            "subagent_type": sname,
            "role": specs.get(sname, {}).get("role", nid),
            "tier": binfo.get("tier", "inherit"),
            "model": binfo.get("model", ""),
        }

    cfg_path = project_dir / CONFIG_FILENAME
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    # 节点别名容错映射（例如 demo 项目中的 gather_state 对应 context_scout 规格中的 explore_context）
    NODE_ALIASES: Dict[str, str] = {
        "gather_state": "explore_context",
        "explore_context": "gather_state",
    }

    # 2. 同步回写 graph.yaml (若存在)
    graph_path = project_dir / "graph.yaml"
    if graph_path.exists():
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_data = yaml.safe_load(f)

        if isinstance(graph_data, dict) and "nodes" in graph_data:
            modified = False
            for nid, node in graph_data["nodes"].items():
                target_binding_key = nid if nid in bindings else NODE_ALIASES.get(nid)
                if target_binding_key and target_binding_key in bindings:
                    b = bindings[target_binding_key]
                    sname = node_to_subagent.get(nid) or node_to_subagent.get(target_binding_key)
                    if sname:
                        node["subagent_type"] = sname
                    node["model_tier"] = b.get("tier")
                    if b.get("model"):
                        # 用户为某宿主显式钉死了模型 -> 保留
                        node["model"] = b.get("model")
                    else:
                        # 预设只声明档位: 移除任何写死的具体模型名, 让 graph.yaml 保持宿主无关,
                        # 运行时由所在宿主的 host_profiles 解析出真实模型
                        node.pop("model", None)
                    modified = True
            if modified:
                with open(graph_path, "w", encoding="utf-8") as f:
                    yaml.dump(graph_data, f, allow_unicode=True, sort_keys=False)

    return cfg_path


def load_project_bindings(project_dir: Path) -> Optional[Dict[str, Any]]:
    """读取项目中已持久化的子智能体配置。"""
    cfg_path = project_dir / CONFIG_FILENAME
    if not cfg_path.exists():
        return None
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def export_subagents_for_workspace(project_dir: Path,
                                   subagents_dir: Optional[Path] = None) -> List[Path]:
    """将子智能体定义导出至 project_dir/.agents/subagents/，以便宿主 Agent 自动发现。"""
    specs = load_subagent_specs(subagents_dir)
    target_dir = project_dir / ".agents" / "subagents"
    target_dir.mkdir(parents=True, exist_ok=True)

    exported_files: List[Path] = []
    for name, spec in specs.items():
        export_path = target_dir / f"{name}.json"
        clean_spec = {
            "name": spec.get("name"),
            "role": spec.get("role"),
            "node_id": spec.get("node_id"),
            "description": spec.get("description"),
            "tools": spec.get("tools", {}),
            "model_config": spec.get("model_config", {}),
            "system_prompt": spec.get("system_prompt", ""),
        }
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(clean_spec, f, ensure_ascii=False, indent=2)
        exported_files.append(export_path)

    return exported_files


def get_registration_definitions(bindings: Optional[Dict[str, Dict[str, str]]] = None,
                                 subagents_dir: Optional[Path] = None,
                                 host: Optional[str] = None) -> List[Dict[str, Any]]:
    """生成供宿主 Agent 自行注册子智能体的标准规格包。

    注册动作由宿主 Agent 完成 (不同宿主方式不同)，本函数只负责把规格与
    **当前宿主下真实可用的模型 ID** 交出去。`_bound_model` 纯按宿主解析
    (显式 pin -> host_profiles.<host>.role_models 角色绑定 -> 档位映射)，
    gemini-*/claude-* 只是 antigravity 宿主 profile 里的取值，与 qoder 对等，
    不再是全局默认；宿主未配置时 `_bound_model` 为 None（由宿主 Agent 去补）。

    返回列表每个元素结构：
    {
        "name": "novel_context_scout",
        "description": "...",
        "system_prompt": "...",
        "enable_write_tools": True,
        "enable_mcp_tools": False,
        "enable_subagent_tools": False,
        "_role": "...",
        "_node_id": "...",
        "_bound_tier": "flash",
        "_bound_model": "qfmodel",
        "_model_origin": "role-mapped",
        "_host": "qoder"
    }
    """
    specs = load_subagent_specs(subagents_dir)
    effective_bindings = bindings or get_preset_bindings("recommended", subagents_dir)
    if host is None:
        host = detect_host().get("host")
    profile = load_host_profile(host, subagents_dir)
    tiers = (profile or {}).get("tiers") or {}
    role_models = (profile or {}).get("role_models") or {}
    known_models = ({m for models in tiers.values() for m in models}
                    | {m for m in role_models.values() if m})

    definitions: List[Dict[str, Any]] = []
    for name, spec in specs.items():
        tools_cfg = spec.get("tools", {})
        nid = spec.get("node_id") or ""
        binfo = effective_bindings.get(nid, {})

        tier = binfo.get("tier") or spec.get("model_config", {}).get("default_tier", "inherit")
        pin = binfo.get("model")  # 用户为某宿主显式钉死的模型串 (可能为空)

        role_bound = host_role_model(profile, name)
        tier_bound = host_tier_model(profile, tier)
        if role_bound:
            host_model, origin = role_bound, "role-mapped"
        elif pin and pin in known_models:
            host_model, origin = pin, "explicit-matched"
        elif tier_bound and tier_bound != "inherit":
            host_model, origin = tier_bound, "tier-mapped"
        else:
            host_model, origin = None, "host-unmapped"

        entry = {
            "name": name,
            "description": spec.get("description", "").strip(),
            "system_prompt": spec.get("system_prompt", "").strip(),
            "enable_write_tools": bool(tools_cfg.get("enable_write_tools", True)),
            "enable_mcp_tools": bool(tools_cfg.get("enable_mcp_tools", False)),
            "enable_subagent_tools": bool(tools_cfg.get("enable_subagent_tools", False)),
            "_role": spec.get("role", name),
            "_node_id": nid,
            "_bound_tier": tier,
            "_bound_model": host_model,
            "_model_origin": origin,
            "_host": host,
        }
        definitions.append(entry)

    return definitions


def build_registration_spec(project_dir: Optional[Path] = None,
                            preset: Optional[str] = None,
                            subagents_dir: Optional[Path] = None,
                            host: Optional[str] = None) -> Dict[str, Any]:
    """打包宿主 Agent 注册子智能体所需的全部信息 (交接物)。

    返回:
    {
      "host": "qoder",
      "host_source": "fingerprint"|"env-override"|"unknown"|"explicit",
      "registration": {...宿主注册契约...},
      "project": "<项目目录或 None>",
      "preset": "recommended",
      "subagents": [ get_registration_definitions() 的逐项 ],
    }

    宿主 Agent 拿到后按 registration 契约自行完成注册:
    Qoder -> 写 <project>/.qoder/agents/<name>.md (frontmatter: name/description/model/tools,
             正文为 system_prompt)，且必须新开会话才会注册上;
    Antigravity -> 逐个调用 define_subagent。
    """
    host_info = detect_host()
    effective_host = host or host_info.get("host")
    profile = load_host_profile(effective_host, subagents_dir)
    bindings = None
    if project_dir:
        saved = load_project_bindings(Path(project_dir))
        if saved and saved.get("bindings"):
            bindings = saved["bindings"]
    return {
        "host": effective_host,
        "host_source": "explicit" if host else host_info.get("source"),
        "host_matched_env": host_info.get("matched"),
        "registration": host_registration(profile),
        "project": str(project_dir) if project_dir else None,
        "preset": preset or ("custom" if bindings else "recommended"),
        "subagents": get_registration_definitions(bindings=bindings,
                                                  subagents_dir=subagents_dir,
                                                  host=effective_host),
    }


# ---------------------------------------------------------------------------
# CLI 命令行处理
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="小说流水线 Subagent 独立规格与注册管理 CLI")
    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # list
    p_list = subparsers.add_parser("list", help="列出所有可用的专家子智能体规格")
    p_list.add_argument("--subagents-dir", type=Path, default=None, help="子智能体规格库路径")

    # configure
    p_cfg = subparsers.add_parser("configure", help="为小说项目配置并绑定子智能体模型")
    p_cfg.add_argument("--project", type=Path, required=True, help="小说项目根目录")
    p_cfg.add_argument("--preset", choices=["recommended", "all_flash", "all_pro", "writer_pro"], default="recommended",
                       help="预设方案")
    p_cfg.add_argument("--set", dest="overrides", action="append", default=[],
                       help="单独覆盖节点配置，格式: node_id=tier或模型名 (如 --set draft_chapter=gemini-3.1-pro)")
    p_cfg.add_argument("--subagents-dir", type=Path, default=None, help="子智能体规格库路径")

    # export
    p_exp = subparsers.add_parser("export", help="导出子智能体规格至项目的 .agents/subagents/")
    p_exp.add_argument("--project", type=Path, required=True, help="小说项目根目录")
    p_exp.add_argument("--subagents-dir", type=Path, default=None, help="子智能体规格库路径")

    # register-spec
    p_reg = subparsers.add_parser(
        "register-spec",
        help="输出当前宿主的子智能体注册规格 JSON (交宿主 Agent 自行完成注册)")
    p_reg.add_argument("--project", type=Path, default=None,
                       help="小说项目根目录 (存在 subagents_config.json 时用其绑定)")
    p_reg.add_argument("--host", default=None,
                       help="强制指定宿主 qoder/antigravity/generic，默认自动感知")
    p_reg.add_argument("--subagents-dir", type=Path, default=None, help="子智能体规格库路径")

    args = parser.parse_args()

    if args.subcommand == "list":
        specs = load_subagent_specs(args.subagents_dir)
        host_info = detect_host()
        host = host_info.get("host")
        profile = load_host_profile(host, args.subagents_dir)
        print(f"=== 小说流水线专家 Subagents 清单 (共 {len(specs)} 个) ===")
        print(describe_host(host_info, args.subagents_dir))
        print()
        for name, spec in specs.items():
            tier = spec.get("model_config", {}).get("default_tier")
            bound = host_role_model(profile, name) or host_tier_model(profile, tier)
            print(f"- 【{name}】: {spec.get('role')}")
            print(f"  对应节点: {spec.get('node_id')}")
            print(f"  默认档位 (跨宿主抽象): {tier}")
            if host:
                origin = "role_models 角色绑定" if host_role_model(profile, name) else "档位映射"
                print(f"  宿主 {host} 解析模型: {bound or '(未配置，请编辑 host_profiles)'} ← {origin}")
            else:
                print("  宿主未识别: 模型待定 (由宿主决定，请先感知宿主)")
            print(f"  职责简介: {spec.get('description')}\n")
        return 0

    elif args.subcommand == "configure":
        custom_tiers = {}
        for item in args.overrides:
            if "=" in item:
                k, v = item.split("=", 1)
                custom_tiers[k.strip()] = v.strip()
        bindings = resolve_bindings(preset=args.preset, custom_tiers=custom_tiers, subagents_dir=args.subagents_dir)
        preset_name = "custom" if custom_tiers else args.preset
        cfg_path = save_bindings_to_project(args.project, bindings, preset_name=preset_name, subagents_dir=args.subagents_dir)
        print(f"[OK] 成功应用配置 [preset={preset_name}] 并持久化至: {cfg_path}")
        for nid, b in bindings.items():
            pin = b.get("model")
            tail = f", model={pin} (显式钉死)" if pin else " (模型由宿主 host_profiles 解析)"
            print(f"  - 节点 [{nid}]: tier={b.get('tier')}{tail}")
        print("[OK] 已同步更新 graph.yaml 各节点的 subagent_type 与 model_tier；未钉死模型的节点已移除写死的 model 名，保持宿主无关")
        return 0

    elif args.subcommand == "export":
        exported = export_subagents_for_workspace(args.project, args.subagents_dir)
        print(f"[OK] 成功导出 {len(exported)} 个子智能体定义至 {args.project / '.agents' / 'subagents'}")
        for p in exported:
            print(f"  - {p.name}")
        return 0

    elif args.subcommand == "register-spec":
        spec = build_registration_spec(project_dir=args.project,
                                       subagents_dir=args.subagents_dir,
                                       host=args.host)
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
