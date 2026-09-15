# -*- coding: utf-8 -*-
"""小说项目需求澄清体系与《小说项目宪法》(novel.md)工程化引擎。

本模块实现：
1. 六阶递进需求澄清问询体系（商业定位、世界法则、人物灵魂、大纲暗线、叙事声纹、质量门禁）
2. 《小说项目宪法》(novel.md) 标准化构建器
3. 宪法多维原子分发引擎 (Fan-out Hydration Engine)：
   一键将 novel.md 拆解并分发至 设定/、资产/、工作区/、正文/ 及 graph.yaml
4. 交互式对话式引导命令行与外部草稿文档解析反向澄清机制
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_BANNED_WORDS = [
    "宛如",
    "仿佛在诉说着",
    "在这一刻",
    "殊不知",
    "不仅如此",
    "更重要的是",
    "嘴角勾起一抹弧度",
    "倒吸一口凉气",
    "眼神中闪烁着坚定的光芒",
    "时间仿佛在这一瞬间静止",
]

DEFAULT_VOICE_SAMPLE = """# 工业化小说文风声纹与语言指纹样本 (Voice Calibration Master)

## 一、 核心叙事指纹与抗朱雀检测军规
1. **感官白描 (Show, Don't Tell)**：严禁用“令人感到无比恐惧”等抽象形容词，只写手电筒光柱里漂浮的石灰尘埃、青石板缝里的腥味、湿泥上碾出的印子。
2. **短句破进 (拉大 Burstiness)**：拒绝 30 字以上复合长句，多用 3~7 字动词短句：“火灭了。”、“拔刀。”、“退三步。”
3. **对话带刺**：人物之间不打无意义官腔，每一句对白都在进行信息差博弈与试探。
4. **一票否决禁词表**：严禁出现“宛如”、“仿佛在诉说着”、“在这一刻”、“殊不知”、“不仅如此”。

## 二、 风格对照基准样章
手电筒的白光扫在青砖墙上，光斑晃得人眼皮发酸。
老齐在前面蹲下身子，胶底解放鞋在湿泥上碾出半圈暗红的印子。他没回头，只是竖起两根生着厚茧的食指，往虚空里轻轻一压。
后头跟着的四个人连呼吸都掐灭了。
空气里有一股烂木头泡在机油里的闷酸味，混着地下渗出的阴冷水汽，直往毛孔深处钻。头顶上的水滴声很匀，“嗒、嗒、嗒”，三秒一声，像在给什么东西计时。
“规矩变了。”老齐压低嗓子，声音沙哑得像生铁磨砂纸，“刚才进门时，右边是三盏熄了的油灯，现在多了一盏。”
哧啦。
暗红的火苗跳起来，照亮了老齐脸上纵横交错的刀疤。火苗笔直向上，连半点晃动都没有。地底下一点风也没有。死寂。
“不是生门封了。”老齐盯着手里快烧到指头的火柴棍，喉结上下滚了滚，“是这屋里……多了个喘大气的，把风给吸回去了。”
"""


@dataclass
class NovelConstitution:
    # 阶梯一：商业定位与核心脑洞
    slug: str = "my-novel"
    title: str = "未命名小说"
    genre: str = "悬疑惊悚"
    target_platform: str = "番茄小说"
    target_audience: str = "喜爱高智商博弈与快节奏反转的年轻网文读者"
    logline: str = "一句话核心爽点/金手指"
    is_continuation: bool = False
    original_summary: str = ""

    # 阶梯二：世界法则与时空禁忌
    reality_relation: str = "现代架空与隐秘超自然暗面交织"
    power_system: str = "规则型诡异异能，分为感知、操纵、因果三层，不可越阶爆发"
    iron_rules: List[str] = field(default_factory=lambda: [
        "通讯不可达法则：在特定封闭结界内，一切电磁波与外部信号彻底失效。",
        "不可逆代价：使用高阶规则能力必须付出自身寿命或部分肢体知觉作为代价。",
        "信息守恒：神明无法直接目睹直视者，凡人直视神明必定发生不可逆精神异化。",
    ])
    factions: List[Dict[str, str]] = field(default_factory=lambda: [
        {"name": "调查清理司", "nature": "官方隐秘维稳机构，行事刻板严苛，以防暴走为首要原则"},
        {"name": "破晓学会", "nature": "民间求知狂热异能者同盟，探索终极禁忌规则"},
    ])

    # 阶梯三：人物灵魂与冲突网络
    protagonist_name: str = "陆巡"
    protagonist_surface_id: str = "普通当铺鉴宝学徒 / 巡逻队员"
    protagonist_hidden_id: str = "唯一身负时间回溯规则碎片的破局者"
    protagonist_motivation: str = "查清三年前全家失踪的真正档案并活下去"
    protagonist_flaw: str = "冷酷偏执，极度多疑，绝不轻信任何人的口头承诺"
    protagonist_moral_boundary: str = "不主动残害无辜，但对挡路与背叛者斩草除根"
    protagonist_voice: str = "语调低沉冷硬，单句少于 15 字，擅长反问与眼神测算"

    antagonist_name: str = "深渊低语者 / 幕后黑手"
    antagonist_drive: str = "通过献祭整座城市重启旧神纪元"
    antagonist_logic: str = "坚信毁灭是拯救人类脱离终极绝望的唯一解法"

    supporting_cast: List[Dict[str, str]] = field(default_factory=lambda: [
        {"name": "林朔", "identity": "行动督查官", "secret": "其实是高层派来观察主角异化指数的看守", "relation": "表面同盟互信，暗中持枪防备"},
        {"name": "白芷", "identity": "黑市情报贩子", "secret": "知晓上一代破局者的死因但选择隐瞒", "relation": "利益交换，互为后手"},
    ])

    # 阶梯四：三幕大纲与暗线伏笔
    three_acts: Dict[str, str] = field(default_factory=lambda: {
        "act1_break": "第一幕（1-10章）：突发规则封锁密室，平静生活被彻底打碎，主角在生死博弈中首次激活禁忌能力。",
        "act2_twist": "第二幕（11-30章）：深入调查学会与官方暗战，至暗时刻发现同盟高层早已被幕后黑手寄生。",
        "act3_resolution": "第三幕（31-40章）：终极对决，付出惨痛代价粉碎献祭仪式，揭示整个世界的终极真相。",
    })
    vol1_title: str = "第一卷：深渊初醒"
    vol1_goal: str = "在封闭规则空间中完成破局，获取第一枚核心规则密钥"
    vol1_chapters_count: int = 10
    first_breakthrough_chapter: int = 3

    clues_ledger: List[Dict[str, Any]] = field(default_factory=lambda: [
        {
            "id": "CLUE_01_BROKEN_WATCH",
            "plant_chapter": 1,
            "payoff_chapter": 8,
            "desc": "主角靴底夹层中停摆在 04:17 的老旧黄铜怀表",
            "forbidden_reveal": "严禁在第 8 章前解释怀表停摆与时空裂隙的关联！只许当作寻常遗物描写",
            "state": "播种期",
        },
        {
            "id": "CLUE_02_SHADOW_CODE",
            "plant_chapter": 2,
            "payoff_chapter": 25,
            "desc": "清理司档案室门把手上的三道非标准三角形刻痕",
            "forbidden_reveal": "全书终局秘密！严禁在前期做任何解释，违者质检一票否决",
            "state": "播种期",
        },
    ])

    # 阶梯五：叙事声纹与语言指纹
    pov: str = "受限第三人称 (Close Third Person)"
    tone: str = "民间悬疑质感与高智商生死博弈结合，冷硬肃杀，节奏凌厉"
    banned_words: List[str] = field(default_factory=lambda: list(DEFAULT_BANNED_WORDS))
    voice_sample_text: str = DEFAULT_VOICE_SAMPLE

    # 阶梯六：章节体量与质检门禁
    target_words_per_chapter: int = 3200
    min_words: int = 2500
    max_words: int = 4500
    min_review_score: int = 80


# ---------------------------------------------------------------------------
# 1. 宪法 Markdown 编译器
# ---------------------------------------------------------------------------

def compile_constitution_markdown(data: NovelConstitution) -> str:
    """将结构化澄清数据编译为具有法律效力级的《小说项目宪法》(novel.md)。"""
    factions_md = "\n".join(
        f"- **{f['name']}**：{f['nature']}" for f in data.factions
    )
    rules_md = "\n".join(
        f"{i+1}. {r}" for i, r in enumerate(data.iron_rules)
    )
    cast_md = "\n".join(
        f"- **{c['name']}**（{c['identity']}）：{c['relation']}；[秘密]：{c['secret']}"
        for c in data.supporting_cast
    )
    clues_md = "\n".join(
        f"| `{c['id']}` | 第 {c['plant_chapter']} 章 | 第 {c['payoff_chapter']} 章 | {c['desc']} | {c['forbidden_reveal']} |"
        for c in data.clues_ledger
    )
    banned_md = "、".join(data.banned_words)

    return f"""# 《小说项目最高宪法》(Novel Project Constitution)

> **项目代号**：`{data.slug}`  
> **作品名称**：《{data.title}》  
> **流派题材**：{data.genre}  
> **目标市场**：{data.target_platform}（受众：{data.target_audience}）  
> **生效原则**：**本宪法是全书生产不可逾越的最高法典。所有后续章节起草、润色、审查及设定演进，均受本文件约束。**

---

## 第零条：核心爽点与最高契约 (Core Hook & Contract)

1. **一句话核心概念 (Logline)**：
   > {data.logline}
2. **续写/初创状态**：
   - 模式：{"老书接入续写/提效" if data.is_continuation else "全新项目冷启动"}
   - 背景提要：{data.original_summary or "从零开始构建"}
3. **【一票否决铁律】**：任何章节内容不得违反本宪法中规定的物理规则、战力天花板、主角底线及伏笔揭秘锁定期。

---

## 第一条：世界观法度与绝对禁忌 (World & Cosmology)

### 1.1 现实映射与世界架构
- {data.reality_relation}

### 1.2 力量/超自然/科技体系
- {data.power_system}

### 1.3 不可逾越的法则铁律与终极代价
{rules_md}

### 1.4 核心阵营与根本利益冲突
{factions_md}

---

## 第二条：人物灵魂、知情范围与反 OOC 宪章 (Character Matrix)

### 2.1 主角档案 (POV 锚定者)
- **姓名**：{data.protagonist_name}
- **表面身份**：{data.protagonist_surface_id}
- **隐藏身份**：{data.protagonist_hidden_id}
- **核心动机与执念**：{data.protagonist_motivation}
- **性格缺陷与弱点**：{data.protagonist_flaw}
- **道德底线与逆鳞**：{data.protagonist_moral_boundary}
- **对白声音指纹**：{data.protagonist_voice}

### 2.2 核心对立面 (反派/天灾)
- **对手**：{data.antagonist_name}
- **行动动机**：{data.antagonist_drive}
- **自洽逻辑**：{data.antagonist_logic}

### 2.3 核心配角人际网络
{cast_md}

### 2.4 知情边界守卫原则 (Epistemic Boundary)
- 任何角色严禁凭空获得其物理未在场或未曾获知的情报；
- 违背知情边界的剧情一律判定为 OOC 缺陷，阻断入库。

---

## 第三条：三幕大纲与伏笔生命周期锁定 (Plot & Foreshadowing)

### 3.1 全书三幕总纲
- **第一幕（起）**：{data.three_acts.get('act1_break', '')}
- **第二幕（承/转）**：{data.three_acts.get('act2_twist', '')}
- **第三幕（合）**：{data.three_acts.get('act3_resolution', '')}

### 3.2 首卷即时规划 ({data.vol1_title})
- **首卷核心任务**：{data.vol1_goal}
- **规划章节数**：约 {data.vol1_chapters_count} 章
- **首次重大破局**：目标发生于第 {data.first_breakthrough_chapter} 章

### 3.3 伏笔暗线生命周期总台账 (严格防早泄锁死)
| 伏笔编号 | 播种章节 | 回收章节 | 伏笔物理细节描述 | 提前剧透严厉禁令 |
| :--- | :--- | :--- | :--- | :--- |
{clues_md}

> ⚠️ **质检红线**：若在回收章节之前出现任何超前解说或旁白剧透，`review_qc` 节点强制评分为 0，阻断流转！

---

## 第四条：叙事声纹与抗朱雀检测规范 (Voice & De-AI)

1. **叙事视角**：{data.pov}，摄像机牢牢焊死在主角视网膜上，严禁全知上帝视角！
2. **文风基调**：{data.tone}。
3. **句式节奏**：强制长短句交替，禁止连用三句 25 字以上复合长句，必须穿插 3~7 字极短动词单句。
4. **一票否决禁词表**：
   > {banned_md}

---

## 第五条：流水线工程参数契约 (Pipeline Parameters)

- **单章目标字数**：{data.target_words_per_chapter} 字（有效区间：{data.min_words} ~ {data.max_words} 字）
- **盲审质检硬门槛**：`SCORES.overall >= {data.min_review_score}` 分
- **初始卷名**：{data.vol1_title.split('：')[0] if '：' in data.vol1_title else '第一卷'}
- **首章序号**：1 (格式化: 01)
"""


# ---------------------------------------------------------------------------
# 2. 宪法多维原子分发引擎 (Fan-out Hydration Engine)
# ---------------------------------------------------------------------------

def fan_out_constitution(data: NovelConstitution, project_root: Path) -> Dict[str, List[str]]:
    """将 NovelConstitution 结构化数据全量分发拆解至标准化工业模块目录中。"""
    project_root = project_root.resolve()
    project_root.mkdir(parents=True, exist_ok=True)

    created_files: List[str] = []

    # 1. 写出最高宪法文件 novel.md
    constitution_text = compile_constitution_markdown(data)
    novel_md_path = project_root / "novel.md"
    novel_md_path.write_text(constitution_text, encoding="utf-8")
    created_files.append("novel.md")

    # 2. 设定/世界观/
    world_dir = project_root / "设定" / "世界观"
    world_dir.mkdir(parents=True, exist_ok=True)

    rules_content = f"""# 《{data.title}》世界法则与绝对禁忌

## 1. 现实映射与世界架构
{data.reality_relation}

## 2. 底层力量与科技体系
{data.power_system}

## 3. 绝对铁律与代价机制（严禁吃书）
""" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(data.iron_rules))

    (world_dir / "01_世界法则与禁忌.md").write_text(rules_content, encoding="utf-8")
    created_files.append("设定/世界观/01_世界法则与禁忌.md")

    factions_content = f"""# 《{data.title}》核心阵营势力图谱

## 主要阵营与冲突矩阵
""" + "\n".join(f"### {f['name']}\n- **性质与特征**：{f['nature']}\n" for f in data.factions)
    (world_dir / "02_阵营势力图谱.md").write_text(factions_content, encoding="utf-8")
    created_files.append("设定/世界观/02_阵营势力图谱.md")

    # 3. 设定/人物/
    char_dir = project_root / "设定" / "人物"
    char_dir.mkdir(parents=True, exist_ok=True)

    protagonist_content = f"""# 主角档案：{data.protagonist_name}

## 1. 身份定义
- **表面身份**：{data.protagonist_surface_id}
- **真实/隐藏身份**：{data.protagonist_hidden_id}

## 2. 心理与行为约束
- **核心动机与终极执念**：{data.protagonist_motivation}
- **性格缺陷与不可违背弱点**：{data.protagonist_flaw}
- **道德底线与逆鳞**：{data.protagonist_moral_boundary}
- **对白语言声音指纹**：{data.protagonist_voice}
"""
    (char_dir / f"01_主角_{data.protagonist_name}.md").write_text(protagonist_content, encoding="utf-8")
    created_files.append(f"设定/人物/01_主角_{data.protagonist_name}.md")

    cast_content = f"""# 核心配角与主要对手矩阵

## 一、 主要对立面 (反派/天灾)
- **名称**：{data.antagonist_name}
- **核心动机**：{data.antagonist_drive}
- **自洽行动逻辑**：{data.antagonist_logic}

## 二、 核心配角网络
""" + "\n".join(
        f"### {c['name']}（{c['identity']}）\n"
        f"- **人际矛盾与利益交集**：{c['relation']}\n"
        f"- **角色隐藏秘密**：{c['secret']}\n"
        for c in data.supporting_cast
    )
    (char_dir / "02_核心配角与反派.md").write_text(cast_content, encoding="utf-8")
    created_files.append("设定/人物/02_核心配角与反派.md")

    info_table = f"""# 《{data.title}》全书角色知情状态表 (Information Boundary)

| 关键秘密 / 事实 | {data.protagonist_name} 知情状态 | 核心配角 知情状态 | 核心反派 知情状态 | 读者知情状态 |
| :--- | :--- | :--- | :--- | :--- |
| **金手指/核心秘密真相** | 知晓表象，未知全貌 | 怀疑但未证实 | 正在搜寻下落 | 随主角视点有限知晓 |
| **初始密室/危机诱因** | 陷入其中，紧急调查 | 处于现场，心怀鬼胎 | 遥控注视，按计划进行 | 未知 |
"""
    (char_dir / "03_角色知情状态表.md").write_text(info_table, encoding="utf-8")
    created_files.append("设定/人物/03_角色知情状态表.md")

    # 4. 设定/大纲/
    outline_dir = project_root / "设定" / "大纲"
    outline_dir.mkdir(parents=True, exist_ok=True)

    acts_content = f"""# 《{data.title}》全书三幕总纲

## 第一幕（起）：危机爆发与打破平衡
{data.three_acts.get('act1_break', '')}

## 第二幕（承/转）：阵营博弈与至暗时刻
{data.three_acts.get('act2_twist', '')}

## 第三幕（合）：世界揭秘与终局决战
{data.three_acts.get('act3_resolution', '')}
"""
    (outline_dir / "01_全书三幕总纲.md").write_text(acts_content, encoding="utf-8")
    created_files.append("设定/大纲/01_全书三幕总纲.md")

    vol1_content = f"""# {data.vol1_title} 分章规划细纲

- **卷核心目标**：{data.vol1_goal}
- **预计章节数**：1 ~ {data.vol1_chapters_count} 章
- **首次重大破局**：第 {data.first_breakthrough_chapter} 章

### 第 1 章：初入迷局 (暂定名)
- **核心看点**：危机突如其来打破生活，主角在毫无准备的情况下遭遇第一重规则考验。
- **戏剧冲突**：即时生存危机 vs 关键线索播种。
- **章末钩子**：发现了一件绝对不应该出现在现场的诡异信物。
"""
    (outline_dir / "02_分卷细纲_第一卷.md").write_text(vol1_content, encoding="utf-8")
    created_files.append("设定/大纲/02_分卷细纲_第一卷.md")

    clues_content = f"""# 《{data.title}》伏笔暗线生命周期总台账

| 伏笔标识 | 播种章节 | 回收章节 | 伏笔细节描述 | 锁定状态与剧透禁令 |
| :--- | :--- | :--- | :--- | :--- |
""" + "\n".join(
        f"| `{c['id']}` | 第 {c['plant_chapter']} 章 | 第 {c['payoff_chapter']} 章 | {c['desc']} | {c['state']} ({c['forbidden_reveal']}) |"
        for c in data.clues_ledger
    )
    (outline_dir / "03_伏笔与线索总台账.md").write_text(clues_content, encoding="utf-8")
    created_files.append("设定/大纲/03_伏笔与线索总台账.md")

    # 5. 设定/事实账本/snapshot.json (抗遗忘因果引擎初始基线)
    facts_dir = project_root / "设定" / "事实账本"
    facts_dir.mkdir(parents=True, exist_ok=True)
    initial_snapshot = {
        "version": 1,
        "novel_slug": data.slug,
        "last_updated_chapter": 0,
        "protagonist": {
            "name": data.protagonist_name,
            "status": "健康，警戒",
            "inventory": ["黄铜怀表", "随身匕首"],
            "injuries": [],
            "known_secrets": ["自身拥有异常感知"],
        },
        "active_clues": [c["id"] for c in data.clues_ledger if c.get("state") == "播种期"],
        "world_state": {
            "current_location": "待第1章指定",
            "danger_level": "中危警戒",
        },
    }
    (facts_dir / "snapshot.json").write_text(json.dumps(initial_snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    created_files.append("设定/事实账本/snapshot.json")

    # 6. 资产/voice_sample.md (去 AI 味与文风对齐)
    assets_dir = project_root / "资产"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "voice_sample.md").write_text(data.voice_sample_text, encoding="utf-8")
    created_files.append("资产/voice_sample.md")

    # 双向兼容 assets/ 路径
    assets_alt = project_root / "assets"
    assets_alt.mkdir(parents=True, exist_ok=True)
    (assets_alt / "voice_sample.md").write_text(data.voice_sample_text, encoding="utf-8")

    # 7. 正文/第一卷/ & 工作区/第01章/
    chapters_dir = project_root / "正文" / "第一卷"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    workspace_ch1 = project_root / "工作区" / "第01章"
    workspace_ch1.mkdir(parents=True, exist_ok=True)

    # 8. graph.yaml
    vol_clean = data.vol1_title.split("：")[0] if "：" in data.vol1_title else "第一卷"
    graph_dict = {
        "version": 1,
        "name": f"novel-{data.slug}",
        "params": {
            "chapter_num": 1,
            "chapter_pad": "01",
            "chapter_title": "初入迷局",
            "volume_name": vol_clean,
            "genre": data.genre,
            "tone": data.tone,
            "target_words": data.target_words_per_chapter,
        },
        "nodes": {
            "gather_state": {
                "kind": "agent",
                "model": "gemini-3.8-flash-high",
                "role": "小说前置状态与伏笔总账员",
                "prompt": (
                    "盘点本书当前的世界观规则、人物知情状态以及未回收伏笔。\n"
                    "提取第 {chapter_num} 章（{chapter_title}）必须推进的核心矛盾与读者信息差要点。\n"
                    "输出简明紧凑的章节任务上下文到指定路径。"
                ),
                "inputs": [
                    "novel.md",
                    "设定/事实账本/snapshot.json",
                    "设定/世界观/",
                    "设定/人物/",
                    "设定/大纲/",
                ],
                "outputs": [
                    "工作区/第{chapter_pad}章/01_状态上下文.md",
                ],
                "skills": [
                    "novel-memory-ledger",
                    "novel-context-curator",
                    "novel-clue-foreshadowing",
                    "novel-character-guardian",
                ],
                "assert": {
                    "min_words": 200,
                },
            },
            "draft_chapter": {
                "kind": "agent",
                "after": ["gather_state"],
                "model": "gemini-3.8-flash-high",
                "role": "长篇小说主笔作家",
                "prompt": (
                    "你是一位顶级职业小说家。请严格结合工作区/第{chapter_pad}章/01_状态上下文.md 的任务要点\n"
                    "与设定/大纲/中关于第 {chapter_num} 章剧情设定，撰写本章完整正文。\n"
                    "人物言行与性格必须严密符合设定/人物/中的档案，严禁突兀 OOC 与上帝视角泄密。\n"
                    "在正文末尾设立强烈的悬念钩子。"
                ),
                "skills": [
                    "story-suspense-investigation",
                    "novel-style-narrator",
                    "novel-scene-pacing",
                    "novel-opening-hook",
                    "novel-character-guardian",
                ],
                "inputs": [
                    "工作区/第{chapter_pad}章/01_状态上下文.md",
                    "设定/人物/",
                    "设定/世界观/",
                ],
                "outputs": [
                    "工作区/第{chapter_pad}章/02_正文初稿.md",
                ],
                "assert": {
                    "min_words": data.min_words,
                    "max_words": data.max_words,
                },
            },
            "deai_polish": {
                "kind": "agent",
                "after": ["draft_chapter"],
                "model": "gemini-3.8-flash-high",
                "role": "去 AI 味与文风校准专家",
                "prompt": (
                    "对照 资产/voice_sample.md 中的作者语言风格样本，对 工作区/第{chapter_pad}章/02_正文初稿.md 进行深度去 AI 味润色：\n"
                    "1. 剔除无意义的排比句、机械递进句、假大空抒情与说明文腔调；\n"
                    "2. 增强环境感官细节、微表情与短促有力的动作描写；\n"
                    "3. 将改写后的高质量定稿直接写出到指定文件。"
                ),
                "skills": [
                    "story-deslop",
                    "novel-deai-humanizer",
                    "novel-sensory-grounding",
                    "novel-anti-cliche",
                ],
                "inputs": [
                    "工作区/第{chapter_pad}章/02_正文初稿.md",
                    "资产/voice_sample.md",
                ],
                "outputs": [
                    "工作区/第{chapter_pad}章/03_去AI味润色稿.md",
                ],
                "assert": {
                    "min_words": int(data.min_words * 0.95),
                },
            },
            "review_qc": {
                "kind": "agent",
                "after": ["deai_polish"],
                "model": "claude-opus-4.6-thinking",
                "role": "小说主编与防吃书质检员",
                "prompt": (
                    "对 工作区/第{chapter_pad}章/03_去AI味润色稿.md 进行逐段盲审质检：\n"
                    "- 角色言行是否符合 设定/人物/（严查 OOC 与知情边界越界）；\n"
                    "- 力量体系与物理常识是否符合 设定/世界观/（严查吃书）；\n"
                    "- 检查是否存在提前剧透未到期伏笔（对照 设定/大纲/03_伏笔与线索总台账.md）；\n"
                    "- 情节节奏、爽点与章末追读力评估。\n"
                    "定位到具体句段给出修改建议，并在报告末尾严格输出一行格式：\n"
                    "SCORES: {\"overall\": 88, \"lore\": 92, \"ooc\": 90}"
                ),
                "skills": [
                    "novel-memory-ledger",
                    "story-review",
                    "novel-lore-enforcer",
                    "novel-consistency-auditor",
                    "novel-pacing-evaluator",
                ],
                "inputs": [
                    "工作区/第{chapter_pad}章/03_去AI味润色稿.md",
                    "设定/世界观/",
                    "设定/人物/",
                    "设定/大纲/",
                ],
                "outputs": [
                    "工作区/第{chapter_pad}章/04_盲审质检报告.md",
                ],
                "assert": {
                    "score_field": "overall",
                    "min_score": data.min_review_score,
                },
            },
            "author_accept": {
                "kind": "human",
                "after": ["review_qc"],
                "ask": "请创作者审阅润色稿与审查打分，确认无误后点击放行入库为正式章节。",
                "inputs": [
                    "工作区/第{chapter_pad}章/03_去AI味润色稿.md",
                    "工作区/第{chapter_pad}章/04_盲审质检报告.md",
                ],
                "outputs": [
                    "正文/{volume_name}/第{chapter_pad}章_{chapter_title}.md",
                ],
            },
            "novel_stats": {
                "kind": "command",
                "after": ["author_accept"],
                "run": [
                    "python",
                    "../../shared/novel_stats.py",
                    "--project",
                    ".",
                    "--chapter",
                    "正文/{volume_name}/第{chapter_pad}章_{chapter_title}.md",
                    "--output",
                    "工作区/第{chapter_pad}章/05_章节统计.json",
                ],
                "inputs": [
                    "正文/{volume_name}/第{chapter_pad}章_{chapter_title}.md",
                ],
                "outputs": [
                    "工作区/第{chapter_pad}章/05_章节统计.json",
                ],
            },
        },
    }

    with open(project_root / "graph.yaml", "w", encoding="utf-8") as f:
        yaml.dump(graph_dict, f, allow_unicode=True, sort_keys=False)
    created_files.append("graph.yaml")

    return {"project_root": str(project_root), "created_files": created_files}


# ---------------------------------------------------------------------------
# 3. 命令行交互引导与外挂解析入口
# ---------------------------------------------------------------------------

def run_interactive_interview() -> NovelConstitution:
    """交互式六阶问询引导器。"""
    c = NovelConstitution()
    print("=" * 65)
    print("      笔心 Studio · 工业化小说需求六阶澄清引擎 (Genesis Engine)")
    print("=" * 65)
    print("通过层层递进的提问，我们将共同确立本书的《小说项目最高宪法》(novel.md)。\n")

    # 阶梯一
    print("[阶梯一：商业定位与核心脑洞]")
    slug = input(f"1.1 小说英文标识/目录名 (slug) [默认: {c.slug}]: ").strip() or c.slug
    title = input(f"1.2 小说中文书名 [默认: {c.title}]: ").strip() or c.title
    genre = input(f"1.3 核心流派题材 (如: 悬疑惊悚/高武玄幻/都市脑洞) [默认: {c.genre}]: ").strip() or c.genre
    platform = input(f"1.4 目标发布平台 (番茄小说/起点中文网/微信读书等) [默认: {c.target_platform}]: ").strip() or c.target_platform
    logline = input(f"1.5 一句话核心爽点/金手指/主旨 (Logline) [默认: {c.logline}]: ").strip() or c.logline

    c.slug = slug
    c.title = title
    c.genre = genre
    c.target_platform = platform
    c.logline = logline

    # 阶梯二
    print("\n[阶梯二：世界法则与时空禁忌]")
    c.reality_relation = input(f"2.1 与现实世界的关系 (完全架空/都市暗面) [默认: {c.reality_relation}]: ").strip() or c.reality_relation
    c.power_system = input(f"2.2 力量/超自然/科技体系层级 [默认: {c.power_system}]: ").strip() or c.power_system

    # 阶梯三
    print("\n[阶梯三：人物灵魂与冲突网络]")
    c.protagonist_name = input(f"3.1 主角姓名 [默认: {c.protagonist_name}]: ").strip() or c.protagonist_name
    c.protagonist_surface_id = input(f"3.2 主角表面身份 [默认: {c.protagonist_surface_id}]: ").strip() or c.protagonist_surface_id
    c.protagonist_hidden_id = input(f"3.3 主角隐藏身份/底牌 [默认: {c.protagonist_hidden_id}]: ").strip() or c.protagonist_hidden_id
    c.protagonist_motivation = input(f"3.4 主角核心执念 [默认: {c.protagonist_motivation}]: ").strip() or c.protagonist_motivation

    # 阶梯四
    print("\n[阶梯四：三幕大纲与暗线伏笔]")
    c.vol1_title = input(f"4.1 第一卷卷名 [默认: {c.vol1_title}]: ").strip() or c.vol1_title
    c.vol1_goal = input(f"4.2 第一卷核心破局目标 [默认: {c.vol1_goal}]: ").strip() or c.vol1_goal

    # 阶梯五 & 六
    print("\n[阶梯五 & 六：声纹基调与质检门禁]")
    c.tone = input(f"5.1 文风基调与氛围 [默认: {c.tone}]: ").strip() or c.tone
    words = input(f"6.1 单章目标字数 [默认: {c.target_words_per_chapter}]: ").strip()
    if words.isdigit():
        c.target_words_per_chapter = int(words)
        c.min_words = int(c.target_words_per_chapter * 0.8)
        c.max_words = int(c.target_words_per_chapter * 1.3)

    return c


def load_constitution_from_json(json_path: Path) -> NovelConstitution:
    """从 JSON 配置文件加载澄清数据。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    c = NovelConstitution()
    for k, v in data.items():
        if hasattr(c, k):
            setattr(c, k, v)
    return c


def main():
    parser = argparse.ArgumentParser(description="笔心 Studio 小说需求澄清与最高宪法(novel.md)生成器")
    parser.add_argument("--interactive", action="store_true", help="启动交互式六阶递进问询")
    parser.add_argument("--from-json", type=str, default=None, help="从已有 JSON 文件加载澄清数据")
    parser.add_argument("--slug", type=str, default=None, help="小说英文标识 (slug)")
    parser.add_argument("--title", type=str, default=None, help="小说中文标题")
    parser.add_argument("--genre", type=str, default=None, help="小说题材类别")
    parser.add_argument("--protagonist", type=str, default=None, help="主角姓名")
    parser.add_argument("--logline", type=str, default=None, help="核心爽点/一句话主旨")
    parser.add_argument("--parent", type=str, default="projects", help="项目存放父目录")

    args = parser.parse_args()

    if args.from_json:
        data = load_constitution_from_json(Path(args.from_json))
    elif args.interactive:
        data = run_interactive_interview()
    else:
        # CLI 快捷参数构造
        data = NovelConstitution()
        if args.slug:
            data.slug = args.slug
        if args.title:
            data.title = args.title
        if args.genre:
            data.genre = args.genre
        if args.protagonist:
            data.protagonist_name = args.protagonist
        if args.logline:
            data.logline = args.logline

    target_dir = Path(args.parent) / data.slug
    res = fan_out_constitution(data, target_dir)

    print(f"\n[clarify] 《小说项目宪法》(novel.md) 已订立并完成全量原子分发！")
    print(f"  - 项目工程路径: {res['project_root']}")
    print(f"  - 分发生效文件数: {len(res['created_files'])}")
    for f in res["created_files"]:
        print(f"    * {f}")
    print("\n恭喜！小说最高法典已确立，流水线已就绪。随时可启动第一章全自动创作！")


if __name__ == "__main__":
    main()
