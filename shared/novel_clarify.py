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

from chapter_templates import reference

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

> **核心流派对标**：《十日终焉》（高智商推演/生死博弈/通俗白话） × 《诡舍》（生理恐惧惊悚/感官白描/情绪沉浸）

## 一、 核心文风四大铁律 (Voice Commandments)

1. **语言底色：现代通俗白话主导（90%~95%）**：
   - 坚决杜绝大段“半文半白”或者假大空的书面之乎者也，行文必须通透、利落、现代、富有阅读冲击力。
   - **半文半白/古意字词仅占 5%~10%**：仅在触及特定古籍残卷、青铜古铭、神秘符文或具有特定身份的历史人物（如魏晋名士）偶发沉吟时，作为气氛调味的“点睛硬骨”，绝不作为全篇主干叙述！

2. **心理推演与生理情绪并重（严禁情感空心化）**：
   - **生理恐惧与应激白描（对标《诡舍》）**：严禁直接贴“他感到极度害怕”等无力标签。必须刻画生理反应——喉咙发紧像吞了砂纸、后颈寒毛倒竖、掌心冷汗浸透刀柄、耳膜里全是自己擂鼓般的心跳声、吸入肺部的空气像带冰碴的刀子。
   - **高智商齿轮咬合与博弈推演（对标《十日终焉》）**：主角的大脑是超频运转的生存逻辑推演器。在极端恐惧下，肾上腺素逼迫神经疯狂运算：怀疑对手动机、拆解规则漏洞、捕捉微表情（瞳孔收缩、指尖颤动、呼吸频率）、预设多重推演分支。
   - **情绪执念与生死悲悯**：面对绝境、淘汰与同伴倒下，必须有真实的人性震颤、痛楚、不甘与狠厉，绝不可将人物写成冰冷没有情绪的剧情触发器。

3. **对话带刺与微表情博弈**：
   - 每一句台词都在争夺生机或隐蔽试探，充满潜台词。
   - 杜绝说明文式对白，穿插市井紧绷感与黑色幽默（“合着咱们九死一生进来，是给人当开门钥匙的？”）。
   - **【质检死线】**：严禁连续 200 字无对白引号！

4. **短句破进与感官白描**：
   - 拆解 25 字以上复合长从句，多用 3~8 字高频动词短句连续破进。
   - 拒绝形容词堆砌，只写物理硬细节：剥落的生锈铁皮、指甲抠进石缝溢出的血沫、湿烂发霉的气味。

---

## 二、 风格对照黄金基准片段 (十日终焉 × 诡舍 生死推演示范)

