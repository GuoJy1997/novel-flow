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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

