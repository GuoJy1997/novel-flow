# -*- coding: utf-8 -*-
"""小说流水线核心引擎自动化测试套件。"""
import json
import shutil
import tempfile
from pathlib import Path
import pytest
import yaml

from pipeline import (
    ValidationError,
    count_text_words,
    derive_status,
    evaluate_asserts,
    hash_directory,
    hash_file,
    hash_path,
    load_graph,
    normalize_params,
    parse_scores_from_text,
)


def test_hash_file_and_directory():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f1 = root / "a.txt"
        f1.write_text("hello novel", encoding="utf-8")
        h1 = hash_file(f1)
        assert h1.startswith("sha256:")

        sub = root / "sub"
        sub.mkdir()
        f2 = sub / "b.txt"
        f2.write_text("chapter 1", encoding="utf-8")

        dh = hash_directory(root)
        assert dh.startswith("sha256:")

        # 修改内容哈希必定改变
        f2.write_text("chapter 1 modified", encoding="utf-8")
        dh2 = hash_directory(root)
        assert dh != dh2


def test_count_text_words():
    text = "这是一段测试文字，包含十五个中文字符和一个 EnglishWord。"
    # 中文字符 23 个 + 1 个英文单词 = 24
    cnt = count_text_words(text)
    assert cnt > 20

    # 标题行剔除测试
    md_text = "# 第一章 启程\n\n正文开始。"
    cnt2 = count_text_words(md_text)
    assert cnt2 == 9  # "第一章" (3) + "启程" (2) + "正文开始" (4) = 9


def test_parse_scores_from_text():
    sample = """
审查结论：
本章整体节奏很好。
SCORES: {"overall": 86.5, "lore": 90, "ooc": 88}
"""
    scores = parse_scores_from_text(sample)
    assert scores is not None
    assert scores["overall"] == 86.5
    assert scores["lore"] == 90.0

    no_score = "没有分数的普通文稿"
    assert parse_scores_from_text(no_score) is None


def test_load_graph_valid_and_cycles():
    valid_yaml = """
version: 1
name: test
nodes:
  n1:
    kind: agent
    role: writer
    inputs: [in.txt]
    outputs: [out.txt]
  n2:
    kind: command
    after: [n1]
    run: [python, test.py]
"""
    data = load_graph(valid_yaml)
    assert "n1" in data["nodes"]
    assert "n2" in data["nodes"]

    # 环检测
    cycle_yaml = """
version: 1
nodes:
  a:
    kind: agent
    after: [b]
  b:
    kind: agent
    after: [a]
"""
    with pytest.raises(ValidationError, match="循环依赖"):
        load_graph(cycle_yaml)

    # 路径越界检测
    escape_yaml = """
version: 1
nodes:
  a:
    kind: agent
    inputs: ["../../secret.txt"]
"""
    with pytest.raises(ValidationError, match="父级目录跳转"):
        load_graph(escape_yaml)


def test_derive_status_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        in_file = root / "outline.md"
        in_file.write_text("大纲内容", encoding="utf-8")

        raw_graph = """
version: 1
nodes:
  gather:
    kind: agent
    inputs: [outline.md]
    outputs: [context.md]
  draft:
    kind: agent
    after: [gather]
    inputs: [context.md]
    outputs: [ch01.md]
    assert:
      min_words: 10
  human_gate:
    kind: human
    after: [draft]
    ask: 审核章节
    inputs: [ch01.md]
"""
        graph = load_graph(raw_graph)

        # 1. 初始状态：context.md 未生成 -> gather 为 stale；draft 的输入缺失 -> blocked
        s1 = derive_status(graph, root)
        assert s1["nodes"]["gather"]["status"] == "stale"
        assert s1["nodes"]["draft"]["status"] == "blocked"
        assert s1["nodes"]["human_gate"]["status"] == "blocked"

        # 2. 生成 context.md -> gather 变为 current（如果基线记录了当前输入）
        (root / "context.md").write_text("上下文任务卡", encoding="utf-8")
        # 写入基线让 gather 认为自身就绪
        s2 = derive_status(graph, root, s1)
        # 模拟 gather 执行完成落盘
        s1["nodes"]["gather"]["inputs"] = {"outline.md": hash_file(in_file)}
        s2 = derive_status(graph, root, s1)
        assert s2["nodes"]["gather"]["status"] == "current"
        # draft 的输出 ch01.md 尚未生成，所以 draft 是 stale
        assert s2["nodes"]["draft"]["status"] == "stale"

        # 3. 模拟 draft 生成且通过字数 assert
        (root / "ch01.md").write_text("这是第一章的正式正文内容，字数超过十个汉字了！", encoding="utf-8")
        s2["nodes"]["draft"]["inputs"] = {"context.md": hash_file(root / "context.md")}
        s3 = derive_status(graph, root, s2)
        assert s3["nodes"]["draft"]["status"] == "current"
        assert s3["nodes"]["human_gate"]["status"] == "pending-human"

        # 4. 模拟人工审批 ackAt
        s3["nodes"]["human_gate"]["ackAt"] = "2026-09-12T05:00:00Z"
        s3["nodes"]["human_gate"]["inputs"] = {"ch01.md": hash_file(root / "ch01.md")}
        s4 = derive_status(graph, root, s3)
        assert s4["nodes"]["human_gate"]["status"] == "current"

        # 5. 上游正文被篡改，human_gate 的审批立刻失效回到 pending-human
        (root / "ch01.md").write_text("正文被篡改了，需要重新审批！", encoding="utf-8")
        s5 = derive_status(graph, root, s4)
        assert s5["nodes"]["human_gate"]["status"] == "pending-human"


