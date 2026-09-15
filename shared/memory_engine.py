# -*- coding: utf-8 -*-
"""NovelFlow Memory & Causal Consistency Engine.

基于 15 维事实快照 (Fact Snapshot) 与 12 类变更声明 (CHANGES Protocol)，
实现长篇小说跨千章抗遗忘、物理状态连续性与因果逻辑守卫。
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class CharacterState:
    id: str
    name: str
    realm_or_level: str = "普通"
    health_status: str = "健康"
    location: str = "未知"
    appearance_traits: List[str] = field(default_factory=list)
    personality_tags: List[str] = field(default_factory=list)
    abilities: List[str] = field(default_factory=list)
    items_held: List[str] = field(default_factory=list)
    relationships: Dict[str, str] = field(default_factory=dict)
    known_secrets: List[str] = field(default_factory=list)
    alive: bool = True
    notes: str = ""


@dataclass
class ClueState:
    id: str
    title: str
    status: str = "planted"  # planted(已埋) / developing(发酵) / paid_off(已收) / abandoned(弃置)
    planted_chapter: int = 1
    tier: int = 1  # 1: 全书核心伏笔, 2: 分卷主伏笔, 3: 章节次级伏笔
    summary: str = ""
    target_characters: List[str] = field(default_factory=list)
    payoff_chapter: Optional[int] = None
    payoff_notes: str = ""


@dataclass
class SecretState:
    id: str
    content: str
    revealed_to: List[str] = field(default_factory=list)
    hidden_from: List[str] = field(default_factory=list)
    is_public: bool = False
    source_chapter: int = 1


@dataclass
class LocationState:
    id: str
    name: str
    status: str = "normal"  # normal, destroyed, sealed, hostile
    current_occupants: List[str] = field(default_factory=list)
    environment_traits: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ConflictState:
    id: str
    title: str
    parties: List[str] = field(default_factory=list)
    status: str = "active"  # active, paused, resolved, escalated
    current_stage: str = ""


@dataclass
class TimelineState:
    current_day: int = 1
    time_of_day: str = "清晨"
    elapsed_hours: float = 0.0
    timeline_markers: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class FactSnapshot:
    """15 维确定性事实快照。不依赖模型模糊记忆，只记录精确状态。"""
    version: int = 1
    last_updated_chapter: int = 0
    characters: Dict[str, CharacterState] = field(default_factory=dict)
    clues: Dict[str, ClueState] = field(default_factory=dict)
    secrets: Dict[str, SecretState] = field(default_factory=dict)
    locations: Dict[str, LocationState] = field(default_factory=dict)
    conflicts: Dict[str, ConflictState] = field(default_factory=dict)
    factions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timeline: TimelineState = field(default_factory=TimelineState)
    inventory_owners: Dict[str, str] = field(default_factory=dict)  # item_name -> character_id or location_id
    promises: List[Dict[str, Any]] = field(default_factory=list)
    deadlines: List[Dict[str, Any]] = field(default_factory=list)
    world_rules: List[str] = field(default_factory=list)
    milestones: List[Dict[str, Any]] = field(default_factory=list)
    chapter_summaries: Dict[int, str] = field(default_factory=dict)
    last_chapter_ending: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FactSnapshot":
        data = copy.deepcopy(data)
        characters = {
            k: CharacterState(**v) for k, v in data.get("characters", {}).items()
        }
        clues = {
            k: ClueState(**v) for k, v in data.get("clues", {}).items()
        }
        secrets = {
            k: SecretState(**v) for k, v in data.get("secrets", {}).items()
        }
        locations = {
            k: LocationState(**v) for k, v in data.get("locations", {}).items()
        }
        conflicts = {
            k: ConflictState(**v) for k, v in data.get("conflicts", {}).items()
        }
        timeline_data = data.get("timeline", {})
        timeline = TimelineState(**timeline_data) if isinstance(timeline_data, dict) else TimelineState()

        return cls(
            version=data.get("version", 1),
            last_updated_chapter=data.get("last_updated_chapter", 0),
            characters=characters,
            clues=clues,
            secrets=secrets,
            locations=locations,
            conflicts=conflicts,
            factions=data.get("factions", {}),
            timeline=timeline,
            inventory_owners=data.get("inventory_owners", {}),
            promises=data.get("promises", []),
            deadlines=data.get("deadlines", []),
            world_rules=data.get("world_rules", []),
            milestones=data.get("milestones", []),
            chapter_summaries={int(k): str(v) for k, v in data.get("chapter_summaries", {}).items()},
            last_chapter_ending=data.get("last_chapter_ending", ""),
        )


class CausalConsistencyChecker:
    """因果与逻辑一致性守卫。

    在章节生成前后核验物理移动、知情权、生死状态、物品流转，拦截不合人设和吃书操作。
    """

    @staticmethod
    def audit_changes(snapshot: FactSnapshot, changes: Dict[str, Any]) -> List[str]:
        """核验 CHANGES 变更声明是否违背当前快照的物理与因果法则。"""
        issues: List[str] = []

        # 1. 检查已死亡角色是否突然行动
        char_updates = changes.get("character_updates", [])
        for cu in char_updates:
            cid = cu.get("id")
            if cid in snapshot.characters:
                c = snapshot.characters[cid]
                if not c.alive and cu.get("alive") is not True and cu.get("action"):
                    issues.append(f"【生死违规】角色 [{c.name}] 已经死亡，但本章依然在进行行动: {cu.get('action')}")

        # 2. 检查物品流转逻辑 (是否从非持有者手中转移)
        item_transfers = changes.get("item_transfers", [])
        for it in item_transfers:
            item = it.get("item")
            giver = it.get("from")
            receiver = it.get("to")
            current_owner = snapshot.inventory_owners.get(item)
            if current_owner and giver and current_owner != giver:
                issues.append(
                    f"【物品穿帮】物品 [{item}] 当前持有者为 [{current_owner}]，但变更声明却记录为从 [{giver}] 转移至 [{receiver}]！"
                )

        # 3. 检查角色移动逻辑 (上一位置是否连贯)
        moves = changes.get("character_moves", [])
        for m in moves:
            cid = m.get("id")
            from_loc = m.get("from")
            to_loc = m.get("to")
            if cid in snapshot.characters:
                current_loc = snapshot.characters[cid].location
                if current_loc and current_loc != "未知" and from_loc and current_loc != from_loc:
                    issues.append(
                        f"【空间瞬间传送】角色 [{snapshot.characters[cid].name}] 上次记录位置在 [{current_loc}]，但移动声明从 [{from_loc}] 移动到 [{to_loc}]，存在时空断层！"
                    )

        # 4. 检查伏笔回收合法性 (是否从未埋设就直接回收)
        clue_actions = changes.get("clue_actions", [])
        for ca in clue_actions:
            clue_id = ca.get("id")
            action = ca.get("action")
            if action in ("payoff", "回收") and clue_id not in snapshot.clues:
                issues.append(
                    f"【机械降神/空降伏笔】伏笔 [{clue_id}] 从未在前期伏笔表中埋设(planted)，却在本章被直接标记回收！"
                )

        # 5. 检查秘密越界知情
        secret_reveals = changes.get("secret_reveals", [])
        for sr in secret_reveals:
            sec_id = sr.get("id")
            new_learners = sr.get("learned_by", [])
            method = sr.get("method", "")
            if not method:
                issues.append(f"【知情无凭】秘密 [{sec_id}] 被角色 {new_learners} 得知，但未声明获知方式(method)！")

        return issues

    @staticmethod
    def audit_draft_text(snapshot: FactSnapshot, draft_text: str, current_chapter_chars: List[str]) -> List[str]:
        """核验正文草稿中是否存在明显的认知边界违规与生理状态矛盾。"""
        warnings: List[str] = []

        # 检查重伤角色是否有剧烈动作词
        for cid in current_chapter_chars:
            c = snapshot.characters.get(cid)
            if not c:
                continue
            if "骨折" in c.health_status or "重伤" in c.health_status or "濒死" in c.health_status:
                violent_actions = ["疾奔", "飞身", "暴起", "狂奔", "凌空", "挥剑猛斩"]
                for va in violent_actions:
                    pattern = rf"{re.escape(c.name)}[^\n。！？]{{0,15}}{va}"
                    if re.search(pattern, draft_text):
                        warnings.append(
                            f"【生理状态矛盾警告】角色 [{c.name}] 当前生理状态为 [{c.health_status}]，但在正文中出现 '{va}' 等剧烈动作，需核查合理性。"
                        )

        # 检查未持有的物品是否被角色突然拔出使用
        for item, owner in snapshot.inventory_owners.items():
            for cid in current_chapter_chars:
                c = snapshot.characters.get(cid)
                if not c or owner == c.name or owner == c.id:
                    continue
                use_pattern = rf"{re.escape(c.name)}[^\n。！？]{{0,10}}(掏出|取出|拔出|祭出|握着){re.escape(item)}"
                if re.search(use_pattern, draft_text):
                    warnings.append(
                        f"【物品穿帮警告】角色 [{c.name}] 并非 [{item}] 的持有者（当前归属: [{owner}]），但正文出现拔出/取出该物品描写！"
                    )

        return warnings


class MemoryEngine:
    """长篇小说记忆引擎：管理状态快照、执行变更回写并生成本章上下文任务包。"""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.ledger_dir = self.project_dir / "设定" / "事实账本"
        self.ledger_file = self.ledger_dir / "snapshot.json"
        self.history_dir = self.ledger_dir / "history"
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def load_snapshot(self) -> FactSnapshot:
        if self.ledger_file.exists():
            try:
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return FactSnapshot.from_dict(data)
            except Exception as e:
                print(f"[warning] 加载事实账本失败: {e}，将初始化默认账本")
        return self._initialize_from_project_files()

    def _initialize_from_project_files(self) -> FactSnapshot:
        """根据工程的 设定/ 目录初次构建初始事实快照。"""
        snapshot = FactSnapshot()

        # 扫描人物设定
        chars_dir = self.project_dir / "设定" / "人物"
        if chars_dir.exists():
            for pf in chars_dir.glob("*.md"):
                cid = pf.stem
                text = pf.read_text(encoding="utf-8", errors="ignore")
                
                # 检查是否为汇总文件（包含多个 - **角色名**）
                multi_char_matches = re.findall(r"^[-*]\s+\*\*([^*]+?)\*\*(?:（([^）]+)）)?\s*[：:]?", text, flags=re.MULTILINE)
                if multi_char_matches:
                    for m_name, m_role in multi_char_matches:
                        clean_name = m_name.split("(")[0].strip()
                        c_id = clean_name.lower().replace(" ", "_")
                        snapshot.characters[c_id] = CharacterState(
                            id=c_id,
                            name=clean_name,
                            notes=f"身份/定位: {m_role or '配角'}"
                        )
                else:
                    name_match = re.search(r"姓名[：:]\s*(.+)", text)
                    name = name_match.group(1).strip() if name_match else cid
                    snapshot.characters[cid] = CharacterState(id=cid, name=name, notes=text[:200])

        # 扫描世界观法则
        world_dir = self.project_dir / "设定" / "世界观"
        if world_dir.exists():
            for wf in world_dir.glob("*.md"):
                text = wf.read_text(encoding="utf-8", errors="ignore")
                rules = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
                snapshot.world_rules.extend(rules[:20])

        return snapshot

    def save_snapshot(self, snapshot: FactSnapshot, chapter_num: Optional[int] = None):
        """保存事实快照，同时在 history 备份章节版本。"""
        self._ensure_dirs()
        data = snapshot.to_dict()
        with open(self.ledger_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        ch = chapter_num if chapter_num is not None else snapshot.last_updated_chapter
        if ch > 0:
            hist_file = self.history_dir / f"snapshot_ch{ch:03d}.json"
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def apply_changes(
        self,
        changes: Dict[str, Any],
        chapter_num: int,
        chapter_summary: str = "",
        ending_text: str = ""
    ) -> Tuple[FactSnapshot, List[str]]:
        """执行状态回写 (State Writeback)：将本章产出的 CHANGES 合并进全局事实账本。"""
        snapshot = self.load_snapshot()

        # 1. 运行因果一致性审计
        issues = CausalConsistencyChecker.audit_changes(snapshot, changes)

        # 2. 合并角色状态
        for cu in changes.get("character_updates", []):
            cid = cu.get("id")
            if not cid:
                continue
            if cid not in snapshot.characters:
                snapshot.characters[cid] = CharacterState(id=cid, name=cu.get("name", cid))
            c = snapshot.characters[cid]
            if "realm_or_level" in cu:
                c.realm_or_level = cu["realm_or_level"]
            if "health_status" in cu:
                c.health_status = cu["health_status"]
            if "location" in cu:
                c.location = cu["location"]
            if "alive" in cu:
                c.alive = bool(cu["alive"])
            if "abilities_add" in cu:
                for ab in cu["abilities_add"]:
                    if ab not in c.abilities:
                        c.abilities.append(ab)
            if "abilities_remove" in cu:
                c.abilities = [ab for ab in c.abilities if ab not in cu["abilities_remove"]]
            if "relationships" in cu:
                c.relationships.update(cu["relationships"])

        # 3. 合并角色移动
        for m in changes.get("character_moves", []):
            cid = m.get("id")
            to_loc = m.get("to")
            if cid and to_loc and cid in snapshot.characters:
                snapshot.characters[cid].location = to_loc

        # 4. 合并物品流转
        for it in changes.get("item_transfers", []):
            item = it.get("item")
            to_owner = it.get("to")
            if item and to_owner:
                snapshot.inventory_owners[item] = to_owner
                for c in snapshot.characters.values():
                    if item in c.items_held and c.name != to_owner and c.id != to_owner:
                        c.items_held.remove(item)
                if to_owner in snapshot.characters:
                    if item not in snapshot.characters[to_owner].items_held:
                        snapshot.characters[to_owner].items_held.append(item)

        # 5. 合并伏笔状态
        for ca in changes.get("clue_actions", []):
            cid = ca.get("id")
            action = ca.get("action")
            if not cid:
                continue
            if cid not in snapshot.clues:
                snapshot.clues[cid] = ClueState(
                    id=cid,
                    title=ca.get("title", cid),
                    planted_chapter=chapter_num,
                    tier=ca.get("tier", 2),
                    summary=ca.get("summary", ""),
                )
            clue = snapshot.clues[cid]
            if action in ("payoff", "回收"):
                clue.status = "paid_off"
                clue.payoff_chapter = chapter_num
                clue.payoff_notes = ca.get("notes", "")
            elif action in ("developing", "发酵"):
                clue.status = "developing"

        # 6. 合并秘密揭示
        for sr in changes.get("secret_reveals", []):
            sec_id = sr.get("id")
            if not sec_id:
                continue
            if sec_id not in snapshot.secrets:
                snapshot.secrets[sec_id] = SecretState(
                    id=sec_id,
                    content=sr.get("content", sec_id),
                    source_chapter=chapter_num,
                )
            sec = snapshot.secrets[sec_id]
            for person in sr.get("learned_by", []):
                if person not in sec.revealed_to:
                    sec.revealed_to.append(person)
                if person in snapshot.characters and sec_id not in snapshot.characters[person].known_secrets:
                    snapshot.characters[person].known_secrets.append(sec_id)

        # 7. 推进时间线
        t_advance = changes.get("timeline_advance", {})
        if t_advance:
            snapshot.timeline.elapsed_hours += float(t_advance.get("hours", 0))
            if "time_of_day" in t_advance:
                snapshot.timeline.time_of_day = t_advance["time_of_day"]
            if "day" in t_advance:
                snapshot.timeline.current_day = int(t_advance["day"])

        # 8. 记录里程碑与章节摘要
        if chapter_summary:
            snapshot.chapter_summaries[chapter_num] = chapter_summary
            snapshot.milestones.append({
                "chapter": chapter_num,
                "summary": chapter_summary[:150],
            })
        if ending_text:
            snapshot.last_chapter_ending = ending_text.strip()

        snapshot.last_updated_chapter = chapter_num
        snapshot.version += 1

        self.save_snapshot(snapshot, chapter_num=chapter_num)
        return snapshot, issues

    def build_chapter_context_package(
        self,
        chapter_num: int,
        target_entities: List[str],
        active_clue_ids: Optional[List[str]] = None,
        max_recent_summaries: int = 3,
    ) -> Dict[str, Any]:
        """打包第 N 章最小必要事实上下文（Task Package）。"""
        snapshot = self.load_snapshot()

        relevant_characters = {}
        for ent in target_entities:
            for cid, c in snapshot.characters.items():
                if ent == cid or ent == c.name:
                    relevant_characters[c.name] = {
                        "id": c.id,
                        "health": c.health_status,
                        "location": c.location,
                        "realm": c.realm_or_level,
                        "items_held": c.items_held,
                        "relationships": c.relationships,
                        "known_secrets": c.known_secrets,
                    }

        relevant_clues = []
        for clue_id, clue in snapshot.clues.items():
            if clue.status in ("planted", "developing"):
                if not active_clue_ids or clue_id in active_clue_ids:
                    relevant_clues.append({
                        "id": clue.id,
                        "title": clue.title,
                        "status": clue.status,
                        "planted_chapter": clue.planted_chapter,
                        "summary": clue.summary,
                    })

        recent_summaries = []
        for ch in range(max(1, chapter_num - max_recent_summaries), chapter_num):
            if ch in snapshot.chapter_summaries:
                recent_summaries.append(f"第{ch}章摘要: {snapshot.chapter_summaries[ch]}")

        package = {
            "chapter_num": chapter_num,
            "timeline": {
                "day": snapshot.timeline.current_day,
                "time_of_day": snapshot.timeline.time_of_day,
                "elapsed_hours": snapshot.timeline.elapsed_hours,
            },
            "relevant_characters_snapshot": relevant_characters,
            "unresolved_clues": relevant_clues,
            "recent_chapter_summaries": recent_summaries,
            "last_chapter_ending_anchor": snapshot.last_chapter_ending,
            "world_hard_rules": snapshot.world_rules[:5],
            "instruction": "【因果守卫律令】正文生成必须严格遵守上述角色的健康状态、已知秘密范围与持有物品。严禁跨越知情边界或时空闪现！",
        }
        return package
