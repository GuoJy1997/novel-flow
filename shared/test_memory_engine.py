# -*- coding: utf-8 -*-
"""Unit tests for NovelFlow Memory & Causal Consistency Engine."""
import shutil
import tempfile
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from memory_engine import (
    CausalConsistencyChecker,
    CharacterState,
    ClueState,
    FactSnapshot,
    LocationState,
    MemoryEngine,
    SecretState,
)


@pytest.fixture
def temp_project(tmp_path):
    proj = tmp_path / "test_novel"
    proj.mkdir()
    (proj / "设定" / "人物").mkdir(parents=True)
    (proj / "设定" / "世界观").mkdir(parents=True)
    (proj / "设定" / "大纲").mkdir(parents=True)
    (proj / "正文").mkdir(parents=True)
    (proj / "工作区").mkdir(parents=True)

    # 写入初始人物
    char_file = proj / "设定" / "人物" / "lin_zhou.md"
    char_file.write_text("姓名：林舟\n身份：信标侦察员\n性格：冷静克制", encoding="utf-8")

    world_file = proj / "设定" / "世界观" / "rules.md"
    world_file.write_text("- 凡人无法在无防护下穿越高维迷雾\n- 信标核心不可复制", encoding="utf-8")

    return proj


def test_fact_snapshot_serialization():
    snap = FactSnapshot(version=2, last_updated_chapter=5)
    snap.characters["c1"] = CharacterState(
        id="c1",
        name="林舟",
        health_status="左臂骨折",
        location="避难所",
        items_held=["信标罗盘"],
        known_secrets=["sec_1"],
    )
    snap.clues["clue_1"] = ClueState(
        id="clue_1",
        title="信标异常频段",
        status="planted",
        planted_chapter=2,
    )
    snap.secrets["sec_1"] = SecretState(
        id="sec_1",
        content="避难所已被污染",
        revealed_to=["林舟"],
    )
    snap.inventory_owners["信标罗盘"] = "林舟"

    d = snap.to_dict()
    restored = FactSnapshot.from_dict(d)

    assert restored.version == 2
    assert restored.last_updated_chapter == 5
    assert restored.characters["c1"].name == "林舟"
    assert restored.characters["c1"].health_status == "左臂骨折"
    assert restored.clues["clue_1"].title == "信标异常频段"
    assert restored.secrets["sec_1"].content == "避难所已被污染"
    assert restored.inventory_owners["信标罗盘"] == "林舟"


def test_causal_gate_dead_character():
    snap = FactSnapshot()
    snap.characters["c_dead"] = CharacterState(id="c_dead", name="陈四", alive=False)

    changes = {
        "character_updates": [
            {"id": "c_dead", "action": "拔枪射击"}
        ]
    }
    issues = CausalConsistencyChecker.audit_changes(snap, changes)
    assert any("生死违规" in issue for issue in issues)


def test_causal_gate_inventory_transfers():
    snap = FactSnapshot()
    snap.inventory_owners["天命剑"] = "张三"

    # 李四试图把不属于他的天命剑给王五
    changes = {
        "item_transfers": [
            {"item": "天命剑", "from": "李四", "to": "王五"}
        ]
    }
    issues = CausalConsistencyChecker.audit_changes(snap, changes)
    assert any("物品穿帮" in issue for issue in issues)


def test_causal_gate_teleportation():
    snap = FactSnapshot()
    snap.characters["hero"] = CharacterState(id="hero", name="林舟", location="黑水集市")

    # 林舟在黑水集市，变更声明却说他从迷雾深谷移动到了灯塔
    changes = {
        "character_moves": [
            {"id": "hero", "from": "迷雾深谷", "to": "灯塔"}
        ]
    }
    issues = CausalConsistencyChecker.audit_changes(snap, changes)
    assert any("空间瞬间传送" in issue for issue in issues)