def test_evaluate_asserts_score():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = root / "review.md"
        rep.write_text("审查不合格\nSCORES: {\"overall\": 72}", encoding="utf-8")

        node_fail = {
            "outputs": ["review.md"],
            "assert": {"min_score": 80, "score_field": "overall"}
        }
        fails = evaluate_asserts(node_fail, root)
        assert len(fails) == 1
        assert "得分 72.0 < 最低门槛 80.0" in fails[0]

        rep.write_text("审查合格\nSCORES: {\"overall\": 91}", encoding="utf-8")
        assert len(evaluate_asserts(node_fail, root)) == 0


def test_evaluate_asserts_forbidden_terms():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        draft = root / "draft.md"
        draft.write_text("顾君转过头对张洋怒喝：“给我闭嘴！”", encoding="utf-8")

        node = {
            "outputs": ["draft.md"],
            "assert": {"forbidden_terms": ["闭嘴", "给我闭嘴"]}
        }
        fails = evaluate_asserts(node, root)
        assert len(fails) >= 1
        assert "命中违规禁用词" in fails[0]

        draft.write_text("老顾转过头，拍了拍张洋的肩膀，递过去一个警惕的眼神。", encoding="utf-8")
        assert len(evaluate_asserts(node, root)) == 0


def test_evaluate_asserts_min_scores_matrix():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        rep = root / "report.md"
        rep.write_text("SCORES: {\"overall\": 90, \"persona\": 75, \"addressing\": 95}", encoding="utf-8")

        node = {
            "outputs": ["report.md"],
            "assert": {
                "min_scores": {
                    "overall": 80,
                    "persona": 80,
                    "addressing": 80
                }
            }
        }
        fails = evaluate_asserts(node, root)
        assert len(fails) == 1
        assert "persona 得分 75.0 < 最低门槛 80.0" in fails[0]

        rep.write_text("SCORES: {\"overall\": 90, \"persona\": 85, \"addressing\": 95}", encoding="utf-8")
        assert len(evaluate_asserts(node, root)) == 0


def test_evaluate_asserts_addressing_and_epistemic():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        draft = root / "ch10.md"
        # 1. 称谓违规：张洋叫顾君全名
        draft.write_text("张洋道：“顾君，你看前面的黑烟！”", encoding="utf-8")
        node = {
            "outputs": ["ch10.md"],
            "assert": {"addressing_check": True}
        }
        fails = evaluate_asserts(node, root)
        assert any("张洋与顾君为生死发小" in f for f in fails)

        # 2. 情绪违规：秦华狂暴咆哮“给我闭嘴”
        draft.write_text("秦华怒喝道：“给我闭嘴，别出声！”", encoding="utf-8")
        fails = evaluate_asserts(node, root)
        assert any("严禁出现低级狂暴咆哮式" in f for f in fails)

        # 3. 知情越界：第10章灾变爆发前出现“丧尸”
        draft.write_text("老顾低声道：“前面有丧尸。”", encoding="utf-8")
        node_ep = {
            "outputs": ["ch10.md"],
            "_params": {"chapter_num": 10},
            "assert": {"epistemic_check": True}
        }
        fails_ep = evaluate_asserts(node_ep, root)
        assert any("绝对禁止出现『丧尸/尸变/行尸』" in f for f in fails_ep)

        # 4. 合规文本通过
        draft.write_text("张洋压低声音道：“老顾，看那边。”顾君掌心向下微微一按，示意噤声。", encoding="utf-8")
        node_clean = {
            "outputs": ["ch10.md"],
            "_params": {"chapter_num": 10},
            "assert": {"addressing_check": True, "epistemic_check": True}
        }
        assert len(evaluate_asserts(node_clean, root)) == 0


