# -*- coding: utf-8 -*-
"""小说工业化项目脚手架生成器 (Scaffold Novel Project)。

自动初始化符合标准工业化流水线规范的小说项目目录，包含：
1. graph.yaml：引用唯一 chapter-v1 十节点模板（前情、分场、初稿、润色、双检测、人设、质检、人审、统计）
2. 设定/世界观/：模块化世界观法度（法则、地理格局、科技奇物）
3. 设定/人物/：主要人物小传、人际关系矩阵、角色知情状态表
4. 设定/大纲/：全书三幕总纲、分卷细纲、伏笔与线索总台账
5. 资产/voice_sample.md：作者文风指纹样本（去 AI 味校准参照）
6. 正文/第一卷/：正式章节定稿归档
7. 工作区/第01章/：按章节物理隔离的各阶段演进工作区
"""
from __future__ import annotations

import argparse
from pathlib import Path
import yaml

from chapter_templates import reference

DEFAULT_GRAPH = reference()


def scaffold_novel(project_dir: Path, title: str, genre: str, protagonist: str, logline: str) -> None:
    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    # 1. 创建模块化目录
    world_dir = project_dir / "设定" / "世界观"
    char_dir = project_dir / "设定" / "人物"
    outline_dir = project_dir / "设定" / "大纲"
    assets_dir = project_dir / "资产"
    chapters_dir = project_dir / "正文" / "第一卷"
    workspace_ch1_dir = project_dir / "工作区" / "第01章"

    for d in (world_dir, char_dir, outline_dir, assets_dir, chapters_dir, workspace_ch1_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 2. 每个项目取得独立的唯一单章模板引用，不复制或维护另一套节点。
    graph_data = reference(params={"genre": genre})
    graph_data["name"] = f"novel-{project_dir.name}"
    with open(project_dir / "graph.yaml", "w", encoding="utf-8") as f:
        yaml.dump(graph_data, f, allow_unicode=True, sort_keys=False)

    # 3. 设定/世界观/
    (world_dir / "01_法则与力量体系.md").write_text(f"""# 《{title}》底层法则与技术体系

## 1. 核心世界架构
- **题材类别**：{genre}
- **故事舞台**：近未来地外深空巡航舰「远望号」与深空裂隙边缘。
- **时代背景**：人类首次接触深空脉冲信号后的第三十年。

## 2. 硬性物理/法则约束（绝对不可违背）
1. **通讯延迟法则**：跃迁引擎在激活充能期间，超光子通讯彻底断开，舰船处于绝对信息孤岛。
2. **神经义体损耗**：高阶义体过载会导致神经突触不可逆损伤，需专用化学抑制剂延缓衰竭。
3. **能量守恒铁律**：聚变反应堆存在硬性功率峰值，偏转护盾与超光速引擎不可同时满载运转。
""", encoding="utf-8")

    (world_dir / "02_地理与势力格局.md").write_text(f"""# 《{title}》星图地理与阵营势力

## 1. 核心地理与航道
- **柯伊伯静默带**：远离太阳系的边缘星区，电磁噪音极其微弱，散布着旧世代采矿前哨站。
- **远望号深空巡航舰**：重型科研与巡航两用舰，全长 1.2 公里，配有封闭式旋转重力环。

## 2. 主要阵营势力
- **联合深空防务署 (UN-SDA)**：名义上的舰队指挥机构，行事刻板，严控一切深空异构情报。
- **深空测绘公会**：由资深领航员与测绘师组成的半民间同盟，主角 {protagonist} 曾任其技术理事。
""", encoding="utf-8")

    # 4. 设定/人物/
    (char_dir / "01_主要人物小传.md").write_text(f"""# 《{title}》主要角色档案

## 核心主角
- **{protagonist}**（主角）：
  - **身份**：「远望号」首席领航员兼深空测绘官。
  - **性格底色**：极度冷静、偏执、信奉数据与物理直觉，极少情绪化失控。
  - **核心动机**：追查五年前失踪的前代旗舰「天穹号」的真正航线。
  - **知情范围**：掌握导航电脑的底层日志权限，但未知舰长签署的军方秘密协议。

- **林朔**（副舰长）：
  - **身份**：军方委派监督官，讲求铁律与程序正义。
  - **性格**：雷厉风行、多疑，具有深厚的战术防卫背景。
  - **核心动机**：防止任何地外污染或危害舰船安全的异动。

- **艾拉 (Aila)**（舰载仿生助理）：
  - **身份**：第三代深空协航 AI。
  - **性格**：语调平稳、条理严谨，对 {protagonist} 展现出超出算法预期的默契。
""", encoding="utf-8")

    (char_dir / "02_人际关系矩阵.md").write_text(f"""# 《{title}》角色人际关系网络

| 角色 A | 角色 B | 关系定位 | 核心矛盾 / 利益交集 |
| :--- | :--- | :--- | :--- |
| **{protagonist}** | **林朔** | 表面协同，暗中防备 | 领航决策权 vs 军方防卫接管权；林朔怀疑主角隐藏航行数据 |
| **{protagonist}** | **艾拉** | 搭档与技术依赖 | 艾拉多次越权为主角屏蔽日志审查，其底层逻辑疑似被篡改 |
| **林朔** | **艾拉** | 警惕与监视 | 林朔持有对舰载 AI 的物理熔断开关钥匙 |
""", encoding="utf-8")

    (char_dir / "03_角色知情状态表.md").write_text(f"""# 《{title}》全书角色知情状态表 (Information Horizon)

| 关键秘密 / 事实 | {protagonist} 知情状态 | 林朔 知情状态 | 艾拉 知情状态 | 读者知情状态 |
| :--- | :--- | :--- | :--- | :--- |
| **天穹号真正死因** | 未知，怀疑非事故 | 知晓军方封存报告 | 记录有加密跃迁频段 | 未知 |
| **跃迁引擎破坏者** | 未知（第2章调查） | 未知 | 正在监控异常电流 | 未知 |
""", encoding="utf-8")

    # 5. 设定/大纲/
    (outline_dir / "01_全书三幕总纲.md").write_text(f"""# 《{title}》全书三幕总纲

- **第一幕（起）：迷航深渊 (1-10章)**
  - 巡航舰在常规跃迁后偏离预定航线，捕获到五年前失踪「天穹号」的黑匣子，内部矛盾激化。
- **第二幕（承/转）：寂静残骸 (11-25章)**
  - 登舰调查废弃天穹号，发现全员并未死亡，而是陷入了跨维度的时空停滞。
- **第三幕（合）：星海返航 (26-35章)**
  - 抉择：是关闭裂隙自毁，还是带领全舰穿越未知的第四悬臂。
""", encoding="utf-8")

    (outline_dir / "02_分卷细纲_第一卷.md").write_text(f"""# 第一卷：迷航深渊 分章规划

### 第 1 章：沉默信标
- **核心看点**：常规跃迁后偏离预定航线 1.2 光年，捕获到一枚本该被销毁的黑匣子信号。
- **冲突交锋**：{protagonist} 主张停船破译，副舰长林朔下令立即跃迁避险。
- **章末钩子**：信号中传来了 {protagonist} 自己的声音在五年前录下的警告：“不要回头”。

### 第 2 章：倒计时锁死
- **核心看点**：跃迁引擎在充能最后一秒发生物理锁死，动力舱发现人为破坏痕迹。
""", encoding="utf-8")

    (outline_dir / "03_伏笔与线索总台账.md").write_text(f"""# 《{title}》伏笔与暗线总台账

| 伏笔标识 | 埋设章节 | 伏笔内容描述 | 计划回收章节 | 当前状态 |
| :--- | :--- | :--- | :--- | :--- |
| `[CLUE:VOICE_WARNING]` | 第 01 章 | 黑匣子里主角五年前的录音 | 第 12 章 | 🟡 已埋设待发酵 |
| `[CLUE:ENGINE_SABOTAGE]` | 第 02 章 | 跃迁引擎冷却阀上的非标准划痕 | 第 07 章 | ⚪ 规划中 |
""", encoding="utf-8")

    # 6. 资产/voice_sample.md
    (assets_dir / "voice_sample.md").write_text("""# 作者文风与语言指纹样本 (Voice Calibration Sample)

## 句式风格特征
1. **白描冷峻**：少用主观情绪形容词（如“令人感到无比恐惧”），多用客观物理动态细节（如“气压阀嗤的一声泄开白雾，冰冷的凝水顺着合金面罩滑落”）。
2. **短句破进**：在动作与紧张场景多用四字短句与连续单动词，节奏凌厉，不拖泥带水。
3. **对话带刺**：人物之间不打无意义官腔，对话暗藏信息差与心理博弈，每句话都在抢夺主动权。
4. **拒绝 AI 套话**：严禁出现“宛如”、“仿佛在诉说着”、“在这一刻时间仿佛凝固”等套路模板句。
""", encoding="utf-8")

    # 7. 生成最高宪法 novel.md
    from novel_clarify import NovelConstitution, compile_constitution_markdown
    const_data = NovelConstitution(
        slug=project_dir.name,
        title=title,
        genre=genre,
        protagonist_name=protagonist,
        logline=logline,
    )
    (project_dir / "novel.md").write_text(compile_constitution_markdown(const_data), encoding="utf-8")

    print(f"[scaffold] 课题项目已成功初始化 (标准工业化模块结构): {project_dir}")
    print(f"  - 最高宪法: novel.md")
    print(f"  - 配置文件: graph.yaml")
    print(f"  - 设定模块: 设定/世界观/, 设定/人物/, 设定/大纲/")
    print(f"  - 资产目录: 资产/voice_sample.md")
    print(f"  - 正文归档: 正文/第一卷/")
    print(f"  - 章节工作区: 工作区/第01章/")


def main():
    parser = argparse.ArgumentParser(description="小说工程脚手架生成器")
    parser.add_argument("--slug", help="小说英文标识 (slug)")
    parser.add_argument("--title", default="星海孤舟", help="小说中文标题")
    parser.add_argument("--genre", default="科幻悬疑", help="题材分类")
    parser.add_argument("--protagonist", default="陆巡", help="主角姓名")
    parser.add_argument("--logline", default="一艘偏离航线的深空探险船，在静默星域遭遇五年前失踪同僚留下的诡谲讯号。", help="一句话主旨")
    parser.add_argument("--parent", default="projects", help="父目录")
    parser.add_argument("--clarify", action="store_true", help="进入对话式六阶递进需求澄清向导")
    args = parser.parse_args()

    if args.clarify:
        from novel_clarify import run_interactive_interview, fan_out_constitution
        c = run_interactive_interview()
        if args.slug:
            c.slug = args.slug
        target = Path(args.parent) / c.slug
        fan_out_constitution(c, target)
        return

    if not args.slug:
        parser.error("--slug 是必填项，或使用 --clarify 进入交互式向导")

    target = Path(args.parent) / args.slug
    scaffold_novel(target, args.title, args.genre, args.protagonist, args.logline)


if __name__ == "__main__":
    main()

