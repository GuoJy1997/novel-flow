# -*- coding: utf-8 -*-
"""小说流水线 Subagent 独立规格与动态注册引擎单元测试。"""
import json
import pytest
from pathlib import Path
import tempfile
import yaml

from shared.subagent_registry import (
    load_manifest,
    load_subagent_specs,
    get_preset_bindings,
    resolve_bindings,
    save_bindings_to_project,
    load_project_bindings,
    export_subagents_for_workspace,
    get_registration_definitions,
    CONFIG_FILENAME,
)
from shared.pipeline import load_graph, derive_status, generate_run_prompt


def test_load_manifest():
    manifest = load_manifest()
    assert manifest["version"] == "2.0"
    assert len(manifest["subagents"]) == 7
    names = [sa["name"] for sa in manifest["subagents"]]
    assert "novel_context_scout" in names
    assert "novel_chapter_writer" in names
    assert "novel_deai_polisher" in names
    assert "novel_persona_auditor" in names
    assert "novel_qc_reviewer" in names
    assert "novel_dungeon_architect" in names
    assert "novel_faction_schemer" in names
    assert "recommended" in manifest["presets"]
    assert "all_flash" in manifest["presets"]
    assert "all_pro" in manifest["presets"]


def test_load_subagent_specs():
    specs = load_subagent_specs()
    assert len(specs) == 7
    for name, spec in specs.items():
        assert "name" in spec
        assert "role" in spec
        assert "node_id" in spec
        assert "tools" in spec
        assert "system_prompt" in spec
        assert len(spec["system_prompt"].strip()) > 50
        assert spec["tools"].get("enable_write_tools") is True


def test_get_preset_bindings():
    rec = get_preset_bindings("recommended")
    assert rec["explore_context"]["tier"] == "flash"
    assert rec["draft_chapter"]["tier"] == "flash"
    assert rec["deai_polish"]["tier"] == "flash"
    assert rec["audit_persona"]["tier"] == "flash"
    assert rec["review_qc"]["tier"] == "pro"

    flash = get_preset_bindings("all_flash")
    for nid, b in flash.items():
        assert b["tier"] == "flash"

    pro = get_preset_bindings("all_pro")
    for nid, b in pro.items():
        assert b["tier"] == "pro"

    with pytest.raises(ValueError):
        get_preset_bindings("non_existent_preset")


def test_resolve_bindings_custom_override():
    # 覆盖 review_qc 为 flash
    resolved = resolve_bindings(
        preset="recommended",
        custom_tiers={"review_qc": "flash"}
    )
    assert resolved["review_qc"]["tier"] == "flash"
    assert resolved["draft_chapter"]["tier"] == "flash"

    # 指定具体的模型字符串
    resolved2 = resolve_bindings(
        preset="recommended",
        custom_tiers={"review_qc": "claude-opus-4.6-thinking"}
    )
    assert resolved2["review_qc"]["tier"] == "pro"
    assert resolved2["review_qc"]["model"] == "claude-opus-4.6-thinking"


def test_save_and_load_project_bindings():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdir = Path(tmpdir)
        # 创建简易 graph.yaml
        graph_data = {
            "version": 1,
            "name": "test-novel",
            "nodes": {
                "explore_context": {"kind": "agent", "prompt": "探索"},
                "draft_chapter": {"kind": "agent", "prompt": "起草"},
                "deai_polish": {"kind": "agent", "prompt": "润色"},
                "review_qc": {"kind": "agent", "prompt": "质检"},
            }
        }
        with open(pdir / "graph.yaml", "w", encoding="utf-8") as f:
            yaml.dump(graph_data, f)

        bindings = get_preset_bindings("recommended")
        cfg_path = save_bindings_to_project(pdir, bindings, preset_name="recommended")
        assert cfg_path.exists()

        # 检查 subagents_config.json
        loaded_cfg = load_project_bindings(pdir)
        assert loaded_cfg is not None
        assert loaded_cfg["preset"] == "recommended"
        assert loaded_cfg["nodes"]["review_qc"]["tier"] == "pro"
        assert loaded_cfg["nodes"]["review_qc"]["subagent_type"] == "novel_qc_reviewer"

        # 检查 graph.yaml 是否被同步修改
        with open(pdir / "graph.yaml", "r", encoding="utf-8") as f:
            updated_graph = yaml.safe_load(f)

        assert updated_graph["nodes"]["explore_context"]["subagent_type"] == "novel_context_scout"
        assert updated_graph["nodes"]["explore_context"]["model_tier"] == "flash"
        assert updated_graph["nodes"]["review_qc"]["subagent_type"] == "novel_qc_reviewer"
        assert updated_graph["nodes"]["review_qc"]["model_tier"] == "pro"


