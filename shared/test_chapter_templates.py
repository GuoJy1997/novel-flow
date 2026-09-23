# -*- coding: utf-8 -*-
"""唯一单章模板的契约测试；只展开配置，不执行节点或请求 API。"""
import copy
import importlib
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHAIN = [
    "explore_context", "scene_beats", "draft_chapter", "deai_polish",
    "check_zhuque", "zhuque_api_final", "audit_persona", "review_qc",
    "author_accept", "novel_stats",
]
ROLES = {
    "explore_context": "novel_context_scout",
    "draft_chapter": "novel_chapter_writer",
    "deai_polish": "novel_deai_polisher",
    "audit_persona": "novel_persona_auditor",
    "review_qc": "novel_qc_reviewer",
}
PARAM_KEYS = {
    "chapter_num", "chapter_title", "volume_name", "genre", "tone", "target_words",
    "chapter_workspace", "chapter_output", "voice_sample",
}


def test_template_api_available():
    assert (ROOT / "shared/chapter_templates.py").is_file(), "单章模板 API 尚未实现"
    module = importlib.import_module("chapter_templates")
    assert callable(module.load_template)
    assert callable(module.instantiate)
    assert callable(module.reference)


@pytest.fixture
def templates():
    return importlib.import_module("chapter_templates")


def assert_chain(graph):
    assert list(graph["nodes"]) == CHAIN
    for i, node_id in enumerate(CHAIN):
        assert graph["nodes"][node_id].get("after", []) == ([] if i == 0 else [CHAIN[i - 1]])


def test_complete_chain_and_polished_manuscript_is_the_archive_source(templates):
    from pipeline import load_graph

    graph = templates.instantiate(params={"chapter_num": 12, "chapter_title": "回声"})
    assert_chain(graph)
    nodes = graph["nodes"]
    assert nodes["explore_context"]["inputs"] == []
    assert nodes["draft_chapter"]["inputs"] == [
        "工作区/第12章/01_状态上下文.md", "工作区/第12章/01_5_分场节拍表.md",
    ]
    assert nodes["deai_polish"]["inputs"] == [
        "工作区/第12章/02_正文初稿.md", "资产/voice_sample.md",
    ]
    assert nodes["author_accept"]["inputs"][0] == "工作区/第12章/03_去AI味润色稿.md"
    assert nodes["author_accept"]["outputs"] == ["正文/第一卷/第12章_回声.md"]
    assert nodes["novel_stats"]["inputs"] == nodes["author_accept"]["outputs"]
    assert "template" not in graph
    assert_chain(load_graph(yaml.safe_dump(graph, allow_unicode=True, sort_keys=False)))


@pytest.mark.parametrize('mutate', [
    lambda n: n['author_accept'].update(kind='command', run=['echo', 'skip']),
    lambda n: n['audit_persona'].update(skills=[]),
    lambda n: n['review_qc'].update(assertion={}) or n['review_qc'].pop('assert'),
    lambda n: n['zhuque_api_final']['assert'].update(min_score=0),
    lambda n: n['author_accept'].update(inputs=['{chapter_workspace}/02_正文初稿.md']),
    lambda n: n['author_accept'].update(outputs=['{chapter_workspace}/fake.md']),
])
def test_self_consistent_snapshot_cannot_remove_quality_or_human_gates(templates, mutate):
    snapshot = templates.load_template()
    mutate(snapshot['nodes'])
    with pytest.raises(ValueError):
        templates.instantiate(snapshot=snapshot)


def test_pipeline_expands_reference_before_applying_chapter_paths(templates):
    import pipeline
    ref = templates.reference()
    graph = pipeline.load_graph(yaml.safe_dump(ref), override_params={'chapter_num': 52})
    assert_chain(graph)
    assert graph['params']['chapter_pad'] == '52'
    assert graph['nodes']['draft_chapter']['outputs'] == ['工作区/第52章/02_正文初稿.md']
    ref['nodes'] = {'replacement': {'kind': 'human', 'ask': 'bypass'}}
    with pytest.raises(pipeline.ValidationError):
        pipeline.load_graph(yaml.safe_dump(ref))