def test_normalize_params_and_chapter_override():
    # 1. 默认空配置派生
    p1 = normalize_params({})
    assert p1["volume_num"] == 1
    assert p1["volume_pad"] == "01"
    assert p1["volume_name"] == "第一卷"

    # 2. 覆盖章节号为 11
    p2 = normalize_params({"chapter_num": 1, "chapter_pad": "01"}, override_params={"chapter_num": 11})
    assert p2["chapter_num"] == 11
    assert p2["chapter_pad"] == "11"
    assert p2["volume_name"] == "第一卷"

    # 3. 覆盖分卷
    p3 = normalize_params({}, override_params={"chapter_num": 5, "volume_num": 2, "volume_name": "第二卷"})
    assert p3["chapter_pad"] == "05"
    assert p3["volume_pad"] == "02"
    assert p3["volume_name"] == "第二卷"


def test_directory_hash_detects_lore_changes():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        lore_dir = root / "设定" / "世界观"
        lore_dir.mkdir(parents=True)
        rule1 = lore_dir / "法则.md"
        rule1.write_text("灵能等级：初级、中级、高级", encoding="utf-8")

        work_dir = root / "工作区" / "第01章"
        work_dir.mkdir(parents=True)
        out_file = work_dir / "context.md"

        raw_graph = """
version: 1
nodes:
  gather:
    kind: agent
    inputs: ["设定/世界观/"]
    outputs: ["工作区/第01章/context.md"]
"""
        graph = load_graph(raw_graph, root)
        s1 = derive_status(graph, root)
        assert s1["nodes"]["gather"]["status"] == "stale"

        # 生成输出并形成基线
        out_file.write_text("任务卡完成", encoding="utf-8")
        s1["nodes"]["gather"]["inputs"] = {"设定/世界观/": hash_path(lore_dir)}
        s2 = derive_status(graph, root, s1)
        assert s2["nodes"]["gather"]["status"] == "current"

        # 在 设定/世界观/ 下新增文件（模拟设定演进或规则补充）
        rule2 = lore_dir / "势力.md"
        rule2.write_text("新增黑星财团设定", encoding="utf-8")

        # 再次推导状态：由于目录内容哈希变动，gather 必须自动变为 stale
        s3 = derive_status(graph, root, s2)
        assert s3["nodes"]["gather"]["status"] == "stale"


def test_dynamic_chapter_graph_expansion():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw_graph = """
version: 1
params:
  chapter_num: 1
  chapter_pad: "01"
  volume_name: "第一卷"
nodes:
  draft:
    kind: agent
    inputs: ["设定/大纲/第{chapter_pad}章细纲.md"]
    outputs: ["工作区/第{chapter_pad}章/ch{chapter_pad}_raw.md"]
"""
        # 未覆盖时使用第 1 章
        g1 = load_graph(raw_graph, root)
        assert g1["params"]["chapter_pad"] == "01"

        # 动态覆盖为第 11 章
        g11 = load_graph(raw_graph, root, override_params={"chapter_num": 11})
        assert g11["params"]["chapter_pad"] == "11"
        assert g11["params"]["chapter_num"] == 11

        # 验证节点产物路径推导
        draft_node = g11["nodes"]["draft"]
        draft_node["_params"] = g11["params"]
        from pipeline import _expand_params
        expanded_out = _expand_params(draft_node["outputs"][0], g11["params"])
        assert expanded_out == "工作区/第11章/ch11_raw.md"

def test_running_node_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw_graph = """
version: 1
params:
  chapter_num: 1
nodes:
  draft:
    kind: agent
    inputs: []
    outputs: ["output.md"]
"""
        (root / "graph.yaml").write_text(raw_graph, encoding="utf-8")
        from pipeline import cmd_start, cmd_finish, load_state

        # 启动 draft 节点
        assert cmd_start("draft", str(root)) == 0
        state = load_state(root)
        assert state.get("running_node") == "draft"
        assert state["nodes"]["draft"]["status"] == "running"
        assert state["nodes"]["draft"]["running"] is True

        # 结束 draft 节点
        assert cmd_finish("draft", str(root)) == 0
        state2 = load_state(root)
        assert state2.get("running_node") is None