def test_export_subagents_for_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdir = Path(tmpdir)
        exported = export_subagents_for_workspace(pdir)
        assert len(exported) == 7
        for p in exported:
            assert p.exists()
            assert p.suffix == ".json"
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert "name" in data
            assert "system_prompt" in data


def test_get_registration_definitions():
    defs = get_registration_definitions(host="qoder")
    assert len(defs) == 7
    valid_qoder_ids = {"qfmodel", "qmodel_38max", "gfmodel", "gmodel", "dmodel",
                       "dfmodel", "mmodel", "cmodel", "kmodel", "kmodel_latest",
                       "qmodel", "qmodel_latest", "smodel", "inherit"}
    for d in defs:
        assert "name" in d
        assert "description" in d
        assert "system_prompt" in d
        assert "enable_write_tools" in d
        assert d["enable_write_tools"] is True
        assert "_bound_tier" in d
        assert "_role" in d
        # 跨平台提示名概念已删除: 模型唯一来源是宿主
        assert "_bound_model_spec" not in d
        assert d["_host"] == "qoder"
        assert d["_bound_model"] in valid_qoder_ids, f"{d['name']} -> {d['_bound_model']}"
        assert d["_model_origin"] == "role-mapped"

    by_name = {d["name"]: d for d in defs}
    assert by_name["novel_qc_reviewer"]["_bound_model"] == "qmodel_38max"
    assert by_name["novel_chapter_writer"]["_bound_model"] == "qfmodel"

    # Antigravity 与 qoder 对等: 同样有 role_models, 生效模型是 gemini/claude
    defs_ag = get_registration_definitions(host="antigravity")
    ag_by_name = {d["name"]: d for d in defs_ag}
    assert ag_by_name["novel_qc_reviewer"]["_bound_model"] == "gemini-3.8-flash-high"
    assert ag_by_name["novel_qc_reviewer"]["_model_origin"] == "role-mapped"
    assert ag_by_name["novel_chapter_writer"]["_bound_model"] == "gemini-3.1-pro-high"
    for d in defs_ag:
        assert d["_bound_model"].split("-")[0] in ("gemini", "claude")

    # 未知宿主: 无档案 -> 模型为 None, host-unmapped, 绝不回落到别家宿主的名字
    defs_unknown = get_registration_definitions(host="unknown-host")
    for d in defs_unknown:
        assert d["_bound_model"] is None
        assert d["_model_origin"] == "host-unmapped"

    # generic (空档案) 同样视为未配置
    defs_generic = get_registration_definitions(host="generic")
    assert all(d["_bound_model"] is None for d in defs_generic)
    assert all(d["_model_origin"] == "host-unmapped" for d in defs_generic)


def test_build_registration_spec():
    """交接物: 宿主 Agent 拿这一份就能自己完成注册。"""
    spec = build_registration_spec(host="qoder")
    assert spec["host"] == "qoder"
    assert spec["host_source"] == "explicit"
    assert spec["preset"] == "recommended"
    assert spec["project"] is None

    reg = spec["registration"]
    assert reg["mechanism"] == "host-agent-writes-definition-files"
    assert reg["agent_dir"] == ".qoder/agents/"
    assert reg["file_pattern"] == "{name}.md"
    assert "model" in reg["frontmatter_fields"]
    assert reg["requires_new_session"] is True
    assert reg["per_call_model_override"] is False
    assert reg["performed_by"] == "宿主 agent（不是本仓库代码）"
    assert "resolvedModel" in reg["verify_with"]

    assert len(spec["subagents"]) == 7
    assert all(s["_bound_model"] in {"qfmodel", "qmodel_38max"} for s in spec["subagents"])

    spec_ag = build_registration_spec(host="antigravity")
    assert spec_ag["registration"]["mechanism"] == "host-writes-md-frontmatter-files"
    assert spec_ag["registration"]["agent_dir"] == ".agents/agents/"
    assert spec_ag["registration"]["per_call_model_override"] is True
    assert spec_ag["registration"]["requires_new_session"] is False
    assert spec_ag["registration"]["frontmatter_tier_map"]["gemini-3.1-pro-high"] == "pro"

    spec_none = build_registration_spec(host="unknown-host")
    assert spec_none["registration"] == {}