def test_model_bindings_and_existing_skills_are_shared_across_chapters(templates):
    first = templates.instantiate(params={"chapter_num": 1})
    second = templates.instantiate(params={"chapter_num": 54, "genre": "武侠"})
    agents = [nid for nid, node in first["nodes"].items() if node["kind"] == "agent"]
    assert len(agents) == 6
    assert first["nodes"]["scene_beats"]["model_tier"] == "flash"
    for nid in agents:
        left, right = first["nodes"][nid], second["nodes"][nid]
        assert "model" not in left and "model" not in right
        assert left.get("subagent_type") == right.get("subagent_type")
        assert left.get("model_tier") == right.get("model_tier")
        if nid in ROLES:
            assert left["subagent_type"] == ROLES[nid]
        assert left["skills"] == right["skills"]
        assert len(left["skills"]) >= 2
        for skill in left["skills"]:
            assert (ROOT / "skills" / skill / "SKILL.md").is_file()
    assert first["nodes"]["deai_polish"]["outputs"] != second["nodes"]["deai_polish"]["outputs"]


def test_locked_snapshot_and_overrides_are_not_mutated_or_reloaded(templates, monkeypatch):
    snapshot = templates.load_template()
    snapshot["nodes"]["draft_chapter"]["prompt"] += "\n锁定版本独有要求。"
    before = copy.deepcopy(snapshot)
    params = {"chapter_num": 51, "chapter_title": "回响"}
    overrides = {"draft_chapter": {
        "prompt_append": "本章补充：保持克制。",
        "inputs_add": ["正文/第一卷/第50章_旧稿.md"],
    }}
    original_overrides = copy.deepcopy(overrides)

    def no_reload(*args, **kwargs):
        pytest.fail("锁定快照不得重新读取当前模板")

    monkeypatch.setattr(templates, "load_template", no_reload)
    first = templates.instantiate(params=params, overrides=overrides, snapshot=snapshot)
    second = templates.instantiate(params={"chapter_num": 52}, snapshot=snapshot)
    draft = first["nodes"]["draft_chapter"]
    assert "锁定版本独有要求。" in draft["prompt"]
    assert draft["prompt"].endswith("本章补充：保持克制。")
    assert draft["inputs"][-1] == "正文/第一卷/第50章_旧稿.md"
    assert "本章补充" not in second["nodes"]["draft_chapter"]["prompt"]
    assert len(second["nodes"]["draft_chapter"]["inputs"]) == 2
    draft["skills"].append("instance-only")
    assert "instance-only" not in second["nodes"]["draft_chapter"]["skills"]
    assert snapshot == before
    assert overrides == original_overrides
    assert params == {"chapter_num": 51, "chapter_title": "回响"}


def test_raw_template_is_portable_and_fresh_on_each_load(templates):
    raw = templates.load_template()
    for node in raw["nodes"].values():
        assert "model" not in node
        if node["kind"] == "command":
            assert node["run"][0] == "{python_executable}"
            assert node["run"][1].startswith("{engine_shared}/")
    assert set(raw["params"]) == PARAM_KEYS
    raw["nodes"]["draft_chapter"]["skills"].clear()
    assert templates.load_template()["nodes"]["draft_chapter"]["skills"]