def test_state_filename_derivation():
    from pipeline import state_filename_for
    assert state_filename_for("graph.yaml") == "pipeline.json"
    assert state_filename_for("graph.yml") == "pipeline.json"
    assert state_filename_for("volume_graph.yaml") == "volume_pipeline.json"
    assert state_filename_for("volume.yaml") == "volume_pipeline.json"
    assert state_filename_for("custom_task_graph.yaml") == "custom_task_pipeline.json"


def test_multi_workflow_isolation():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        chapter_graph = """
version: 1
params:
  chapter_num: 1
nodes:
  draft:
    kind: agent
    inputs: []
    outputs: ["ch01.md"]
"""
        volume_graph = """
version: 1
params:
  volume_num: 1
nodes:
  volume_premise:
    kind: agent
    inputs: []
    outputs: ["vol01.md"]
"""
        (root / "graph.yaml").write_text(chapter_graph, encoding="utf-8")
        (root / "volume_graph.yaml").write_text(volume_graph, encoding="utf-8")

        from pipeline import cmd_status, load_state, cmd_start, cmd_finish

        # 运行 chapter graph
        assert cmd_status(str(root), graph_file="graph.yaml") == 0
        ch_state = load_state(root, graph_file="graph.yaml")
        assert "draft" in ch_state["nodes"]
        assert "volume_premise" not in ch_state["nodes"]
        assert (root / "pipeline.json").is_file()

        # 运行 volume graph
        assert cmd_status(str(root), graph_file="volume_graph.yaml") == 0
        vol_state = load_state(root, graph_file="volume_graph.yaml")
        assert "volume_premise" in vol_state["nodes"]
        assert "draft" not in vol_state["nodes"]
        assert (root / "volume_pipeline.json").is_file()

        # 验证 start 与 finish 在 volume 状态下完全独立
        assert cmd_start("volume_premise", str(root), graph_file="volume_graph.yaml") == 0
        vol_state2 = load_state(root, graph_file="volume_graph.yaml")
        assert vol_state2.get("running_node") == "volume_premise"
        # chapter pipeline 不受任何影响
        ch_state2 = load_state(root, graph_file="graph.yaml")
        assert ch_state2.get("running_node") is None

        assert cmd_finish("volume_premise", str(root), graph_file="volume_graph.yaml") == 0
        vol_state3 = load_state(root, graph_file="volume_graph.yaml")
        assert vol_state3.get("running_node") is None


def test_demo_novel_graph_single_core_skill_and_scene_beats():
    """验证 demo-novel 的工作流配置严格遵守 1 节点 = 1 专属核心 Skill，且 scene_beats 成功解耦。"""
    demo_dir = Path("projects/demo-novel")
    if not demo_dir.exists():
        pytest.skip("projects/demo-novel not found")

    ch_graph = load_graph((demo_dir / "graph.yaml").read_text(encoding="utf-8"))
    nodes = ch_graph["nodes"]

    # 1. 验证 scene_beats 解耦
    assert "scene_beats" in nodes
    assert nodes["scene_beats"]["after"] == ["gather_state"]
    assert nodes["draft_chapter"]["after"] == ["scene_beats"]
    assert "工作区/第{chapter_pad}章/01_5_分场节拍表.md" in nodes["scene_beats"]["outputs"]
    assert "工作区/第{chapter_pad}章/01_5_分场节拍表.md" in nodes["draft_chapter"]["inputs"]

    # 2. 验证每个 agent 节点严格具备且仅具备 1 个专属核心 Skill
    expected_ch_skills = {
        "gather_state": "novel-context-curator",
        "scene_beats": "novel-scene-tension",
        "draft_chapter": "novel-style-narrator",
        "deai_polish": "novel-deai-humanizer",
        "audit_persona": "novel-character-guardian",
        "review_qc": "novel-editorial-reviewer",
    }
    for node_id, exp_skill in expected_ch_skills.items():
        skills = nodes[node_id].get("skills", [])
        assert len(skills) == 1, f"节点 [{node_id}] 的 skills 数量应为 1，实际为 {skills}"
        assert skills[0] == exp_skill, f"节点 [{node_id}] 应分配技能 {exp_skill}，实际为 {skills[0]}"

    # 3. 验证 volume_graph.yaml 同样严格单 Skill 映射
    vol_graph = load_graph((demo_dir / "volume_graph.yaml").read_text(encoding="utf-8"))
    vol_nodes = vol_graph["nodes"]
    expected_vol_skills = {
        "volume_premise": "novel-plot-architect",
        "dungeon_physics": "novel-dungeon-physics",
        "faction_agenda_matrix": "novel-faction-schemer",
        "revelation_ladder": "story-suspense-investigation",
        "pacing_beats": "novel-scene-tension",
        "clue_ledger_sync": "novel-memory-ledger",
    }
    for node_id, exp_skill in expected_vol_skills.items():
        skills = vol_nodes[node_id].get("skills", [])
        assert len(skills) == 1, f"分卷节点 [{node_id}] 的 skills 数量应为 1，实际为 {skills}"
        assert skills[0] == exp_skill, f"分卷节点 [{node_id}] 应分配技能 {exp_skill}，实际为 {skills[0]}"