def test_pipeline_integration_with_subagents():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdir = Path(tmpdir)
        yaml_content = """
version: 1
name: test-subagent-pipeline
params:
  chapter_num: 1
  chapter_pad: "01"
nodes:
  review_qc:
    kind: agent
    role: 历史考据主编
    subagent_type: novel_qc_reviewer
    model_tier: pro
    model: claude-opus-4.6-thinking
    prompt: 请严格盲审
    inputs: []
    outputs:
      - output.md
"""
        graph = load_graph(yaml_content, pdir)
        node = graph["nodes"]["review_qc"]
        assert node["subagent_type"] == "novel_qc_reviewer"
        assert node["model_tier"] == "pro"

        import os as _os

        def _prompt_under(host_name):
            old = _os.environ.get(HOST_OVERRIDE_ENV)
            _os.environ[HOST_OVERRIDE_ENV] = host_name
            try:
                return generate_run_prompt("review_qc", node, str(pdir))
            finally:
                if old is None:
                    _os.environ.pop(HOST_OVERRIDE_ENV, None)
                else:
                    _os.environ[HOST_OVERRIDE_ENV] = old

        # Antigravity: 角色绑定权威, 盲审已改绑 gemini flash; 按调用传模型
        prompt = _prompt_under("antigravity")
        assert "novel_qc_reviewer" in prompt
        assert "gemini-3.8-flash-high" in prompt
        assert "pro" in prompt
        assert "invoke_subagent" in prompt

        # Qoder: 角色级绑定优先, 模型必须是宿主真实可用的内置 ID
        prompt_q = _prompt_under("qoder")
        assert "novel_qc_reviewer" in prompt_q
        assert "qmodel_38max" in prompt_q
        assert "角色绑定" in prompt_q
        assert "Agent(subagent_type=novel_qc_reviewer)" in prompt_q
        assert "注册前提" in prompt_q
        assert "invoke_subagent" not in prompt_q


# ---------------------------------------------------------------------------
# 宿主感知 (Host Awareness) 与模型解析测试
# ---------------------------------------------------------------------------

from shared.subagent_registry import (  # noqa: E402
    detect_host,
    load_host_profile,
    host_tier_model,
    host_role_model,
    host_registration,
    resolve_node_model,
    describe_host,
    build_registration_spec,
    HOST_OVERRIDE_ENV,
)


def test_detect_host_priority():
    # 1. 显式覆盖优先于一切指纹
    info = detect_host({HOST_OVERRIDE_ENV: "qoder", "QODER_CLI": "1"})
    assert info["host"] == "qoder"
    assert info["source"] == "env-override"

    # 2. Qoder 指纹
    info = detect_host({"QODER_SESSION_TYPE": "desktop"})
    assert info["host"] == "qoder"
    assert info["source"] == "fingerprint"
    assert info["matched"] == "QODER_SESSION_TYPE"

    # 3. Antigravity 指纹
    info = detect_host({"ANTIGRAVITY_SANDBOX": "1"})
    assert info["host"] == "antigravity"

    # 4. 未知环境
    info = detect_host({"PATH": "/usr/bin"})
    assert info["host"] is None
    assert info["source"] == "unknown"


def test_host_profiles_in_manifest():
    manifest = load_manifest()
    profiles = manifest.get("host_profiles") or {}
    assert "qoder" in profiles
    assert "antigravity" in profiles
    assert "generic" in profiles

    q = load_host_profile("qoder")
    # Qoder 只认内置系统 ID 与 BYOK 裸 UUID; 上游 slug (kimi-k3) 会静默回落,
    # 2026-09-22 已实测复现, 因此档位表里不得出现 slug
    assert host_tier_model(q, "flash") == "qfmodel"
    assert host_tier_model(q, "flash_lite") == "qfmodel"
    assert host_tier_model(q, "pro") == "qmodel_38max"

    # 角色级映射: 7 个角色全部提前写定, 且都是 Qoder 内置 ID
    valid_qoder_ids = {"qfmodel", "qmodel_38max", "gfmodel", "gmodel", "dmodel",
                       "dfmodel", "mmodel", "cmodel", "kmodel", "kmodel_latest",
                       "qmodel", "qmodel_latest", "smodel", "inherit"}
    role_models = q.get("role_models") or {}
    assert len(role_models) == 7
    for role, mid in role_models.items():
        assert role.startswith("novel_"), role
        assert mid in valid_qoder_ids, f"{role} -> {mid} 不是 Qoder 合法内置 ID"
    assert host_role_model(q, "novel_qc_reviewer") == "qmodel_38max"
    assert host_role_model(q, "novel_chapter_writer") == "qfmodel"
    assert host_role_model(q, "不存在的角色") is None

    # 注册契约: 注册动作由宿主 Agent 完成, 且 Qoder 需新开会话
    reg = host_registration(q)
    assert reg.get("mechanism") == "host-agent-writes-definition-files"
    assert reg.get("agent_dir") == ".qoder/agents/"
    assert reg.get("requires_new_session") is True
    assert reg.get("per_call_model_override") is False
    assert "Agent(subagent_type=" in reg.get("dispatch_tool", "")

    ag = load_host_profile("antigravity")
    assert host_tier_model(ag, "flash") == "gemini-3.8-flash-high"
    assert host_tier_model(ag, "pro") == "gemini-3.1-pro-high"
    ag_reg = host_registration(ag)
    assert ag_reg.get("mechanism") == "host-writes-md-frontmatter-files"
    assert ag_reg.get("per_call_model_override") is True

    # 未知宿主无档案
    assert load_host_profile("unknown-host") is None
    assert host_tier_model(None, "flash") is None
    assert host_role_model(None, "novel_qc_reviewer") is None
    assert host_registration(None) == {}