def test_external_project_paths_and_engine_commands_are_materialized(templates, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    graph = templates.instantiate(params={
        "chapter_num": 54, "chapter_title": "引信", "volume_name": "第三卷",
        "chapter_workspace": "工作区/生产任务/插章/第{chapter_pad}章",
        "chapter_output": "正文/{volume_name}/第{chapter_pad3}章_旧标题.md",
        "voice_sample": "资料\\作者样本.md",
    }, overrides={"explore_context": {"inputs_add": ["正文/{volume_name}/第{chapter_prev_pad3}章_前章.md"]}})
    nodes = graph["nodes"]
    assert nodes["explore_context"]["inputs"] == ["正文/第三卷/第053章_前章.md"]
    assert nodes["deai_polish"]["inputs"][1] == "资料/作者样本.md"
    assert nodes["author_accept"]["outputs"] == ["正文/第三卷/第054章_旧标题.md"]
    assert nodes["author_accept"]["inputs"][0] == "工作区/生产任务/插章/第54章/03_去AI味润色稿.md"
    for node in nodes.values():
        if node["kind"] == "command":
            assert Path(node["run"][0]) == Path(sys.executable)
            assert Path(node["run"][1]).parent == ROOT / "shared"
            assert Path(node["run"][1]).is_file()
    assert nodes["novel_stats"]["run"][5] == "正文/第三卷/第054章_旧标题.md"


@pytest.mark.parametrize("target", [500, 1200, 3200, 6000, 20000])
def test_only_manuscript_word_limits_scale_with_target(templates, target):
    base = templates.instantiate()
    graph = templates.instantiate(params={"target_words": target})
    for nid, node in graph["nodes"].items():
        rules = node.get("assert", {})
        if nid in ("draft_chapter", "deai_polish"):
            assert 0.7 * target <= rules["min_words"] < target
            assert target < rules["max_words"] <= 1.5 * target
            assert rules["forbidden_terms"] == base["nodes"][nid]["assert"]["forbidden_terms"]
        else:
            assert rules == base["nodes"][nid].get("assert", {})
    assert graph["nodes"]["check_zhuque"]["assert"]["min_score"] == 80
    assert graph["nodes"]["zhuque_api_final"]["assert"]["min_score"] == 60
    assert graph["nodes"]["audit_persona"]["assert"]["min_scores"]["epistemic_boundary"] == 80
    assert graph["nodes"]["review_qc"]["assert"]["min_score"] == 80


@pytest.mark.parametrize("field", [
    "model", "model_tier", "subagent_type", "skills", "kind", "after", "run",
    "outputs", "inputs", "assert", "prompt", "role", "inplace", "unknown",
])
def test_overrides_cannot_replace_structure_or_quality_rules(templates, field):
    with pytest.raises(ValueError):
        templates.instantiate(overrides={"draft_chapter": {field: "replacement"}})


@pytest.mark.parametrize("overrides", [
    [], "", False, {"missing": {}}, {"draft_chapter": None},
    {"draft_chapter": []}, {"draft_chapter": {"prompt_append": 1}},
    {"draft_chapter": {"prompt_append": None}},
    {"draft_chapter": {"inputs_add": "资料.md"}},
    {"draft_chapter": {"inputs_add": [1]}},
    {"draft_chapter": {"inputs_add": [""]}},
    {"draft_chapter": {"inputs_add": None}},
    {"author_accept": {"prompt_append": ""}},
    {"check_zhuque": {"prompt_append": "跳过检测"}},
])
def test_override_types_and_agent_only_prompt_append_are_strict(templates, overrides):
    with pytest.raises(ValueError):
        templates.instantiate(overrides=overrides)


@pytest.mark.parametrize("path", [
    "../secret", "资料/../../secret", "..\\secret", "资料\\..\\secret",
    "/etc/passwd", "C:/secret", "C:\\secret", "C:secret", "\\secret",
    "\\\\server\\share\\secret", "//server/share/secret", "资料\x00.md",
    "资料\n.md", "资料/.. /secret", "资料/file.md:stream", "~/secret",
    "{engine_shared}/secret", "{python_executable}", "{missing}/secret",
])
def test_input_path_escape_and_unresolved_placeholders_are_rejected(templates, path):
    with pytest.raises(ValueError):
        templates.instantiate(overrides={"explore_context": {"inputs_add": [path]}})


@pytest.mark.parametrize("key", ["chapter_workspace", "chapter_output", "voice_sample"])
@pytest.mark.parametrize("path", ["../outside", "..\\outside", "D:/outside", "/outside", "{engine_shared}/outside"])
def test_param_paths_cannot_escape_project(templates, key, path):
    with pytest.raises(ValueError):
        templates.instantiate(params={key: path})
    with pytest.raises(ValueError):
        templates.reference(params={key: path})


@pytest.mark.parametrize("params", [
    [], False, "", {"chapter_num": True}, {"chapter_num": "51"}, {"chapter_num": 0},
    {"chapter_num": 1.5}, {"target_words": 0}, {"target_words": True},
    {"target_words": 499}, {"target_words": 20001}, {"target_words": "3200"},
    {"chapter_title": "../坏标题"}, {"chapter_title": "坏\\标题"},
    {"chapter_title": "{engine_shared}"}, {"chapter_title": ""},
    {"volume_name": "../卷"}, {"voice_sample": None}, {"genre": []}, {"tone": 1},
    {"chapter_pad": "051"}, {"chapter_pad3": "051"}, {"chapter_prev_num": 0},
    {"volume_num": 3}, {"python_executable": "evil"}, {"engine_shared": "evil"},
    {"draft_min_words": 0}, {"review": {"min_score": 0}},
    {"chapter_workspace": "{chapter_output}", "chapter_output": "{chapter_workspace}"},
])
def test_param_types_and_derived_param_overrides_are_rejected(templates, params):
    with pytest.raises(ValueError):
        templates.instantiate(params=params)
    with pytest.raises(ValueError):
        templates.reference(params=params)


@pytest.mark.parametrize("template_id", ["other", "../chapter-v1", "chapter-v1.yaml", "", None, 1])
def test_only_registered_template_id_is_allowed(templates, template_id):
    with pytest.raises(ValueError):
        templates.load_template(template_id)
    with pytest.raises(ValueError):
        templates.instantiate(template_id, snapshot=templates.load_template())


def test_reference_preserves_defaults_without_derived_params_and_is_independent(templates):
    params = {"chapter_num": 3, "genre": "武侠"}
    ref = templates.reference(params)
    assert set(ref) == {"version", "name", "template", "params", "overrides"}
    assert ref["version"] == 1 and ref["template"] == "chapter-v1"
    assert set(ref["params"]) == PARAM_KEYS
    assert ref["params"]["chapter_num"] == 3
    assert "设定/世界观/" in ref["overrides"]["explore_context"]["inputs_add"]
    graph = templates.instantiate(ref["template"], ref["params"], ref["overrides"])
    assert_chain(graph)
    assert graph["nodes"]["author_accept"]["outputs"] == ["正文/第一卷/第03章_沉默信标.md"]
    ref["overrides"]["explore_context"]["inputs_add"].clear()
    ref["params"]["genre"] = "已修改"
    assert templates.reference()["overrides"]["explore_context"]["inputs_add"]
    assert templates.reference()["params"]["genre"] == "科幻悬疑"
    assert params == {"chapter_num": 3, "genre": "武侠"}


def test_scaffold_and_demo_reference_the_complete_template(templates, tmp_path):
    import scaffold_novel

    assert scaffold_novel.DEFAULT_GRAPH["template"] == "chapter-v1"
    assert "nodes" not in scaffold_novel.DEFAULT_GRAPH
    baseline = copy.deepcopy(scaffold_novel.DEFAULT_GRAPH)
    for slug, genre in [("one", "武侠"), ("two", "科幻")]:
        target = tmp_path / slug
        scaffold_novel.scaffold_novel(target, "测试项目", genre, "测试主角", "仅测试脚手架")
        ref = yaml.safe_load((target / "graph.yaml").read_text(encoding="utf-8"))
        assert "nodes" not in ref
        assert ref["params"]["genre"] == genre
        assert_chain(templates.instantiate(ref["template"], ref["params"], ref["overrides"]))
    assert scaffold_novel.DEFAULT_GRAPH == baseline
    demo = yaml.safe_load((ROOT / "projects/demo-novel/graph.yaml").read_text(encoding="utf-8"))
    assert demo["template"] == "chapter-v1" and "nodes" not in demo
    assert set(demo["params"]) <= PARAM_KEYS
    assert demo["params"]["chapter_title"] == "沉默信标"
    assert demo["params"]["target_words"] == 3200
    graph = templates.instantiate(demo["template"], demo["params"], demo["overrides"])
    assert_chain(graph)
    assert "设定/事实账本/snapshot.json" in graph["nodes"]["explore_context"]["inputs"]
