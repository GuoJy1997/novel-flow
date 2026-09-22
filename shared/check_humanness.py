# -*- coding: utf-8 -*-
"""朱雀 AI 检测与拟人化特征门禁诊断引擎 (0-Token 纯本地确定性脚本)。

基于对腾讯朱雀检测系统 (Sophomoresty/zhuque) 及开源反朱雀项目 (anti-zhuque, wewrite, Humanizer-zh)
的深度特征建模，纯本地毫秒级计算以下核心指纹：
1. 句长突发性 (Burstiness) 与变异系数 (CV = sigma / mu)，连续 3 句匀称平直度扫描；
2. 状态副词密度 (Adverb Density, 严格把关 <= 2.5 / 100 字)；
3. AI 结构指纹：否定式二元转折 (不是A而是B)、三段式机械排比 (A、B和C)、说明文过渡词；
4. 人类粗粝感与感官生理锚点极性 (Friction & Negative Sensation)；
5. 输出标准化 Markdown 诊断报告 (含行号错题集) 与 SCORES 门禁行，不达标退出码为 1。
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# 高频 AI 状态副词（AI 高度依赖此类副词垫充叙述呼吸感）
AI_STATE_ADVERBS = [
    "缓缓", "微微", "悄然", "蓦然", "暗暗", "下意识", "不由得", "忍不住",
    "径直", "猛地", "赫然", "悄无声息", "不约而同", "隐隐", "静静", "陡然",
    "毅然", "断然", "旋即", "骤然", "俨然", "殊不知", "不由自主", "若隐若现",
    "若有所思", "不自觉", "愤然", "茫然", "赫然"
]

# AI 否定式二元转折句式模式（朱雀强特征）
NEGATION_PATTERNS = [
    (re.compile(r"不是[，,\s]*[^，,。！？]{2,20}[，,\s]*而是"), "二元否定转折 (不是A而是B)"),
    (re.compile(r"不只是[，,\s]*[^，,。！？]{2,20}[，,\s]*更是"), "二元递进否定 (不只是A更是B)"),
    (re.compile(r"不仅是[，,\s]*[^，,。！？]{2,20}[，,\s]*更是"), "二元递进 (不仅是A更是B)"),
    (re.compile(r"与其说[，,\s]*[^，,。！？]{2,20}[，,\s]*不如说"), "比较式二元论 (与其说A不如说B)"),
    (re.compile(r"并非[，,\s]*[^，,。！？]{2,20}[，,\s]*而是"), "庄重二元否定 (并非A而是B)"),
    (re.compile(r"既不[，,\s]*[^，,。！？]{2,20}[，,\s]*也不"), "双重否定并列 (既不A也不B)"),
]

# 三段式机械并列模式 (A、B和C / A、B与C)
RULE_OF_THREE_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{2,8})[、,]([\u4e00-\u9fa5]{2,8})[和与]([\u4e00-\u9fa5]{2,8})"
)

# 典型 AI 腔调、说明文过渡与空洞升华套话
AI_CLICHES = [
    (r"值得注意的是", "论文说明腔过渡词"),
    (r"总而言之|综上所述", "公文总结套词"),
    (r"不可否认的是", "议论说明腔"),
    (r"从某种意义上说|从某种程度上说", "学术式修饰语"),
    (r"毋庸置疑|显而易见", "强加论断词"),
    (r"不难看出", "教导主任式分析"),
    (r"换句话说", "说明文解释腔"),
    (r"与此同时", "机械场景切换词"),
    (r"不得不说", "网络评论式口头禅"),
    (r"仿佛在诉说着", "过度拟人化空洞抒情"),
    (r"无声地诉说", "矫揉造作抒情"),
    (r"时间仿佛在这一刻凝固", "时间凝滞陈词滥调"),
    (r"空气中弥漫着.*?的(气息|味道)", "感官描写模板化"),
    (r"空气仿佛凝固了", "氛围模板化"),
    (r"这无疑是", "绝对化判断词"),
    (r"眼神中闪烁着.*?的(光芒|光彩)", "目光描写模板化"),
    (r"倒吸了一口(凉气|冷气)", "机械惊呼模板"),
    (r"嘴角勾起了一抹.*?(微笑|冷笑|弧度)", "邪魅狂狷式模板句"),
    (r"宛如.*?(一般|一样)", "机械比喻堆砌"),
    (r"然而，?事情并没有想象的那么简单", "机械剧情悬疑转折"),
    (r"殊不知", "上帝视角生硬剧透"),
    (r"这一刻[，,]", "时间停滞模板词"),
    (r"仿佛都在这一刻", "群体感应模板套话"),
]

# 人类写作者粗粝感与生理物理实存特征词（反制 AI 过度礼貌纯净）
RAW_HUMAN_TEXTURE_WORDS = [
    "妈的", "操", "见鬼", "该死", "啐", "龇牙", "冷汗", "黏腻", "腥臭",
    "刺痛", "恶心", "酸痛", "疲惫", "骂娘", "脏兮兮", "冷笑", "扯淡", "屁话",
    "翻白眼", "太阳穴", "唾沫", "破烂", "臭烘烘", "发霉", "粗口", "喘粗气",
    "骨头", "神经紧绷", "血丝", "焦糊", "发麻", "嘶哑", "干呕", "颤抖",
    "寒毛", "鸡皮疙瘩", "抽搐", "浑浊", "腥气", "铁锈味", "指甲盖", "后脊梁"
]


def count_text_words(text: str) -> int:
    """计算中文小说的有效字数（CJK + 英文单词数）。"""
    if not text:
        return 0
    clean = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    clean_lines = [l.lstrip("# \t") for l in clean.splitlines() if l.strip()]
    cleaned = "\n".join(clean_lines)
    cjk = len(re.findall(r"[\u4e00-\u9fa5\u3040-\u30ff\u3400-\u4dbf]", cleaned))
    words = len(re.findall(r"\b[a-zA-Z0-9_-]+\b", cleaned))
    return cjk + words


def extract_clean_sentences(text: str) -> List[Tuple[str, int]]:
    """提取有效正文句子及其对应的物理行号 (从1开始)。

    返回列表 [(sentence_text, line_number), ...]
    """
    clean = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
    lines = clean.splitlines()
    sentences = []

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # 以中文标点分句：。！？!?… 以及连续句末标点
        raw_chunks = re.split(r"([。！？!?…]+)", stripped)
        current = ""
        for part in raw_chunks:
            current += part
            if re.match(r"^[。！？!?…]+$", part):
                s = current.strip()
                if count_text_words(s) > 0:
                    sentences.append((s, line_idx))
                current = ""
        if current.strip() and count_text_words(current.strip()) > 0:
            sentences.append((current.strip(), line_idx))

    return sentences


def calculate_burstiness(sentences: List[Tuple[str, int]]) -> Dict[str, Any]:
    """计算句长突发性指标 (Burstiness) 与变异系数 (CV) 及连续匀速检测。"""
    if not sentences:
        return {
            "mean": 0.0,
            "std": 0.0,
            "cv": 0.0,
            "uniform_triplets": [],
            "cliff_transitions": 0,
            "score": 0.0,
        }

    lengths = [count_text_words(s[0]) for s in sentences]
    n = len(lengths)
    mean_len = sum(lengths) / n
    variance = sum((l - mean_len) ** 2 for l in lengths) / n
    std_dev = math.sqrt(variance)
    cv = (std_dev / mean_len) if mean_len > 0 else 0.0

    # 1. 连续 3 句匀速平直度检测 (AI 典型特征：连续三句长度差距 < 20%)
    uniform_triplets = []
    for i in range(n - 2):
        l1, l2, l3 = lengths[i], lengths[i + 1], lengths[i + 2]
        max_l = max(l1, l2, l3)
        min_l = min(l1, l2, l3)
        # 仅当句子有一定长度（>=8字）且极度接近时预警
        if max_l >= 8 and (max_l - min_l) / max_l < 0.20:
            uniform_triplets.append({
                "index": i + 1,
                "lines": [sentences[i][1], sentences[i + 1][1], sentences[i + 2][1]],
                "lengths": [l1, l2, l3],
                "sample": sentences[i][0][:20] + "..."
            })

    # 2. 断崖式句长交替统计 (人类特征：相邻句子长度比 >= 3.5 或 <= 0.28)
    cliff_transitions = 0
    for i in range(n - 1):
        l_cur, l_next = lengths[i], lengths[i + 1]
        if l_cur > 0 and l_next > 0:
            ratio = max(l_cur, l_next) / min(l_cur, l_next)
            if ratio >= 3.5:
                cliff_transitions += 1

    # 3. 计算 Burstiness 得分 (0-100)
    # CV 基准: 人类优秀网文 >= 0.50，良好 0.40~0.50，AI 常见 < 0.30
    if cv >= 0.55:
        base_score = 96.0
    elif cv >= 0.45:
        base_score = 88.0 + (cv - 0.45) * 80.0
    elif cv >= 0.35:
        base_score = 75.0 + (cv - 0.35) * 130.0
    elif cv >= 0.25:
        base_score = 55.0 + (cv - 0.25) * 200.0
    else:
        base_score = max(20.0, cv * 220.0)

    # 扣除连续匀速病灶罚分：每个扣 4 分，上限 25 分
    penalty = min(25.0, len(uniform_triplets) * 4.0)
    # 奖励断崖句长错落：每个 +1 分，上限 8 分
    bonus = min(8.0, cliff_transitions * 1.0)

    final_burstiness = max(20.0, min(100.0, base_score - penalty + bonus))

    return {
        "mean": round(mean_len, 2),
        "std": round(std_dev, 2),
        "cv": round(cv, 3),
        "uniform_triplets": uniform_triplets,
        "cliff_transitions": cliff_transitions,
        "score": round(final_burstiness, 1),
    }


def calculate_adverb_density(text: str, total_words: int) -> Dict[str, Any]:
    """计算状态副词密度与纯净度得分。"""
    if total_words <= 0:
        return {"count": 0, "density": 0.0, "hits": [], "score": 100.0}

    lines = text.splitlines()
    hits = []
    adverb_counts: Dict[str, int] = {}

    for line_idx, line in enumerate(lines, start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        for adv in AI_STATE_ADVERBS:
            matches = list(re.finditer(re.escape(adv), line))
            for m in matches:
                adverb_counts[adv] = adverb_counts.get(adv, 0) + 1
                snippet = line[max(0, m.start() - 10):min(len(line), m.end() + 10)]
                hits.append({
                    "line": line_idx,
                    "word": adv,
                    "snippet": snippet
                })

    total_hits = len(hits)
    density_per_100 = (total_hits / (total_words / 100.0)) if total_words > 0 else 0.0

    # 得分映射：
    # <= 1.5/百字 -> 96~100
    # 1.5 ~ 2.5/百字 -> 85~95
    # 2.5 ~ 4.0/百字 -> 65~85
    # > 4.0/百字 -> < 60
    if density_per_100 <= 1.5:
        score = 98.0
    elif density_per_100 <= 2.5:
        score = 95.0 - (density_per_100 - 1.5) * 10.0
    elif density_per_100 <= 4.0:
        score = 85.0 - (density_per_100 - 2.5) * 16.0
    else:
        score = max(20.0, 60.0 - (density_per_100 - 4.0) * 15.0)

    return {
        "count": total_hits,
        "density": round(density_per_100, 2),
        "adverb_distribution": sorted(adverb_counts.items(), key=lambda x: x[1], reverse=True),
        "hits": hits,
        "score": round(score, 1),
    }


def check_syntactic_patterns(text: str) -> Dict[str, Any]:
    """检测二元否定句式、三段式排比与典型 AI 陈词滥调。"""
    lines = text.splitlines()
    negation_hits = []
    rule_of_three_hits = []
    cliche_hits = []

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 1. 二元否定
        for pat, name in NEGATION_PATTERNS:
            for m in pat.finditer(line):
                negation_hits.append({
                    "line": line_idx,
                    "type": name,
                    "matched": m.group(0),
                    "snippet": line[max(0, m.start() - 10):min(len(line), m.end() + 10)]
                })

        # 2. 三段式排比
        for m in RULE_OF_THREE_PATTERN.finditer(line):
            rule_of_three_hits.append({
                "line": line_idx,
                "items": [m.group(1), m.group(2), m.group(3)],
                "matched": m.group(0),
                "snippet": line[max(0, m.start() - 10):min(len(line), m.end() + 10)]
            })

        # 3. AI 说明过渡与抒情套话
        for pat_str, desc in AI_CLICHES:
            for m in re.finditer(pat_str, line):
                cliche_hits.append({
                    "line": line_idx,
                    "desc": desc,
                    "matched": m.group(0),
                    "snippet": line[max(0, m.start() - 10):min(len(line), m.end() + 10)]
                })

    # 计分：基础 100 分，二元否定每处扣 10 分，三段式每处扣 6 分，套话每处扣 7 分
    penalty = len(negation_hits) * 10.0 + len(rule_of_three_hits) * 6.0 + len(cliche_hits) * 7.0
    score = max(20.0, 100.0 - penalty)

    return {
        "negation_hits": negation_hits,
        "rule_of_three_hits": rule_of_three_hits,
        "cliche_hits": cliche_hits,
        "total_hits": len(negation_hits) + len(rule_of_three_hits) + len(cliche_hits),
        "score": round(score, 1),
    }


def check_human_texture(text: str, total_words: int) -> Dict[str, Any]:
    """检测粗粝感、负面生理应激与真实人类心理摩擦词汇。"""
    if total_words <= 0:
        return {"hits": [], "count": 0, "score": 50.0}

    lines = text.splitlines()
    hits = []
    for line_idx, line in enumerate(lines, start=1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        for word in RAW_HUMAN_TEXTURE_WORDS:
            if word in line:
                hits.append({"line": line_idx, "word": word})

    count = len(hits)
    # 人类真实网文每千字通常至少含有 3-5 处粗粝/生理应激/负面情绪词汇
    per_1k = (count / (total_words / 1000.0)) if total_words > 0 else 0.0

    if per_1k >= 3.0:
        score = 95.0
    elif per_1k >= 1.5:
        score = 85.0 + (per_1k - 1.5) * 6.6
    elif per_1k >= 0.5:
        score = 70.0 + (per_1k - 0.5) * 15.0
    else:
        score = max(40.0, per_1k * 80.0)

    return {
        "hits": hits,
        "count": count,
        "per_1000_words": round(per_1k, 2),
        "score": round(score, 1)
    }


def evaluate_humanness(text: str, filename: str = "chapter.md") -> Dict[str, Any]:
    """对输入文本执行完整朱雀拟人化检测全景评估。"""
    total_words = count_text_words(text)
    sentences = extract_clean_sentences(text)

    burstiness = calculate_burstiness(sentences)
    adverbs = calculate_adverb_density(text, total_words)
    syntactic = check_syntactic_patterns(text)
    texture = check_human_texture(text, total_words)

    # 综合拟人化得分权重：
    # 句长突发性 35% + 副词控制 25% + 句式纯净度 30% + 粗粝感 10%
    overall = (
        burstiness["score"] * 0.35 +
        adverbs["score"] * 0.25 +
        syntactic["score"] * 0.30 +
        texture["score"] * 0.10
    )
    overall_score = round(overall, 1)

    return {
        "file": filename,
        "total_words": total_words,
        "sentence_count": len(sentences),
        "overall_score": overall_score,
        "burstiness": burstiness,
        "adverb_density": adverbs,
        "syntactic": syntactic,
        "texture": texture,
        "scores": {
            "overall": overall_score,
            "humanness": overall_score,
            "burstiness": burstiness["score"],
            "adverb_control": adverbs["score"],
            "pattern_clean": syntactic["score"],
            "texture": texture["score"],
        }
    }


def generate_markdown_report(result: Dict[str, Any], min_score: float = 80.0) -> str:
    """生成详尽的朱雀 AI 检测与拟人化审计诊断报告。"""
    passed = result["overall_score"] >= min_score
    status_badge = "✅ 合格放行 (Passed)" if passed else "❌ 拦截打回 (Failed - Blocked)"

    b = result["burstiness"]
    adv = result["adverb_density"]
    syn = result["syntactic"]
    tex = result["texture"]

    lines = [
        f"# 朱雀 AI 检测与拟人化特征门禁诊断报告",
        f"",
        f"- **被检文稿**：`{result['file']}`",
        f"- **总有效字数**：{result['total_words']} 字（分句数：{result['sentence_count']}）",
        f"- **门禁判定结果**：**{status_badge}**",
        f"- **综合拟人化得分**：**{result['overall_score']} 分**（合格底线：{min_score} 分）",
        f"",
        f"---",
        f"",
        f"## 一、 四维拟人化统计指标看板",
        f"",
        f"| 检测维度 | 得分 | 核心统计值 | 人类创作基准参考 | 诊断判定 |",
        f"| :--- | :--- | :--- | :--- | :--- |",
        f"| **1. 句长突发性 (Burstiness)** | **{b['score']}** | 均长: {b['mean']}字, 变异系数 CV: {b['cv']} | CV ≥ 0.45, 拒绝连续匀长 | {'✅ 达标' if b['score'] >= 80 else '⚠️ 句长节奏过平'} |",
        f"| **2. 状态副词密度 (Adverb Density)** | **{adv['score']}** | 总数: {adv['count']}个, 密度: {adv['density']}/百字 | 密度 ≤ 2.5/百字 | {'✅ 达标' if adv['score'] >= 80 else '⚠️ 副词严重超载'} |",
        f"| **3. AI 句法套路纯净度 (Pattern Clean)** | **{syn['score']}** | 违规命中: {syn['total_hits']}处 | 0 处二元否定/机械排比 | {'✅ 达标' if syn['score'] >= 80 else '❌ 命中典型AI套路'} |",
        f"| **4. 粗粝感与生理锚点 (Texture)** | **{tex['score']}** | 摩擦词: {tex['count']}处 ({tex['per_1000_words']}/千字) | ≥ 1.5 处/千字 | {'✅ 达标' if tex['score'] >= 75 else '⚠️ 语感过于平滑纯净'} |",
        f"",
        f"---",
        f"",
        f"## 二、 靶向重写诊断错题集 (Actionable Rewrite Directives)",
        f"",
    ]

    has_issues = False

    # 1. 否定句式
    if syn["negation_hits"]:
        has_issues = True
        lines.append("### 1. 🚨 二元否定转折句式（朱雀必杀指纹，必须彻底拆解）")
        for hit in syn["negation_hits"]:
            lines.append(f"- **[第 {hit['line']} 行]** `{hit['type']}`: 『{hit['matched']}』")
            lines.append(f"  - 上下文：`...{hit['snippet']}...`")
            lines.append(f"  - **靶向改写建议**：删除否定前置，直接采用肯定白描或人物即时动作反应。")
        lines.append("")

    # 2. 三段式排比
    if syn["rule_of_three_hits"]:
        has_issues = True
        lines.append("### 2. 🚨 三段式机械并列（必须打碎为单项或不对称结构）")
        for hit in syn["rule_of_three_hits"]:
            lines.append(f"- **[第 {hit['line']} 行]** 命中项: `{'、'.join(hit['items'])}`")
            lines.append(f"  - 上下文：`...{hit['snippet']}...`")
            lines.append(f"  - **靶向改写建议**：保留最核心的一个感官意象，其余两个删去或改换为动词动作。")
        lines.append("")

    # 3. 连续 3 句匀速平直
    if b["uniform_triplets"]:
        has_issues = True
        lines.append("### 3. ⚠️ 连续三句匀速平直病灶（节奏单一，极易被识别为 AI）")
        for hit in b["uniform_triplets"]:
            lines.append(f"- **[第 {hit['lines'][0]}~{hit['lines'][2]} 行]** 连续句长: `{hit['lengths']}` 字（差异 < 20%）")
            lines.append(f"  - 句首线索：`{hit['sample']}`")
            lines.append(f"  - **靶向改写建议**：执行断崖切割！将其中一句压缩为 2~5 字短促动作断句，或将另一句合并为多重定语长句。")
        lines.append("")

    # 4. 副词聚集预警
    if adv["hits"] and adv["density"] > 2.2:
        has_issues = True
        lines.append("### 4. ⚠️ 高频状态副词聚集（AI 垫词典型习惯）")
        top_advs = ", ".join(f"{w}({c}次)" for w, c in adv["adverb_distribution"][:6])
        lines.append(f"- **高频副词分布**：{top_advs}")
        for hit in adv["hits"][:8]:
            lines.append(f"- **[第 {hit['line']} 行]** 垫词: `{hit['word']}` -> `...{hit['snippet']}...`")
        if len(adv["hits"]) > 8:
            lines.append(f"- *(其余 {len(adv['hits']) - 8} 处副词略，详见全量扫描)*")
        lines.append(f"- **靶向改写建议**：坚决剔除“缓缓/微微/悄然”，将副词转化为具体物理位移动作或直接省略。")
        lines.append("")

    # 5. 说明文过渡与陈词滥调
    if syn["cliche_hits"]:
        has_issues = True
        lines.append("### 5. ⚠️ 说明文过渡与网文模板陈词滥调")
        for hit in syn["cliche_hits"]:
            lines.append(f"- **[第 {hit['line']} 行]** `{hit['desc']}`: 『{hit['matched']}』")
            lines.append(f"  - 上下文：`...{hit['snippet']}...`")
        lines.append(f"- **靶向改写建议**：删除说明腔过渡，直接切入场景交互与限制视角心理反应。")
        lines.append("")

    if not has_issues:
        lines.append("🎉 **全篇未检测到明显 AI 指纹！**")
        lines.append("- 句长起伏错落有致，节奏呼吸感良好；")
        lines.append("- 彻底规避了二元否定与三段式排比等机械套路；")
        lines.append("- 状态副词克制，具备扎实的人类创作质感。")
        lines.append("")

    lines.append("---")
    lines.append("")
    # 结构化评分标记行供 pipeline.py 自动识别与断言强校验
    lines.append(f"SCORES: {json.dumps(result['scores'], ensure_ascii=False)}")
    lines.append("")

    return "\n".join(lines)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="朱雀 AI 检测与拟人化特征门禁诊断引擎")
    parser.add_argument("--input", required=True, help="待检测文稿路径 (如 工作区/第01章/03_去AI味润色稿.md)")
    parser.add_argument("--output", help="诊断报告产出路径 (如 工作区/第01章/03_3_朱雀检测报告.md)")
    parser.add_argument("--min-score", type=float, default=80.0, help="合格最低总分门槛 (默认 80.0)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出到控制台")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"Error: 待检测文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    try:
        text = in_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error: 无法读取输入文件 {in_path}: {e}", file=sys.stderr)
        sys.exit(1)

    result = evaluate_humanness(text, filename=in_path.name)
    report_md = generate_markdown_report(result, min_score=args.min_score)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report_md, encoding="utf-8")
        print(f"[check_zhuque] 诊断报告已生成: {out_path}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== 朱雀检测评估: {result['file']} ===")
        print(f"有效字数: {result['total_words']} | 分句数: {result['sentence_count']}")
        print(f"综合拟人化得分: {result['overall_score']} 分 (门槛: {args.min_score})")
        print(f"  - 句长突发性 (Burstiness): {result['burstiness']['score']} 分 (CV={result['burstiness']['cv']})")
        print(f"  - 副词控制率 (Adverb): {result['adverb_density']['score']} 分 (密度={result['adverb_density']['density']}/百字)")
        print(f"  - 句法纯净度 (Pattern): {result['syntactic']['score']} 分 (命中={result['syntactic']['total_hits']}处)")
        print(f"  - 粗粝感特征 (Texture): {result['texture']['score']} 分")
        print(f"SCORES: {json.dumps(result['scores'], ensure_ascii=False)}")

    passed = result["overall_score"] >= args.min_score
    if not passed:
        print(f"❌ 未达到门禁要求 ({result['overall_score']} < {args.min_score})，触发阻断打回！", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"✅ 拟人化门禁通过 ({result['overall_score']} >= {args.min_score})，允许流转下游！")
        sys.exit(0)


if __name__ == "__main__":
    main()