def test_resolve_node_model_branches():
    # 显式 model 是宿主认识的 -> 尊重 (用户为该宿主钉死)
    r = resolve_node_model({"model": "qfmodel"}, "qoder")
    assert r["model"] == "qfmodel"
    assert r["origin"] == "explicit-matched"

    # 显式 model 宿主不认识 (跨宿主名) + 带角色 -> 角色绑定生效, 忽略提示名
    r = resolve_node_model({"model": "gemini-3.8-flash-high",
                            "subagent_type": "novel_chapter_writer"}, "qoder")
    assert r["model"] == "qfmodel"
    assert r["origin"] == "role-mapped"
    assert r["note"] and "忽略" in r["note"]

    # 显式 model 宿主不认识 + 只有 model_tier -> 档位映射
    r = resolve_node_model({"model": "gemini-3.8-flash-high", "model_tier": "flash"}, "qoder")
    assert r["model"] == "qfmodel"
    assert r["origin"] == "tier-mapped"
    assert r["note"] and "忽略" in r["note"]

    # 仅 model_tier -> 档位映射
    r = resolve_node_model({"model_tier": "pro"}, "qoder")
    assert r["model"] == "qmodel_38max"
    assert r["origin"] == "tier-mapped"

    # 上游 slug kimi-k3 宿主不认识, 无角色, 只有档位 -> 按档位解析 (不再"猜名字替换")
    r = resolve_node_model({"model": "kimi-k3", "model_tier": "pro"}, "qoder")
    assert r["model"] == "qmodel_38max"
    assert r["origin"] == "tier-mapped"

    # antigravity 档位映射 -> gemini/claude (与 qoder 对等, 非"默认")
    r = resolve_node_model({"model_tier": "flash"}, "antigravity")
    assert r["model"] == "gemini-3.8-flash-high"
    assert r["origin"] == "tier-mapped"

    # 宿主有档案但未给该角色/档位配置 -> host-unmapped, model 为 None
    r = resolve_node_model({"model": "some-exotic-model"}, "qoder")
    assert r["model"] is None
    assert r["origin"] == "host-unmapped"
    assert r["note"]

    # generic 空档案 -> host-unmapped
    r = resolve_node_model({"model_tier": "flash"}, "generic")
    assert r["model"] is None
    assert r["origin"] == "host-unmapped"

    # 未知宿主 -> no-host, model 为 None (不再透传 gemini 名)
    r = resolve_node_model({"model": "gemini-3.8-flash-high", "model_tier": "flash"}, None)
    assert r["model"] is None
    assert r["origin"] == "no-host"

    # 无 model 无 tier 无角色 -> host-unmapped
    r = resolve_node_model({"role": "x"}, "qoder")
    assert r["model"] is None
    assert r["origin"] == "host-unmapped"