def test_check_humanness_algorithm():
    """验证朱雀检测核心算法指标 (Burstiness, Adverb, Negation, Clichés) 的精确度与打分判定。"""
    from check_humanness import (
        calculate_burstiness,
        calculate_adverb_density,
        check_syntactic_patterns,
        evaluate_humanness,
        extract_clean_sentences,
        generate_markdown_report,
    )

    # 1. 纯 AI 高度拟合样本（匀速句长、二元否定、说明套话、副词扎堆）
    ai_sample = (
        "夜幕降临，整个城市仿佛在这一刻凝固了。\n"
        "他缓缓地抬起头，眼神中闪烁着坚定的光彩。\n"
        "这不仅是一场关乎生死的较量，更是一次心灵的救赎。\n"
        "他的心中充斥着恐惧、焦虑和不安。\n"
        "他微微地叹了一口气，心中不由得升起一阵苍凉。\n"
        "这并不是失败，而是为了下一次更加辉煌的胜利。\n"
        "不可否认的是，空气中弥漫着危险的气息。\n"
        "他悄然地向前迈出了一步，静静地等待着命运的宣判。"
    )

    res_ai = evaluate_humanness(ai_sample, "ai_sample.md")
    assert res_ai["overall_score"] < 65.0, f"AI 样本得分应低于 65，实际为 {res_ai['overall_score']}"
    assert res_ai["syntactic"]["score"] < 70.0
    assert len(res_ai["syntactic"]["negation_hits"]) >= 1
    assert len(res_ai["syntactic"]["rule_of_three_hits"]) >= 1
    assert len(res_ai["adverb_density"]["hits"]) >= 4

    # 报告生成与 SCORES 格式核验
    report_ai = generate_markdown_report(res_ai, min_score=80.0)
    assert "❌ 拦截打回 (Failed - Blocked)" in report_ai
    assert "SCORES: {" in report_ai
    parsed_ai_scores = parse_scores_from_text(report_ai)
    assert parsed_ai_scores is not None
    assert parsed_ai_scores["overall"] == res_ai["overall_score"]

    # 2. 人类作家特征样本（断崖句长、口语俚语、粗粝生理应激、0 二元否定）
    human_sample = (
        "冰水顺着破损的防暴头盔缝隙淌进后颈，冷得陆巡狠狠抽了一口冷气，牙根发酸。"
        "没用。"
        "操纵杆彻底卡死在紧急闭锁槽里，无论他怎么用发麻的手掌去拍打那枚渗出焦糊机油味的红色按钮，仪表盘上只有暗红色的过载警报在神经质地跳闪。"
        "老顾抹了把脸上的血泥，啐了一口带铁锈味的浓痰，骂道：“别折腾了，减速伞早烧成灰了。”"
        "轰！"
        "机舱猛烈倾斜，金属蒙皮在狂风中撕裂出刺耳的尖啸。"
        "抓紧。"
    )

    res_human = evaluate_humanness(human_sample, "human_sample.md")
    assert res_human["overall_score"] >= 85.0, f"人类质感样本得分应 >= 85，实际为 {res_human['overall_score']}"
    assert res_human["syntactic"]["total_hits"] == 0
    assert res_human["adverb_density"]["score"] >= 90.0
    assert res_human["texture"]["score"] >= 80.0

    report_human = generate_markdown_report(res_human, min_score=80.0)
    assert "✅ 合格放行 (Passed)" in report_human


