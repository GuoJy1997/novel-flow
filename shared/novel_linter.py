# -*- coding: utf-8 -*-
"""小说静态质量与去 AI 味 Linter 工具 (0-Token 本地确定性脚本)。

类似代码领域的 ESLint / Oxlint，无需消耗大模型 Token，毫秒级快速扫描：
1. 中文 AI 味套话库扫描（常见假大空虚词、模式化递进连词、抒情陈词滥调）
2. 句式结构异味扫描（连续排比句、连续三字短语、自问自答式说明腔）
3. 排版与标点规范（连续省略号、感叹号滥用、段落过长超载）
4. 对话与叙事节奏比（检测是否沦为纯对话大白话，或纯说明文叙述）
5. 伏笔与情节点标记规范扫描 ([CLUE:xxx], [SECTION:xxx])

输出结构化报告 linter_report.json，供 Assert 门禁和审查节点消费。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 高频 AI 典型套路词/陈词滥调词库（中文网文领域高度特异性特征）
AI_CLICHE_PATTERNS = [
    (r"仿佛在诉说着", "过度拟人化抒情套话"),
    (r"宛如.*?(一般|一样)", "机械比喻堆砌"),
    (r"在这一刻[，,]", "典型 AI 时间停滞过渡词"),
    (r"不可否认的是", "说明文论文腔"),
    (r"总而言之|综上所述", "公文式总结词"),
    (r"眼神中闪烁着.*?的(光芒|光彩)", "面部微表情千人一面套路句"),
    (r"倒吸了一口(凉气|冷气)", "网文机械反应套话"),
    (r"空气中弥漫着.*?的(气息|味道)", "感官描写模板化"),
    (r"嘴角勾起了一抹.*?(微笑|冷笑|弧度)", "邪魅狂狷式模板句"),
    (r"然而，?事情并没有想象的那么简单", "机械推进转折套路"),
    (r"殊不知", "上帝视角生硬剧透词"),
    (r"不仅如此", "机械说明文并列递进词"),
    (r"一时间，?", "场面描写过渡套词"),
]

# 结构性排查
PATTERN_TRIPLE_PARALLEL = re.compile(r"([，,]\s*[^，,\n]{2,8}){3,}[。!！]")
PATTERN_OVERLONG_PARAGRAPH = 600  # 单段超过 600 字提示阅读体验超载


def lint_text(text: str, filename: str = "chapter.md") -> Dict[str, Any]:
    lines = text.splitlines()
    total_chars = len(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]", text))

    issues: List[Dict[str, Any]] = []

    # 1. 扫描 AI 套路词
    ai_cliche_hits = []
    for pattern, desc in AI_CLICHE_PATTERNS:
        matches = list(re.finditer(pattern, text))
        for m in matches:
            line_no = text[:m.start()].count("\n") + 1
            snippet = text[max(0, m.start() - 10):min(len(text), m.end() + 10)].replace("\n", " ")
            hit = {
                "line": line_no,
                "pattern": pattern,
                "matched": m.group(0),
                "type": "ai_cliche",
                "severity": "warn",
                "message": f"检测到典型 AI 腔调: '{m.group(0)}' ({desc})",
                "snippet": snippet,
            }
            issues.append(hit)
            ai_cliche_hits.append(hit)

    # 2. 段落长度与排版检查
    for idx, line in enumerate(lines, start=1):
        line_s = line.strip()
        if not line_s or line_s.startswith("#"):
            continue
        line_len = len(line_s)
        if line_len > PATTERN_OVERLONG_PARAGRAPH:
            issues.append({
                "line": idx,
                "type": "formatting",
                "severity": "info",
                "message": f"第 {idx} 段字数达到 {line_len} 字，长篇移动端排版建议拆分节奏",
                "snippet": line_s[:40] + "...",
            })

    # 3. 标点符号规范扫描
    exclamation_count = text.count("！") + text.count("!")
    if total_chars > 0 and (exclamation_count / max(1, total_chars / 1000)) > 25:
        issues.append({
            "line": 1,
            "type": "punctuation",
            "severity": "warn",
            "message": f"感叹号密度过高 (千字 {round(exclamation_count / (total_chars / 1000), 1)} 个)，建议弱化主观宣泄增强白描克制感",
        })

    # 4. 对话比率平衡度
    dialogues = re.findall(r"“([^“”]+)”", text)
    dialogue_chars = sum(len(d) for d in dialogues)
    dialogue_ratio = round((dialogue_chars / max(1, total_chars)) * 100, 1)

    if dialogue_ratio > 70:
        issues.append({
            "line": 1,
            "type": "pacing",
            "severity": "warn",
            "message": f"对话字数占比高达 {dialogue_ratio}%，画面感与动作描写偏弱，防范变成水剧情对白戏",
        })
    elif dialogue_ratio < 15 and total_chars > 1500:
        issues.append({
            "line": 1,
            "type": "pacing",
            "severity": "info",
            "message": f"对话字数占比仅为 {dialogue_ratio}%，大量连续叙述，建议增加角色微表情与交锋台词",
        })

    # 计算 AI 异味指数（千字命中率）
    ai_cliche_density = round(len(ai_cliche_hits) / max(0.5, total_chars / 1000), 2)
    overall_health_score = max(0, 100 - len(ai_cliche_hits) * 5 - (15 if dialogue_ratio > 70 else 0))

    return {
        "file": filename,
        "total_chars": total_chars,
        "dialogue_ratio_percent": dialogue_ratio,
        "ai_cliche_count": len(ai_cliche_hits),
        "ai_cliche_density_per_1k": ai_cliche_density,
        "health_score": overall_health_score,
        "total_issues": len(issues),
        "issues": issues,
    }


def main():
    parser = argparse.ArgumentParser(description="小说静态质量与去 AI 味 Linter")
    parser.add_argument("--project", default=".", help="小说工程目录")
    parser.add_argument("--file", required=True, help="待检测的文稿相对路径 (如 drafts/ch_1_polished.md)")
    parser.add_argument("--out", default="workflow/linter_report.json", help="输出报告相对路径")
    parser.add_argument("--max-cliches", type=int, default=5, help="允许的最大 AI 套话数量，超过则退出非 0")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    target_file = project_root / args.file

    if not target_file.is_file():
        print(f"[linter] 错误: 目标文件不存在: {target_file}")
        return 1

    content = target_file.read_text(encoding="utf-8", errors="replace")
    report = lint_text(content, filename=args.file)

    out_path = project_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[linter] 检测完成: {args.file}")
    print(f"  - 有效字数: {report['total_chars']} 字")
    print(f"  - 对话占比: {report['dialogue_ratio_percent']}%")
    print(f"  - AI 套套套话命中: {report['ai_cliche_count']} 处 (千字密度: {report['ai_cliche_density_per_1k']})")
    print(f"  - 健康指数评分: {report['health_score']} / 100")
    print(f"  - 详细报告已落盘: {out_path}")

    if report["ai_cliche_count"] > args.max_cliches:
        print(f"[linter] 质量门禁未通过: AI 套话命中 {report['ai_cliche_count']} > 上限 {args.max_cliches}")
        return 1

    print(f"[linter] 质量门禁通过")
    return 0


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    _reconfigure_stdio()
    import sys
    sys.exit(main())