def test_resolve_node_model_role_mapped():
    """宿主感知主路径: 角色模型由宿主 role_models 决定, gemini/claude 只是提示名。"""
    node = {"subagent_type": "novel_qc_reviewer", "model": "gemini-3.8-flash-high"}

    r = resolve_node_model(node, "qoder")
    assert r["model"] == "qmodel_38max"
    assert r["origin"] == "role-mapped"
    assert r["note"] and "绑定" in r["note"] and "忽略" in r["note"]

    # 写手角色 -> qoder flash 档内置 ID (角色绑定优先于节点 model_tier=pro)
    r = resolve_node_model({"subagent_type": "novel_chapter_writer",
                            "model": "claude-opus-4.6-thinking",
                            "model_tier": "pro"}, "qoder")
    assert r["model"] == "qfmodel"
    assert r["origin"] == "role-mapped"

    # 无角色绑定 + 显式 model 宿主认识 -> 尊重显式值 (无角色节点的逃生舱)
    r = resolve_node_model({"model": "qfmodel"}, "qoder")
    assert r["model"] == "qfmodel"
    assert r["origin"] == "explicit-matched"

    # 带角色的节点: role_models 权威, 图谱里遗留的显式 model (哪怕宿主认识) 被忽略
    r = resolve_node_model({"subagent_type": "novel_qc_reviewer",
                            "model": "qfmodel"}, "qoder")
    assert r["model"] == "qmodel_38max"
    assert r["origin"] == "role-mapped"

    # 未知角色名 + 无 model_tier -> host-unmapped (不再从模型名猜档位)
    r = resolve_node_model({"subagent_type": "novel_not_registered",
                            "model": "gemini-3.8-flash-high"}, "qoder")
    assert r["model"] is None
    assert r["origin"] == "host-unmapped"

    # Antigravity 与 qoder 对等: 角色绑定权威, 显式模型(哪怕宿主认识)被忽略
    r = resolve_node_model({"subagent_type": "novel_qc_reviewer",
                            "model": "claude-opus-4.6-thinking"}, "antigravity")
    assert r["model"] == "gemini-3.8-flash-high"
    assert r["origin"] == "role-mapped"

    # 未知宿主 -> no-host, 不透传 gemini 名
    r = resolve_node_model(node, None)
    assert r["model"] is None
    assert r["origin"] == "no-host"


def test_describe_host_lines():
    assert "未识别宿主" in describe_host({"host": None, "source": "unknown", "matched": None})
    line = describe_host({"host": "qoder", "source": "fingerprint",
                          "matched": "QODER_CLI"})
    assert "qoder" in line and "qfmodel" in line and "qmodel_38max" in line
    assert "kimi-k3" not in line  # 无效 slug 不得再出现在宿主摘要里
    assert "角色级绑定: 7 个" in line
    assert describe_host({"host": "generic", "source": "env-override",
                          "matched": None}).startswith("[host]")


def test_generate_run_prompt_host_awareness(tmp_path):
    """强制 Qoder 宿主时, Antigravity 模型名应被替换并附适配说明。"""
    yaml_content = """
version: 1
name: host-aware-test
params: {}
nodes:
  draft_chapter:
    kind: agent
    role: 主笔作家
    model: gemini-3.8-flash-high
    model_tier: flash
    prompt: 写一章
    inputs: []
    outputs:
      - out.md
"""
    graph = load_graph(yaml_content, tmp_path)
    node = graph["nodes"]["draft_chapter"]

    import os as _os
    old = _os.environ.get(HOST_OVERRIDE_ENV)
    _os.environ[HOST_OVERRIDE_ENV] = "qoder"
    try:
        prompt = generate_run_prompt("draft_chapter", node, str(tmp_path))
    finally:
        if old is None:
            _os.environ.pop(HOST_OVERRIDE_ENV, None)
        else:
            _os.environ[HOST_OVERRIDE_ENV] = old

    assert "qfmodel" in prompt
    assert "模型解析说明" in prompt

    # Antigravity 宿主下应保留原模型, 无适配说明
    old = _os.environ.get(HOST_OVERRIDE_ENV)
    _os.environ[HOST_OVERRIDE_ENV] = "antigravity"
    try:
        prompt = generate_run_prompt("draft_chapter", node, str(tmp_path))
    finally:
        if old is None:
            _os.environ.pop(HOST_OVERRIDE_ENV, None)
        else:
            _os.environ[HOST_OVERRIDE_ENV] = old
    assert "gemini-3.8-flash-high" in prompt
    assert "模型解析说明" not in prompt


def test_derive_status_records_model_origin(tmp_path):
    yaml_content = """
version: 1
name: origin-test
params: {}
nodes:
  solo:
    kind: agent
    role: 独行节点
    model: gemini-3.8-flash-high
    model_tier: flash
    prompt: 做
    inputs: []
    outputs:
      - o.md
"""
    graph = load_graph(yaml_content, tmp_path)
    state = derive_status(graph, tmp_path, None,
                          host_info={"host": "qoder", "source": "env-override",
                                     "matched": HOST_OVERRIDE_ENV})
    entry = state["nodes"]["solo"]
    assert entry["model"] == "qfmodel"
    assert entry["model_tier"] == "flash"
    assert entry["model_origin"] == "tier-mapped"
    assert entry["model_note"]
