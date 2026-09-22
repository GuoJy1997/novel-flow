# -*- coding: utf-8 -*-
"""章节宪法与质量红线自动化检查工具。"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def count_chinese_and_words(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]", text))
    words = len(re.findall(r"\b[a-zA-Z0-9_-]+\b", text))
    return cjk + words


def check_dialogue_overcrowding(dialogue_ratio: float, dialogue_count: int, total_words: int) -> Tuple[bool, str]:
    """检查是否出现对白过于密集挤压人物描写 (占比>45% 或平均对白间隔过小且总字数多)。"""
    if dialogue_ratio > 45.0:
        return False, f"对白过于密集 (占比 {dialogue_ratio}% > 45%)，挤压了主要角色的心理推演、微表情与战术白描空间！"
    return True, ""


def check_dialogue_density(text: str, max_gap: int = 400) -> Tuple[bool, int, str]:
    """检查是否出现连续超过 max_gap 个字没有对话引号。"""
    # 将文本拆分为含引号段和纯旁白段 (兼容中文引号与英文双引号)
    pattern = re.compile(r'(“[^“”]+”|"[^"\n]+")')
    parts = pattern.split(text)

    max_non_dialogue = 0
    longest_snippet = ""

    for part in parts:
        if pattern.match(part):
            continue
        clean_part = re.sub(r"\s+", "", part)
        part_len = count_chinese_and_words(clean_part)
        if part_len > max_non_dialogue:
            max_non_dialogue = part_len
            longest_snippet = clean_part[:50] + "..." if len(clean_part) > 50 else clean_part

    passed = max_non_dialogue <= max_gap
    return passed, max_non_dialogue, longest_snippet


def check_persona_consistency(text: str) -> List[str]:
    """审查主要角色的人设行为与说话指纹是否崩塌 (OOC 检查)。"""
    issues = []
    # 秦华：自治区干部、战术执行专家，绝不能发表大段汉族古代政治史考据或门阀内幕
    # 检索秦华是否发表深入门阀断代或道门符箓学说的长篇对白
    qin_speeches = re.findall(r'秦华[^\n“”]*?[道说喊喝]：?[“"]([^“”"\n]+)[”"]', text)
    for sp in qin_speeches:
        if any(term in sp for term in ["王敦之乱", "苏峻之乱", "门阀互咬", "琅琊太原两门", "九品中正", "黄老内丹", "天师道祖"]):
            issues.append(f"【秦华人设越界】秦华作为自治区干部，发表了不应由其掌握的深层汉族历史门阀/道门考据: 『{sp[:40]}...』")
    
    # 老莫：隐藏大佬，胸有成竹，绝不可表现为一无所知的新手小白式惊呼或疑惑
    mo_speeches = re.findall(r'老莫[^\n“”]*?[道说喊喝]：?[“"]([^“”"\n]+)[”"]', text)
    for sp in mo_speeches:
        if any(term in sp for term in ["这是怎么回事？", "难道说这是……", "我怎么不知道", "这不可能吧？", "什么是大醮"]):
            issues.append(f"【老莫人设崩塌】老莫作为胸有成竹的隐藏大佬，表现出小白式无知疑惑: 『{sp[:40]}...』")
    return issues


def check_social_addressing(text: str, chapter_num: int) -> List[str]:
    """审查人物称谓是否得体、熟人互动与历史礼仪是否合规。"""
    issues = []

    # 1. 发小称谓：张洋称呼顾君绝不能叫全名“顾君”，必须称“老顾/顾子/君儿”
    zy_speeches = re.findall(r'(?:张洋|洋子)[^\n“”]*?[道说问喊骂喝]：?[“"]([^“”"\n]+)[”"]', text)
    for sp in zy_speeches:
        if "顾君" in sp:
            issues.append(f"【称谓违规】张洋与顾君为生死发小，对白中禁止直呼全名『顾君』，应称『老顾/顾子/君儿』: 『{sp[:40]}...』")

    # 2. 历史门阀礼仪：王羲之、谢安当面称桓温，绝不能直呼“桓温”，必须称“桓公/使君/征西”
    for speaker in ["王羲之", "谢安", "谢万", "王绥之", "杜子恭", "许询"]:
        speeches = re.findall(rf'{speaker}[^\n“”]*?[道说问喊喝]：?[“"]([^“”"\n]+)[”"]', text)
        for sp in speeches:
            if "桓温" in sp or "桓元子" in sp:
                issues.append(f"【门阀礼仪违规】{speaker}在正式场合对白中直呼『桓温/桓元子』失仪！应尊称『桓公/使君/征西』: 『{sp[:40]}...』")

    # 3. 情绪打断动力学：顾君、秦华严禁好莱坞式狂暴怒吼“给我闭嘴/闭嘴！”
    # 顾君为高智商冷幽默程序员，秦华为沉稳体制内干部，打断方式应为接梗、吐槽、战术手势
    for speaker in ["顾君", "秦华"]:
        outbursts = re.findall(rf'{speaker}[^\n“”]*?(?:怒[吼喝道]|喝道|凶[巴巴道]|厉声|呵斥)[^\n“”]*?：?[“"]([^“”"\n]*?(?:闭嘴|给我闭嘴)[^“”"\n]*?)[”"]', text)
        for ob in outbursts:
            issues.append(f"【情绪失真崩坏】{speaker}作为理性克制角色，严禁出现低级狂暴咆哮式『闭嘴』，应改为冷幽默接梗、战术手势警示或逻辑反制: 『{ob[:40]}...』")

        normal_speeches = re.findall(rf'{speaker}[^\n“”]*?[道说问]：?[“"]([^“”"\n]+)[”"]', text)
        for sp in normal_speeches:
            if re.search(r'^(?:你?给我闭嘴[！!]|闭嘴[！!]|别废话[！!]|住口[！!])', sp.strip()):
                issues.append(f"【互动方式粗暴】{speaker}对待队友出现粗暴指令式『{sp.strip()[:20]}』，与人设不符，建议改为具有个人指纹的接梗吐槽或沉稳压制")

    return issues


def check_epistemic_boundaries(text: str, chapter_num: int) -> List[str]:
    """审查是否存在知情越界、前知偷渡、上帝视角剧透。"""
    issues = []

    # 1. 显形前（Ch33末集序写完前），NPC 绝对看不见、感知不到主角团
    if chapter_num < 33:
        for npc in ["王羲之", "谢安", "桓温", "孙绰", "杜子恭", "周彦", "郗超", "侍从", "名士", "仆从"]:
            if re.search(rf'{npc}[^\n。]*?(?:察觉|感知|听到|看见|注意到|盯[着向]|望向)[^\n。]*?(?:顾君|张洋|白艺|秦华|虚空|隐形)', text):
                if not (chapter_num == 33 and "涤杯" in text):
                    issues.append(f"【知情边界越界】第 {chapter_num} 章尚未显形，NPC [{npc}] 绝不能感知/察觉到隐形的主角团！")

    # 2. 名士在变异爆发前（Ch32前），意识里绝无“丧尸/变异”概念，只有“行散/得道”
    if chapter_num < 32:
        if any(term in text for term in ["丧尸", "行尸", "活死人", "尸变", "丧尸毒"]):
            issues.append(f"【概念时代越界】第 {chapter_num} 章灾变尚未爆发，文中绝对禁止出现『丧尸/尸变/行尸』词汇（当时名士眼中只有'行散得道'）！")

    # 3. 前燕-前秦-刘弼幕后黑手，在Ch47前不可被角色直接坐实指控
    if chapter_num < 47:
        speeches = re.findall(r'[“"]([^“”"\n]+)[”"]', text)
        for sp in speeches:
            if "刘弼是特务" in sp or "刘弼投毒" in sp or "刘弼勾结前燕" in sp:
                issues.append(f"【剧透偷跑】第 {chapter_num} 章尚未调查出刘弼真身，对白中严禁提前指控刘弼: 『{sp[:40]}...』")

    return issues


def check_forbidden_terms(text: str, chapter_num: int) -> List[str]:
    violations = []
    # 1. 绝对禁忌词
    taboo_words = ["一死生", "齐彭殇", "虚诞", "妄作"]
    for w in taboo_words:
        if w in text:
            violations.append(f"触发规则杀绝对禁忌词: 【{w}】")

    # 2. 传国玉玺（全书大反转核心，第二副本中前期禁止直接说出）
    if chapter_num < 49:
        if "传国玉玺" in text or "传国玺" in text:
            violations.append("违规泄露核心伏笔: 出现了【传国玉玺/传国玺】（应使用'信物'/'那件东西'等指代）")

    # 3. AI 滥俗词 (De-AI)
    ai_cliches = [
        "宛如", "仿佛在诉说", "在这一刻", "不仅如此", "更重要的是",
        "嘴角勾起一抹弧度", "倒吸一口凉气", "殊不知"
    ]
    for w in ai_cliches:
        if w in text:
            violations.append(f"存在AI套路腔调词: 【{w}】")

    # 4. 秦华卧底身份提前识破
    if chapter_num < 43:
        if re.search(r"秦华.*?(间谍|内奸|叛徒|反派|卧底|卢夏)", text):
            violations.append("知情边界越界: 顾君/白艺提前识破了秦华的间谍/反派身份！")

    return violations


def audit_chapter(file_path: Path, chapter_num: int, min_words: int = 1800, max_words: int = 2500) -> Dict[str, any]:
    text = file_path.read_text(encoding="utf-8", errors="replace")
    total_words = count_chinese_and_words(text)

    dialogues = re.findall(r"“([^“”]+)”", text) + re.findall(r'"([^"\n]+)"', text)
    dialogue_words = sum(count_chinese_and_words(d) for d in dialogues)
    dialogue_ratio = round((dialogue_words / max(1, total_words)) * 100, 1)

    density_pass, max_gap, longest_snippet = check_dialogue_density(text, max_gap=400)
    taboo_violations = check_forbidden_terms(text, chapter_num)
    persona_violations = check_persona_consistency(text)
    addressing_violations = check_social_addressing(text, chapter_num)
    epistemic_violations = check_epistemic_boundaries(text, chapter_num)

    violations = []
    violations.extend(taboo_violations)
    violations.extend(persona_violations)
    violations.extend(addressing_violations)
    violations.extend(epistemic_violations)

    overcrowd_pass, overcrowd_msg = check_dialogue_overcrowding(dialogue_ratio, len(dialogues), total_words)
    if not overcrowd_pass:
        violations.append(overcrowd_msg)

    word_pass = min_words <= total_words <= max_words
    addressing_pass = (len(addressing_violations) == 0)
    epistemic_pass = (len(epistemic_violations) == 0)
    overall_pass = word_pass and density_pass and addressing_pass and epistemic_pass and (len(violations) == 0)

    addressing_score = max(0, 100 - len(addressing_violations) * 20)
    epistemic_score = max(0, 100 - len(epistemic_violations) * 25)
    persona_score = max(0, 100 - len(persona_violations) * 20)
    rule_score = max(0, 100 - len(taboo_violations) * 20)
    density_score = 95 if density_pass else max(50, 95 - (max_gap - 220) // 5)
    word_score = 95 if word_pass else (80 if total_words >= 1600 else 60)

    overall_score = round(
        rule_score * 0.2 +
        addressing_score * 0.2 +
        epistemic_score * 0.2 +
        persona_score * 0.15 +
        density_score * 0.15 +
        word_score * 0.1
    )

    return {
        "file": file_path.name,
        "chapter_num": chapter_num,
        "total_words": total_words,
        "dialogue_ratio": dialogue_ratio,
        "dialogue_count": len(dialogues),
        "word_pass": word_pass,
        "density_pass": density_pass,
        "addressing_pass": addressing_pass,
        "epistemic_pass": epistemic_pass,
        "max_gap": max_gap,
        "longest_non_dialogue_snippet": longest_snippet,
        "violations": violations,
        "addressing_violations": addressing_violations,
        "epistemic_violations": epistemic_violations,
        "overall_pass": overall_pass,
        "scores": {
            "overall": overall_score,
            "addressing": addressing_score,
            "epistemic_boundary": epistemic_score,
            "persona": persona_score,
            "rules": rule_score,
            "dialogue_density": density_score,
            "word_count": word_score
        }
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="章节宪法检查器")
    parser.add_argument("file", help="待审查文件路径")
    parser.add_argument("--chapter", type=int, default=37, help="章节编号")
    parser.add_argument("--min", type=int, default=1800, help="最低字数")
    parser.add_argument("--max", type=int, default=2500, help="最高字数")
    args = parser.parse_args()

    p = Path(args.file)
    if not p.is_file():
        print(f"Error: 文件不存在 {p}")
        sys.exit(1)

    res = audit_chapter(p, args.chapter, args.min, args.max)
    print(f"=== 章节审查报告: {res['file']} (第 {res['chapter_num']} 章) ===")
    print(f"总字数: {res['total_words']} (达标: {res['word_pass']}, 区间: {args.min}~{args.max})")
    print(f"对话占比: {res['dialogue_ratio']}% (共 {res['dialogue_count']} 句对白)")
    print(f"最大连续旁白字数: {res['max_gap']} (达标: {res['density_pass']}, 允许上限 400 字)")
    print(f"称谓礼仪得体: {'✅ 达标' if res['addressing_pass'] else '❌ 存在称谓违规或狂暴吼叫'}")
    print(f"知情视界合规: {'✅ 达标' if res['epistemic_pass'] else '❌ 存在前知偷渡或上帝视角剧透'}")
    if not res["density_pass"]:
        print(f"  超长旁白片段: {res['longest_non_dialogue_snippet']}")
    if res["violations"]:
        print(f"❌ 违规项 ({len(res['violations'])}):")
        for v in res["violations"]:
            print(f"  - {v}")
    else:
        print("✅ 无任何禁忌词与AI套路违规")
    print(f"SCORES: {res['scores']}")
    sys.exit(0 if res["overall_pass"] else 1)


if __name__ == "__main__":
    main()
