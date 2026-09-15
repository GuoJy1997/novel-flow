# -*- coding: utf-8 -*-
"""测试小说需求澄清与最高宪法(novel.md)生成及原子分发。"""
import json
import tempfile
from pathlib import Path

import pytest
import yaml

from novel_clarify import (
    NovelConstitution,
    compile_constitution_markdown,
    fan_out_constitution,
    load_constitution_from_json,
)
from pipeline import load_graph, derive_status


def test_constitution_data_defaults():
    c = NovelConstitution(slug="test-novel", title="迷雾灯塔")
    assert c.slug == "test-novel"
    assert c.title == "迷雾灯塔"
    assert len(c.iron_rules) >= 3
    assert len(c.clues_ledger) >= 2
    assert "宛如" in c.banned_words


def test_compile_constitution_markdown():
    c = NovelConstitution(
        slug="deep-shadow",
        title="深影之誓",
        genre="克苏鲁悬疑",
        protagonist_name="顾临",
        logline="当凝视深渊三分钟后，深渊也只能按规则和他赌命。",
    )
    md = compile_constitution_markdown(c)
    assert "# 《小说项目最高宪法》(Novel Project Constitution)" in md
    assert "深影之誓" in md
    assert "克苏鲁悬疑" in md
    assert "顾临" in md
    assert "当凝视深渊三分钟后" in md
    assert "第三条：三幕大纲与伏笔生命周期锁定" in md
    assert "第四条：叙事声纹与抗朱雀检测规范" in md


def test_fan_out_and_pipeline_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "shadow-beacon"
        c = NovelConstitution(
            slug="shadow-beacon",
            title="阴影信标",
            genre="硬核科幻",
            protagonist_name="楚河",
            logline="穿越静默视界前的最后八分钟。",
        )
        res = fan_out_constitution(c, root)

        # 1. 验证关键文件全量生成
        assert (root / "novel.md").is_file()
        assert (root / "设定" / "世界观" / "01_世界法则与禁忌.md").is_file()
        assert (root / "设定" / "世界观" / "02_阵营势力图谱.md").is_file()
        assert (root / "设定" / "人物" / "01_主角_楚河.md").is_file()
        assert (root / "设定" / "人物" / "02_核心配角与反派.md").is_file()
        assert (root / "设定" / "人物" / "03_角色知情状态表.md").is_file()
        assert (root / "设定" / "大纲" / "01_全书三幕总纲.md").is_file()
        assert (root / "设定" / "大纲" / "02_分卷细纲_第一卷.md").is_file()
        assert (root / "设定" / "大纲" / "03_伏笔与线索总台账.md").is_file()
        assert (root / "设定" / "事实账本" / "snapshot.json").is_file()
        assert (root / "资产" / "voice_sample.md").is_file()
        assert (root / "graph.yaml").is_file()

        # 2. 验证 snapshot.json 内容
        snap = json.loads((root / "设定" / "事实账本" / "snapshot.json").read_text(encoding="utf-8"))
        assert snap["novel_slug"] == "shadow-beacon"
        assert snap["protagonist"]["name"] == "楚河"

        # 3. 验证生成的 graph.yaml 能够被核心引擎 pipeline.py 解析
        graph_text = (root / "graph.yaml").read_text(encoding="utf-8")
        parsed_graph = load_graph(graph_text, project_root=root)
        assert parsed_graph["params"]["genre"] == "硬核科幻"
        assert "gather_state" in parsed_graph["nodes"]
        assert "draft_chapter" in parsed_graph["nodes"]
        assert "deai_polish" in parsed_graph["nodes"]
        assert "review_qc" in parsed_graph["nodes"]

        # 4. 验证增量状态机推导
        state = derive_status(parsed_graph, root, None)
        # gather_state inputs 全部就绪，输出未生成，应当为 stale
        assert state["nodes"]["gather_state"]["status"] == "stale"
        # 后续节点依赖 gather_state，应当为 blocked
        assert state["nodes"]["draft_chapter"]["status"] == "blocked"


def test_load_from_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / "config.json"
        json_file.write_text(json.dumps({
            "slug": "custom-book",
            "title": "异化黎明",
            "genre": "末世异能",
            "protagonist_name": "白沉",
        }, ensure_ascii=False), encoding="utf-8")

        c = load_constitution_from_json(json_file)
        assert c.slug == "custom-book"
        assert c.title == "异化黎明"
        assert c.protagonist_name == "白沉"