手电筒光束落在那扇锈死的大铁门上。
光斑在发抖。
不是光在抖，是陆巡握着手电筒的右手小臂在痉挛。
生理本能无法骗人。他的心脏在胸腔里剧烈撞击，像一头困在铁笼里快要撞碎肋骨的兽。冷汗顺着下巴尖滑下来，砸在冰凉的手背上，激起一阵刺骨的麻痒。
身后的通道一片死寂。
刚才那种湿漉漉的拖行声停了。停在距离他们不到十米处的拐角暗处。
“跑……跑啊！”周胖子两排牙齿在疯狂打架，声音抖得像筛糠，伸手就去拽门栓。
“别碰！”
陆巡一把扣住周胖子的手腕。手指捏得发白，指甲深深陷进皮肉里。
周胖子痛得倒抽气：“门没锁！拉开就能出去！你想死别拉上我！”
“你低头看门把手。”陆巡声音压到极低，喉咙干涩得像是被砂纸狠狠刮过。
门把手是生铁铸的，上面结着一层暗红色的锈壳。但把手下方，垂着三根细如蛛丝的红线，红线另一端，连着门框里侧一枚微弱泛光的古旧铜铃。
铜铃上刻着四个隐约可见的小篆：【开门见煞】。
半文半白的古篆泛着妖异的暗青，但在陆巡眼里，这是最致命的规则陷阱。
“如果门真的能走，上一批进来的人为什么全死在门后五米的地方？”
陆巡死死盯着那枚铜铃，大脑像超频运转的齿轮，疯狂咬合推演：
——如果拉门，铜铃必响。
——规则第三条说：‘声起，生绝’。
——但如果门不是生路，为什么背后的怪物偏偏把他们往这扇门前驱赶？
冷汗渗进眼眶，带来火辣辣的刺痛。陆巡连眨都不眨一下。
“怪物不是在猎杀我们。”陆巡喉结滚动了一下，瞳孔收缩如针尖，“它是在用恐怖逼我们替它拉开这扇门。”
它进不去这扇门。
它需要活人的手，去扯断那三根红线。
“那……那怎么办？”周胖子的哭腔已经带了绝望，双腿一软，几乎跪在地上。
身后的黑暗里，黏腻的脚步声再次响了起来。
一步。
两步。
距离拐角，只剩五米。
空气里弥漫着一股浓重得令人作呕的福尔马林与烂泥腥气。
陆巡反手从靴底拔出短刀，冰冷的刀刃贴在手心，剧痛让他的神经瞬间清醒到极致。
“退后。”陆巡盯着拐角处渐渐拉长的黑色扭曲阴影，声音很轻，却透着一股被逼入绝境后的疯狂冷冽，“它想让我们开门，说明它怕这门后的东西。那就——让它自己来开。”
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

    # 阶梯五：叙事声纹与语言风格定制 (Narrative Voice & Style)
    pov: str = "受限第三人称 (Close Third Person)"
    tone: str = "《十日终焉》×《诡舍》高智商生死博弈与心理惊悚，以现代通俗白话为主，情绪与心理高压紧绷"
    style_archetype: str = "十日终焉×诡舍 (现代通俗白话/生死博弈/深度心理悬疑)"
    classical_ratio: str = "纯现代通俗白话占比 90%~95%，半文半白/古意字词仅占 5%~10% 适度穿插"
    psychological_depth: str = "高密度心理推演与生理应激白描（心率、冷汗、微表情、多步推演反制），严禁削弱情绪"
    dialogue_style: str = "高密度对白博弈、带刺试探、微表情信息差交锋，严禁连续 200 字无对白"
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
3. **文风流派对标**：{data.style_archetype}。
4. **语体与文言配比**：{data.classical_ratio}。坚决杜绝大段半文半白堆砌，保持现代白话的阅读通透感与极速叙事节奏。
5. **心理与情绪流铁律**：{data.psychological_depth}。每一场危机必须有真实的恐惧生理应激（瞳孔收缩、心脏狂跳、冷汗渗出）与主角高速运转的推演逻辑，角色绝不可写成麻木工具人！
6. **对话张力与密度**：{data.dialogue_style}。正文严禁出现连续 200 字无对白引号！
7. **句式节奏**：强制长短句交替，禁止连用三句 25 字以上复合长句，必须穿插 3~7 字极短动词单句。
8. **一票否决禁词表**：
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
        "style_constitution": {
            "style_archetype": data.style_archetype,
            "classical_ratio": data.classical_ratio,
            "psychological_depth": data.psychological_depth,
            "dialogue_style": data.dialogue_style,
        },
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

    # 8. graph.yaml：只持久化统一十节点模板引用，章级参数仅使用业务白名单。
    vol_clean = data.vol1_title.split("：")[0] if "：" in data.vol1_title else "第一卷"
    graph_dict = reference({
        "chapter_num": 1,
        "chapter_title": "初入迷局",
        "volume_name": vol_clean,
        "genre": data.genre,
        "tone": data.tone,
        "target_words": data.target_words_per_chapter,
        "chapter_workspace": "工作区/第{chapter_pad}章",
        "chapter_output": "正文/{volume_name}/第{chapter_pad}章_{chapter_title}.md",
        "voice_sample": "资产/voice_sample.md",
    })
    graph_dict["name"] = f"novel-{data.slug}"
    style_prompt = (
        "本书文风补充：结合 novel.md 与 设定/事实账本/snapshot.json 中的用户约定执行当前任务。\n"
        f"- 叙事视角：{data.pov}\n"
        f"- 文风流派对标：{data.style_archetype}\n"
        f"- 语体与文言配比：{data.classical_ratio}\n"
        f"- 心理与情绪描写：{data.psychological_depth}\n"
        f"- 对话风格：{data.dialogue_style}\n"
        f"- 禁词表：{'、'.join(data.banned_words)}"
    )
    # 用户文风与事实资料只作追加，不改写模板的模型、技能、质量门禁或输出契约。
    for node_id in (
        "explore_context", "scene_beats", "draft_chapter", "deai_polish",
        "audit_persona", "review_qc",
    ):
        patch = graph_dict["overrides"].setdefault(node_id, {})
        patch["prompt_append"] = style_prompt
        patch.setdefault("inputs_add", []).extend([
            "novel.md", "设定/事实账本/snapshot.json",
        ])

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

    # 阶梯五：文风声纹与语言风格定制 (Narrative Voice & Style)
    print("\n[阶梯五：文风声纹与语言风格定制 (Narrative Voice & Style)]")
    print("请指定小说的核心文风/语言风格：")
    print("  [1] 《十日终焉》×《诡舍》原型 (推荐：现代通俗白话90%+、高智商推演、生理恐惧与紧绷心理流、适度穿插5%古雅点缀)")
    print("  [2] 硬核悬疑探险原型 (对标《鬼吹灯》：江湖黑话、民俗考据、粗粝写实动作)")
    print("  [3] 纯现代都市暗面冷硬风 (对标经典美式硬汉侦探/新怪谈)")
    print("  [4] 自定义文风")
    style_choice = input("请选择预设序号 [默认: 1]: ").strip() or "1"
    if style_choice == "1":
        c.style_archetype = "十日终焉×诡舍 (现代通俗白话/生死博弈/深度心理悬疑)"
        c.tone = "现代通俗白话生死博弈，强心理推理与生理恐惧紧绷，半文半白仅适量穿插"
        c.classical_ratio = "纯现代通俗白话占比 90%~95%，半文半白/古雅字词仅占 5%~10% 作为气氛点缀"
        c.psychological_depth = "极高深度心理推演与生理恐惧应激（心率、冷汗、微表情测算、多重假设推演），绝不削弱情绪"
    elif style_choice == "2":
        c.style_archetype = "鬼吹灯原型 (江湖黑话/民俗考据/硬核探险)"
        c.tone = "粗粝写实、民俗考据扎实、快节奏动作与市井对白"
        c.classical_ratio = "现代白话85%，民俗黑话与古籍考据占15%"
    elif style_choice == "3":
        c.style_archetype = "都市冷硬悬疑 (冷峻克制/快节奏追索)"
        c.tone = "冷硬短促、心理压迫感强、注重细节物证"
        c.classical_ratio = "纯现代白话 100%"
    else:
        c.style_archetype = input(f"请输入自定义文风原型 [默认: {c.style_archetype}]: ").strip() or c.style_archetype
        c.classical_ratio = input(f"请输入文白配比要求 [默认: {c.classical_ratio}]: ").strip() or c.classical_ratio

    tone_in = input(f"5.1 文风基调与情绪氛围 [默认: {c.tone}]: ").strip()
    if tone_in:
        c.tone = tone_in
    ratio_in = input(f"5.2 文白配比说明 [默认: {c.classical_ratio}]: ").strip()
    if ratio_in:
        c.classical_ratio = ratio_in
    psy_in = input(f"5.3 心理与情绪描写要求 [默认: {c.psychological_depth}]: ").strip()
    if psy_in:
        c.psychological_depth = psy_in

    # 阶梯六：章节体量与质检门禁
    print("\n[阶梯六：章节体量与质检门禁]")
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
    parser.add_argument("--style-archetype", type=str, default=None, help="文风原型（如：十日终焉×诡舍）")
    parser.add_argument("--classical-ratio", type=str, default=None, help="文白配比（如：白话90%+，文言5%~10%）")
    parser.add_argument("--psychological-depth", type=str, default=None, help="心理与情绪描写要求")
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
        if args.style_archetype:
            data.style_archetype = args.style_archetype
        if args.classical_ratio:
            data.classical_ratio = args.classical_ratio
        if args.psychological_depth:
            data.psychological_depth = args.psychological_depth

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
