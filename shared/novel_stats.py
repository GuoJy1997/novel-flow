# -*- coding: utf-8 -*-
"""小说文本统计与分析脚本（0-Token Command 节点工具）。

功能：
1. 统计指定章节或全书有效字数、段落数、对话占比
2. 扫描关键角色（从 relations.md 或设定库读取）的登场与互动频次
3. 统计伏笔标记 [CLUE:xxx] 与高潮转折点
4. 产出结构化统计报告 novel_stats.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List


def count_words(text: str) -> int:
    """中文字符 + 英文单词数。"""
    cjk = len(re.findall(r"[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]", text))
    words = len(re.findall(r"\b[a-zA-Z0-9_-]+\b", text))
    return cjk + words


def analyze_chapter(chapter_path: Path, characters: List[str]) -> Dict[str, Any]:
    text = chapter_path.read_text(encoding="utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # 提取所有引号内对话内容
    dialogues = re.findall(r"“([^“”]+)”", text)
    dialogue_words = sum(count_words(d) for d in dialogues)
    total_words = count_words(text)

    dialogue_ratio = round((dialogue_words / max(1, total_words)) * 100, 1)

    # 统计角色出场频次
    char_counts = {}
    for char in characters:
        count = len(re.findall(re.escape(char), text))
        if count > 0:
            char_counts[char] = count

    # 扫描伏笔标记
    clues = re.findall(r"\[CLUE:([^\]]+)\]", text)

    return {
        "file": chapter_path.name,
        "total_words": total_words,
        "paragraphs": len(lines),
        "dialogue_words": dialogue_words,
        "dialogue_ratio_percent": dialogue_ratio,
        "character_mentions": char_counts,
        "clues_detected": clues,
    }


def main():
    parser = argparse.ArgumentParser(description="小说文本分析工具")
    parser.add_argument("--project", default=".", help="小说项目根目录")
    parser.add_argument("--chapter", default=None, help="指定分析章节文件名或编号")
    parser.add_argument("--out", "--output", dest="out", default="workflow/novel_stats.json", help="输出 json 路径")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    out_path = project_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 优先从 设定/人物/ 目录或 relations.md 提取主要角色名
    characters = ["主角", "配角"]
    char_texts = []
    char_dir = project_root / "设定" / "人物"
    if char_dir.is_dir():
        for p in char_dir.glob("*.md"):
            char_texts.append(p.read_text(encoding="utf-8", errors="replace"))
    rel_path = project_root / "relations.md"
    if rel_path.is_file():
        char_texts.append(rel_path.read_text(encoding="utf-8", errors="replace"))

    if char_texts:
        all_text = "\n".join(char_texts)
        found_chars = re.findall(r"\*\*([^\*]+)\*\*", all_text)
        if found_chars:
            characters = list(set(found_chars[:30]))

    # 扫描正文章节（支持 正文/ 深度子目录与传统 chapters/ 目录）
    stats_list = []
    chapter_candidates = []

    # 如果直接指定了具体章节路径
    if args.chapter:
        target_path = project_root / args.chapter
        if target_path.is_file():
            chapter_candidates.append(target_path)

    if not chapter_candidates:
        search_dirs = [project_root / "正文", project_root / "chapters"]
        for sdir in search_dirs:
            if sdir.is_dir():
                for ch_file in sorted(sdir.rglob("*.md")):
                    if args.chapter and args.chapter not in ch_file.name and args.chapter not in str(ch_file):
                        continue
                    chapter_candidates.append(ch_file)

    for ch_file in chapter_candidates:
        stats_list.append(analyze_chapter(ch_file, characters))

    result = {
        "project": project_root.name,
        "chapters_analyzed": len(stats_list),
        "total_book_words": sum(s["total_words"] for s in stats_list),
        "chapters": stats_list,
    }

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[novel_stats] 分析完成，产出已落盘: {out_path} (统计章节: {len(stats_list)} 章, 共 {result['total_book_words']} 字)")


if __name__ == "__main__":
    main()
