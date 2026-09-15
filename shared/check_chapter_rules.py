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


def check_dialogue_density(text: str, max_gap: int = 220) -> Tuple[bool, int, str]:
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

    density_pass, max_gap, longest_snippet = check_dialogue_density(text, max_gap=220)
    violations = check_forbidden_terms(text, chapter_num)

    word_pass = min_words <= total_words <= max_words
    overall_pass = word_pass and density_pass and (len(violations) == 0)

    rule_score = max(0, 100 - len(violations) * 20)
    density_score = 95 if density_pass else max(50, 95 - (max_gap - 220) // 5)
    word_score = 95 if word_pass else (80 if total_words >= 1600 else 60)
    overall_score = round(rule_score * 0.4 + density_score * 0.3 + word_score * 0.3)

    return {
        "file": file_path.name,
        "chapter_num": chapter_num,
        "total_words": total_words,
        "dialogue_ratio": dialogue_ratio,
        "dialogue_count": len(dialogues),
        "word_pass": word_pass,
        "density_pass": density_pass,
        "max_gap": max_gap,
        "longest_non_dialogue_snippet": longest_snippet,
        "violations": violations,
        "overall_pass": overall_pass,
        "scores": {
            "overall": overall_score,
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
    print(f"最大连续旁白字数: {res['max_gap']} (达标: {res['density_pass']}, 允许上限 220 字)")
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
