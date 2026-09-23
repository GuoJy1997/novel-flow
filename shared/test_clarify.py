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
from pipeline import derive_status, generate_run_prompt, load_graph


CHAPTER_CHAIN = [
    "explore_context", "scene_beats", "draft_chapter", "deai_polish",
    "check_zhuque", "zhuque_api_final", "audit_persona", "review_qc",
    "author_accept", "novel_stats",
]


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
            tone="冷静克制的深空求生",
            vol1_title="序卷：静默边界",
            target_words_per_chapter=4000,
            min_words=1000,
            max_words=9000,
            min_review_score=20,
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

        # 3. 只持久化模板引用和白名单业务参数，不另存节点或覆盖门禁。
        graph_text = (root / "graph.yaml").read_text(encoding="utf-8")
        reference = yaml.safe_load(graph_text)
        assert set(reference) == {"version", "name", "template", "params", "overrides"}
        assert reference["version"] == 1
        assert reference["template"] == "chapter-v1"
        assert reference["name"] == "novel-shadow-beacon"
        assert reference["params"] == {
            "chapter_num": 1,
            "chapter_title": "初入迷局",
            "volume_name": "序卷",
            "genre": "硬核科幻",
            "tone": "冷静克制的深空求生",
            "target_words": 4000,
            "chapter_workspace": "工作区/第{chapter_pad}章",
            "chapter_output": "正文/{volume_name}/第{chapter_pad}章_{chapter_title}.md",
            "voice_sample": "资产/voice_sample.md",
        }
        for patch in reference["overrides"].values():
            assert set(patch) <= {"prompt_append", "inputs_add"}

        # 4. 核心加载器必须展开完整十节点链，并保留统一门禁与动态章路径。
        parsed_graph = load_graph(graph_text, project_root=root)
        assert parsed_graph["name"] == "novel-shadow-beacon"
        nodes = parsed_graph["nodes"]
        assert list(nodes) == CHAPTER_CHAIN
        for index, nid in enumerate(CHAPTER_CHAIN):
            assert nodes[nid].get("after", []) == ([] if index == 0 else [CHAPTER_CHAIN[index - 1]])
            assert "model" not in nodes[nid]
        assert nodes["draft_chapter"]["assert"]["min_words"] == 3200
        assert nodes["draft_chapter"]["assert"]["max_words"] == 5600
        assert nodes["deai_polish"]["assert"]["min_words"] == 3000
        assert nodes["review_qc"]["assert"]["min_score"] == 80
        assert nodes["check_zhuque"]["assert"]["min_score"] == 80
        assert nodes["zhuque_api_final"]["assert"]["min_score"] == 60
        assert nodes["audit_persona"]["assert"]["min_scores"]["epistemic_boundary"] == 80
        assert nodes["author_accept"]["outputs"] == ["正文/序卷/第01章_初入迷局.md"]
        later = load_graph(graph_text, project_root=root, override_params={
            "chapter_num": 12, "chapter_title": "回声",
        })
        assert list(later["nodes"]) == CHAPTER_CHAIN
        assert later["nodes"]["draft_chapter"]["outputs"] == ["工作区/第12章/02_正文初稿.md"]
        assert later["nodes"]["author_accept"]["outputs"] == ["正文/序卷/第12章_回声.md"]
        assert "第 12 章《回声》" in generate_run_prompt(
            "draft_chapter", later["nodes"]["draft_chapter"], str(root),
        )

        # 5. 首次仅前情节点可运行；产物就绪后应先放行分场，不能跳过它。
        state = derive_status(parsed_graph, root, None)
        assert state["nodes"]["explore_context"]["status"] == "stale"
        for nid in CHAPTER_CHAIN[1:]:
            assert state["nodes"][nid]["status"] == "blocked"
        (root / "工作区/第01章/01_状态上下文.md").write_text("前情事实。" * 60, encoding="utf-8")
        progressed = derive_status(parsed_graph, root, state)
        assert progressed["nodes"]["explore_context"]["status"] == "current"
        assert progressed["nodes"]["scene_beats"]["status"] == "stale"
        for nid in CHAPTER_CHAIN[2:]:
            assert progressed["nodes"][nid]["status"] == "blocked"


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