def test_causal_gate_unplanted_clue_payoff():
    snap = FactSnapshot()
    # 伏笔从未埋设过
    changes = {
        "clue_actions": [
            {"id": "hidden_god_weapon", "action": "payoff", "notes": "突然天降神剑杀敌"}
        ]
    }
    issues = CausalConsistencyChecker.audit_changes(snap, changes)
    assert any("机械降神/空降伏笔" in issue for issue in issues)


def test_audit_draft_text_injuries_and_unowned_items():
    snap = FactSnapshot()
    snap.characters["lin_zhou"] = CharacterState(
        id="lin_zhou",
        name="林舟",
        health_status="右腿粉碎性骨折",
        location="地窖",
    )
    snap.characters["villain"] = CharacterState(
        id="villain",
        name="刀疤脸",
        location="地窖",
    )
    snap.inventory_owners["黑煞令"] = "刀疤脸"

    draft = "林舟狂奔向前，身形极度矫健。随后林舟掏出黑煞令，冷冷看向对方。"
    warnings = CausalConsistencyChecker.audit_draft_text(
        snap, draft, ["lin_zhou"]
    )

    assert any("生理状态矛盾警告" in w for w in warnings)
    assert any("物品穿帮警告" in w for w in warnings)


def test_memory_engine_apply_changes_lifecycle(temp_project):
    engine = MemoryEngine(temp_project)
    init_snap = engine.load_snapshot()
    assert "lin_zhou" in init_snap.characters
    assert init_snap.characters["lin_zhou"].name == "林舟"

    # 第 1 章回写
    changes_ch1 = {
        "character_updates": [
            {"id": "lin_zhou", "health_status": "轻微擦伤", "realm_or_level": "三级侦察兵"}
        ],
        "character_moves": [
            {"id": "lin_zhou", "to": "07号监测站"}
        ],
        "item_transfers": [
            {"item": "高频信号盒", "to": "lin_zhou"}
        ],
        "clue_actions": [
            {"id": "signal_echo", "title": "信标回声异常", "summary": "监测站听到非人类呼救"}
        ],
        "secret_reveals": [
            {"id": "omega_code", "content": "欧米茄协议已被启动", "learned_by": ["lin_zhou"], "method": "截获信标密电"}
        ],
        "timeline_advance": {
            "hours": 4,
            "time_of_day": "正午",
            "day": 1,
        }
    }

    updated_snap, issues = engine.apply_changes(
        changes=changes_ch1,
        chapter_num=1,
        chapter_summary="林舟抵达07号监测站，截获欧米茄协议密电并发现信标回声异常。",
        ending_text="风暴在窗外咆哮，屏幕上的波形正渐渐凝聚成一只眼睛的形状。",
    )

    assert len(issues) == 0
    assert updated_snap.last_updated_chapter == 1
    assert updated_snap.characters["lin_zhou"].location == "07号监测站"
    assert updated_snap.characters["lin_zhou"].health_status == "轻微擦伤"
    assert "高频信号盒" in updated_snap.characters["lin_zhou"].items_held
    assert "signal_echo" in updated_snap.clues
    assert "omega_code" in updated_snap.secrets
    assert "lin_zhou" in updated_snap.secrets["omega_code"].revealed_to
    assert updated_snap.timeline.time_of_day == "正午"

    # 检查历史归档
    history_file = temp_project / "设定" / "事实账本" / "history" / "snapshot_ch001.json"
    assert history_file.exists()

    # 打包第 2 章上下文任务卡
    pkg = engine.build_chapter_context_package(
        chapter_num=2,
        target_entities=["林舟"],
        active_clue_ids=["signal_echo"],
    )

    assert pkg["chapter_num"] == 2
    assert "林舟" in pkg["relevant_characters_snapshot"]
    assert pkg["relevant_characters_snapshot"]["林舟"]["location"] == "07号监测站"
    assert len(pkg["unresolved_clues"]) == 1
    assert pkg["unresolved_clues"][0]["id"] == "signal_echo"
    assert "风暴在窗外咆哮" in pkg["last_chapter_ending_anchor"]
    assert len(pkg["recent_chapter_summaries"]) == 1