def test_check_zhuque_node_integration():
    """验证 demo-novel 中 check_zhuque 节点的插入、下游阻断与通过流转。"""
    demo_dir = Path("projects/demo-novel")
    if not demo_dir.exists():
        pytest.skip("projects/demo-novel not found")

    ch_graph = load_graph((demo_dir / "graph.yaml").read_text(encoding="utf-8"))
    nodes = ch_graph["nodes"]

    # 1. 节点拓扑存在性与前后依赖验证 (两级门禁: 本地粗筛 -> 官方 API 终审)
    assert "check_zhuque" in nodes, "工作流中必须包含 check_zhuque 节点"
    assert nodes["check_zhuque"]["kind"] == "command"
    assert nodes["check_zhuque"]["after"] == ["deai_polish"], "check_zhuque 必须紧接在 deai_polish 之后"
    assert "zhuque_api_final" in nodes, "工作流中必须包含 zhuque_api_final 官方终审节点"
    assert nodes["zhuque_api_final"]["kind"] == "command"
    assert nodes["zhuque_api_final"]["after"] == ["check_zhuque"], "zhuque_api_final 必须紧接在 check_zhuque 之后"
    assert nodes["audit_persona"]["after"] == ["zhuque_api_final"], "audit_persona 必须依赖 zhuque_api_final"

    # 2. 断言门禁要求核验 (本地粗筛 80 分 / 官方终审人类得分 60 分)
    assert_cfg = nodes["check_zhuque"].get("assert", {})
    assert assert_cfg.get("min_score") == 80
    assert assert_cfg.get("score_field") == "overall"
    api_assert_cfg = nodes["zhuque_api_final"].get("assert", {})
    assert api_assert_cfg.get("min_score") == 60
    assert api_assert_cfg.get("score_field") == "overall"

    # 3. 验证 author_accept 输入中包含 03_3 本地报告与 03_4 官方终审报告
    assert any("03_3_朱雀检测报告.md" in inp for inp in nodes["author_accept"]["inputs"])
    assert any("03_4_朱雀API终审报告.md" in inp for inp in nodes["author_accept"]["inputs"])

    # 4. 模拟 DAG 运行：验证打分未达 80 分时状态熔断 (failed) 并向下阻断 (blocked)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        polish_file = root / "03_polish.md"
        polish_file.write_text("正文内容...", encoding="utf-8")

        test_graph = {
            "version": 1,
            "nodes": {
                "deai_polish": {
                    "kind": "agent",
                    "outputs": ["03_polish.md"]
                },
                "check_zhuque": {
                    "kind": "command",
                    "after": ["deai_polish"],
                    "inputs": ["03_polish.md"],
                    "outputs": ["03_3_report.md"],
                    "assert": {"min_score": 80, "score_field": "overall"}
                },
                "audit_persona": {
                    "kind": "agent",
                    "after": ["check_zhuque"],
                    "inputs": ["03_polish.md"],
                    "outputs": ["03_5_persona.md"]
                }
            }
        }

        # 4.1 场景 A：朱雀报告得分为 62 分 (< 80) -> check_zhuque 判定 failed，下游 audit_persona 强行 blocked
        report_file = root / "03_3_report.md"
        report_file.write_text("# 报告\nSCORES: {\"overall\": 62.0}\n", encoding="utf-8")

        state_fail = derive_status(test_graph, root, None)
        assert state_fail["nodes"]["check_zhuque"]["status"] == "failed"
        assert "overall 得分 62.0 < 最低门槛 80.0" in state_fail["nodes"]["check_zhuque"]["failedBecause"]
        assert state_fail["nodes"]["audit_persona"]["status"] == "blocked"
        assert "上游节点 [check_zhuque] 处于 failed 状态" in state_fail["nodes"]["audit_persona"]["staleBecause"]

        # 4.2 场景 B：润色重写后朱雀报告得分为 88 分 (>= 80) -> check_zhuque 放行 (current)
        report_file.write_text("# 报告\nSCORES: {\"overall\": 88.0}\n", encoding="utf-8")
        baseline = {
            "nodes": {
                "deai_polish": {"inputs": {}},
                "check_zhuque": {"inputs": {"03_polish.md": hash_file(polish_file)}},
            }
        }
        state_pass = derive_status(test_graph, root, baseline)
        assert state_pass["nodes"]["check_zhuque"]["status"] == "current"
        assert state_pass["nodes"]["check_zhuque"].get("failedBecause") is None
        # audit_persona 产物未生成，但其上游 check_zhuque 已经放行 (current)，所以 audit_persona 变为就绪准备执行 (stale)，不再被 blocked
        assert state_pass["nodes"]["audit_persona"]["status"] == "stale"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