def test_style_constitution_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "style-novel"
        c = NovelConstitution(
            slug="style-novel",
            title="终焉之舍",
            genre="无限流悬疑",
            style_archetype="十日终焉×诡舍 (现代通俗白话/生死博弈/深度心理悬疑)",
            classical_ratio="纯现代通俗白话占比 90%~95%，半文半白/古意字词仅占 5%~10% 适度穿插",
            psychological_depth="高密度心理推演与生理应激白描（心率、冷汗、微表情、多步推演反制），严禁削弱情绪",
        )
        res = fan_out_constitution(c, root)

        # 1. 验证 novel.md 中写入了文风规则
        novel_md = (root / "novel.md").read_text(encoding="utf-8")
        assert "文风流派对标" in novel_md
        assert "十日终焉×诡舍" in novel_md
        assert "纯现代通俗白话占比 90%~95%" in novel_md
        assert "心理与情绪流铁律" in novel_md

        # 2. 验证 snapshot.json 中持久化了文风元数据
        snap = json.loads((root / "设定" / "事实账本" / "snapshot.json").read_text(encoding="utf-8"))
        assert "style_constitution" in snap
        assert snap["style_constitution"]["style_archetype"] == "十日终焉×诡舍 (现代通俗白话/生死博弈/深度心理悬疑)"
        assert "90%~95%" in snap["style_constitution"]["classical_ratio"]

        # 3. 验证 voice_sample.md 包含了十日终焉与诡舍黄金对照
        sample = (root / "资产" / "voice_sample.md").read_text(encoding="utf-8")
        assert "十日终焉" in sample
        assert "诡舍" in sample
        assert "开门见煞" in sample

        # 4. 通过真实加载器与派发提示词验证补充规则，而非搜索源码或 YAML 文本。
        graph_text = (root / "graph.yaml").read_text(encoding="utf-8")
        graph = load_graph(graph_text, project_root=root)
        prompt = generate_run_prompt("deai_polish", graph["nodes"]["deai_polish"], str(root))
        for value in (c.style_archetype, c.classical_ratio, c.psychological_depth, c.dialogue_style):
            assert value in prompt
        assert "资产/voice_sample.md" in graph["nodes"]["deai_polish"]["inputs"]


@pytest.mark.parametrize("node_id", [
    "explore_context", "scene_beats", "draft_chapter", "deai_polish",
    "audit_persona", "review_qc",
])
def test_custom_style_reaches_actual_run_prompt(node_id, tmp_path):
    c = NovelConstitution(
        slug="custom-style",
        title="市井小记",
        genre="现实生活",
        tone="轻快而温暖",
        pov="第一人称回忆视角",
        style_archetype="市井轻喜剧与口述史",
        classical_ratio="九成口语、一成地方方言，不用文言",
        psychological_depth="以犹豫和日常小动作呈现心理，不堆砌恐惧反应",
        dialogue_style="南方小镇闲谈，允许长段无对白的回忆",
        banned_words=["命运齿轮", "宿命洪流"],
        voice_sample_text="# 自定义样本\n巷口又卖起了热豆花。",
    )
    root = tmp_path / c.slug
    fan_out_constitution(c, root)
    graph = load_graph((root / "graph.yaml").read_text(encoding="utf-8"), project_root=root)
    assert node_id in graph["nodes"]
    node = graph["nodes"][node_id]
    prompt = generate_run_prompt(node_id, node, str(root))
    for value in (
        c.pov, c.style_archetype, c.classical_ratio, c.psychological_depth,
        c.dialogue_style, *c.banned_words,
    ):
        assert value in prompt
    for path in ("novel.md", "设定/事实账本/snapshot.json"):
        assert path in node["inputs"]
        assert path in prompt
        assert (root / path).is_file()
    assert (root / "资产/voice_sample.md").read_text(encoding="utf-8") == c.voice_sample_text
    assert (root / "assets/voice_sample.md").read_text(encoding="utf-8") == c.voice_sample_text
