# -*- coding: utf-8 -*-
"""朱雀官方 API 终审门禁脚本 (腾讯云 EdgeOne "朱雀 AIGC 检测模型" zhuque-text)。

与本地代理门禁 check_humanness.py 组成两级检测：
  第一级 check_zhuque   : 0-Token 纯本地统计指纹粗筛 (毫秒级, 挡明显不过关的稿子)；
  第二级 zhuque_api_final: 将润色稿提交腾讯朱雀官方检测模型终审 (真判别器, 成本约 0.12 元/3000字)。

API 契约 (依据 2026-09 EdgeOne Makers 官方文档快照，字段语义以官方最新文档为准):
  - POST {ZHUQUE_API_URL}
      默认 https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify
      (自建网关时用环境变量 ZHUQUE_API_URL 覆盖完整端点)
  - Headers : Authorization: Bearer <ZHUQUE_API_KEY>
              Content-Type: application/json
  - Body    : {"text": str, "is_merge": bool}
              is_merge=false 时逐段独立输出置信度 (本脚本固定 true, 输出整篇单一结论)
  - Response: {"softmax_confidence": float, "labels_ratio": {...},
               "makers_models_usage": {...}(可能存在)}
      - softmax_confidence: 0~1, 越大越可能命中 AI 风险内容;
      - labels_ratio     : 键 "0"=人工, "1"=AI, "2"=疑似, 值为占比;
      - makers_models_usage: 调用用量计费信息 (存在时写入报告用于成本追踪)。

输出: Markdown 诊断报告 (与 03_3 本地报告同风格), 末尾附
      SCORES: {"overall": <人类得分0-100>, ...} 供 pipeline.py 的
      assert (min_score/score_field) 断言机制强校验。

退出码: 0 = 门禁通过; 1 = 检测拦截 (AI 风险超标, 文稿质量问题);
        2 = 配置缺失 / 网络 / API 错误 (基础设施问题, 非文稿问题)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_API_URL = "https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify"
API_KEY_ENV = "ZHUQUE_API_KEY"
API_URL_ENV = "ZHUQUE_API_URL"


def _load_api_key() -> str:
    """读取朱雀 API Key：先看当前进程环境变量，Windows 下再回退用户级注册表。

    回退注册表 (HKCU\\Environment) 的意义：用户 `setx ZHUQUE_API_KEY ...` 配置后，
    已经在运行的 studio 服务进程无需重启即可在本节点执行时读到新 Key，
    消除"配了 Key 却要重启整个工作台"的断点。
    """
    key = os.environ.get(API_KEY_ENV, "").strip()
    if key:
        return key
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as reg:
                value, _ = winreg.QueryValueEx(reg, API_KEY_ENV)
            return str(value).strip()
        except (OSError, ImportError):
            pass
    return ""

# labels_ratio 文档语义: 0=人工, 1=AI, 2=疑似
LABEL_KEY_MAP = {"0": "human", "1": "ai", "2": "suspect"}

# 朱雀网页版要求 >= 200 字; API 侧未见明确下限, 低于此值仅告警不阻断
MIN_TEXT_WARN = 200


class ZhuqueApiError(RuntimeError):
    """朱雀 API 调用失败 (网络 / HTTP / 响应非法)。对应退出码 2。"""


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def _parse_labels_ratio(raw: Any) -> Optional[Dict[str, float]]:
    """把 labels_ratio 容错解析为 {human/ai/suspect: 0~100 占比}。

    官方文档定义值为占比 (0~1)。若检测到取值明显超过 1 (如 50), 视为
    已是百分数口径, 不再乘 100。无法解析时返回 None, 不阻断主结论
    (主结论由 softmax_confidence 决定)。
    """
    if not isinstance(raw, dict):
        return None
    out: Dict[str, float] = {}
    for key, value in raw.items():
        label = LABEL_KEY_MAP.get(str(key).strip())
        if label is None or not isinstance(value, (int, float)):
            continue
        out[label] = float(value)
    if not out:
        return None
    if max(out.values()) > 1.5:
        return {k: round(v, 1) for k, v in out.items()}
    return {k: round(v * 100, 1) for k, v in out.items()}


def parse_zhuque_response(payload: Any) -> Dict[str, Any]:
    """把朱雀 API 响应解析为统一结果结构。

    核心换算: softmax_confidence 越大越 "AI", 故
      overall (人类得分) = 100 - softmax_confidence * 100
    与本项目其他门禁节点 "分数越高越好" 的方向保持一致。
    """
    if not isinstance(payload, dict):
        raise ZhuqueApiError(f"响应不是 JSON 对象: {type(payload).__name__}")

    conf = payload.get("softmax_confidence")
    if conf is None or not isinstance(conf, (int, float)):
        raise ZhuqueApiError(f"响应缺少合法的 softmax_confidence 字段: {payload!r}")

    ai_confidence = min(100.0, max(0.0, float(conf) * 100.0))
    overall = round(100.0 - ai_confidence, 1)

    labels = _parse_labels_ratio(payload.get("labels_ratio"))
    usage = payload.get("makers_models_usage") if isinstance(payload.get("makers_models_usage"), dict) else None
    raw_tokens = usage.get("total_tokens") if usage else None

    scores: Dict[str, Any] = {
        "overall": overall,
        "zhuque_ai_confidence": round(ai_confidence, 1),
    }
    if labels:
        scores["zhuque_human_ratio"] = labels.get("human")
        scores["zhuque_ai_ratio"] = labels.get("ai")
        scores["zhuque_suspect_ratio"] = labels.get("suspect")

    return {
        "ai_confidence": round(ai_confidence, 1),
        "overall": overall,
        "labels": labels,
        "usage": usage,
        "total_tokens": raw_tokens,
        "scores": scores,
        "raw": payload,
    }


# ---------------------------------------------------------------------------
# HTTP 调用 (stdlib, 无第三方依赖)
# ---------------------------------------------------------------------------

def _http_request(api_url: str, api_key: str, body: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    """单次 HTTP POST, 返回解析后的 JSON。网络/HTTP 错误抛异常由上层重试。"""
    req = urllib.request.Request(
        api_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset, errors="replace"))


def call_zhuque_api(text: str, api_url: str, api_key: str,
                    timeout: float = 60.0, retries: int = 1) -> Dict[str, Any]:
    """调用朱雀官方检测接口, 瞬时故障 (网络/5xx) 自动重试一次。"""
    body = {"text": text, "is_merge": True}
    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _http_request(api_url, api_key, body, timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            last_err = ZhuqueApiError(f"HTTP {e.code} {e.reason} {detail}".strip())
            if e.code < 500:
                raise last_err  # 4xx (鉴权/参数) 重试无意义, 直接失败
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = ZhuqueApiError(f"网络或响应错误: {e}")
        if attempt < retries:
            time.sleep(2)
    raise last_err or ZhuqueApiError("未知 API 错误")


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def generate_markdown_report(result: Dict[str, Any], min_score: float, *,
                             filename: str, total_words: int,
                             api_url: str, api_key_masked: str,
                             error_note: Optional[str] = None) -> str:
    """生成朱雀官方 API 终审报告 (error_note 非空时为错误诊断报告, 无门禁判定)。"""
    lines = ["# 朱雀官方 API 终审检测报告", ""]

    if error_note:
        lines += [
            f"- **被检文稿**：`{filename}`",
            f"- **终审状态**：**⚠️ 未完成 (API 调用失败, 不构成质检结论)**",
            f"- **失败原因**：{error_note}",
            "",
            "本次失败属于**基础设施问题**（配置缺失 / 网络 / API 异常），而非文稿质量问题。",
            "请检查环境变量 `ZHUQUE_API_KEY`（及可选 `ZHUQUE_API_URL`）后重跑本节点。",
            "",
            "---",
            "",
            "SCORES: {}",
            "",
        ]
        return "\n".join(lines)

    passed = result["overall"] >= min_score
    badge = "✅ 人工特征达标放行 (Passed)" if passed else "❌ AI 风险超标拦截 (Blocked)"
    labels = result.get("labels")

    lines += [
        f"- **被检文稿**：`{filename}`",
        f"- **总有效字数**：{total_words} 字",
        f"- **门禁判定结果**：**{badge}**",
        f"- **朱雀 AI 风险置信度**：**{result['ai_confidence']}%**（softmax_confidence，越大越像 AI）",
        f"- **综合人类得分**：**{result['overall']} 分**（合格底线：{min_score} 分 = AI 风险 ≤ {round(100 - min_score, 1)}%）",
        "",
        "---",
        "",
        "## 一、 官方模型检测指标看板",
        "",
        "| 检测指标 | 数值 | 说明 |",
        "| :--- | :--- | :--- |",
        f"| softmax_confidence | {result['ai_confidence']}% | 官方模型输出的 AI 风险置信度，越大越可能命中 AI 生成 |",
    ]
    if labels:
        lines += [
            f"| 人工占比 (label=0) | {labels.get('human', '—')}% | 分段判定为人工创作的比例 |",
            f"| AI 占比 (label=1) | {labels.get('ai', '—')}% | 分段判定为 AI 生成的比例 |",
            f"| 疑似占比 (label=2) | {labels.get('suspect', '—')}% | 分段判定为疑似 AI 的比例 |",
        ]
    else:
        lines += ["| labels_ratio | 未返回 | 本次响应未携带分段占比，以 softmax_confidence 为准 |"]

    usage = result.get("usage")
    if usage:
        lines += [
            "",
            "## 二、 本次调用用量",
            "",
            "```json",
            json.dumps(usage, ensure_ascii=False, indent=2),
            "```",
        ]

    lines += [
        "",
        "---",
        "",
        "## 三、 处置建议",
        "",
    ]
    if passed:
        lines += [
            "官方检测模型判定本稿人工特征达标，允许流转下游进入人设审查与盲审质检。",
        ]
    else:
        lines += [
            f"官方模型判定 AI 风险超标（人类得分 {result['overall']} < 门槛 {min_score}），拦截打回。建议：",
            "",
            "1. 回炉 `deai_polish` 节点定向重写，重点参考 `03_3_朱雀检测报告.md` 中的【靶向重写错题集】；",
            "2. 本地代理门禁（句长突发性/副词/句式套路）已通过但官方仍拦截时，优先排查：段落间语义过于连贯均质、用词分布过于平滑、情节推进缺乏跳跃；",
            "3. 门槛值可在 graph.yaml 中调整（`--min-score`，默认 60 = AI 风险 ≤ 40%），建议先跑 3~5 章校准与本地检测的相关性再定阈值。",
        ]

    lines += [
        "",
        "---",
        "",
        "## 附、 原始响应（排障用）",
        "",
        "```json",
        json.dumps(result.get("raw"), ensure_ascii=False, indent=2)[:2000],
        "```",
        "",
        f"- **检测端点**：`{api_url}`",
        f"- **鉴权凭据**：`{api_key_masked}`",
        f"- **说明**：本报告字段语义依据 2026-09 EdgeOne 官方文档快照；`is_merge=true`（整篇单一结论），逐段定位可后续以 `is_merge=false` 增强。",
        "",
        # 结构化评分标记行供 pipeline.py 自动识别与断言强校验
        f"SCORES: {json.dumps(result['scores'], ensure_ascii=False)}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="朱雀官方 API 终审门禁 (腾讯云 EdgeOne zhuque-text)")
    parser.add_argument("--input", required=True,
                        help="待检测文稿路径 (如 工作区/第01章/03_去AI味润色稿.md)")
    parser.add_argument("--output",
                        help="诊断报告产出路径 (如 工作区/第01章/03_4_朱雀API终审报告.md)")
    parser.add_argument("--min-score", type=float, default=60.0,
                        help="人类得分门槛, 0-100 (默认 60, 即 AI 风险置信度 ≤ 40%%)")
    parser.add_argument("--api-url", default=os.environ.get(API_URL_ENV, DEFAULT_API_URL),
                        help=f"检测端点 URL (默认读环境变量 {API_URL_ENV}, 再退回官方默认网关)")
    parser.add_argument("--timeout", type=float, default=60.0,
                        help="单次请求超时秒数 (默认 60)")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出到控制台")
    args = parser.parse_args()

    def write_report(content: str) -> None:
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
            print(f"[zhuque_api_final] 终审报告已生成: {out_path}")

    in_path = Path(args.input)
    if not in_path.is_file():
        print(f"Error: 待检测文件不存在: {in_path}", file=sys.stderr)
        return 1

    try:
        text = in_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error: 无法读取输入文件 {in_path}: {e}", file=sys.stderr)
        return 1

    api_key = _load_api_key()
    api_key_masked = (api_key[:6] + "***") if len(api_key) > 6 else ("(已配置)" if api_key else "(未配置)")
    filename = in_path.name
    total_words = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")  # 粗略 CJK 字数, 仅供报告展示

    # 配置缺失: 基础设施问题, 写报告并退出码 2 (区别于门禁拦截的 1)
    if not api_key:
        write_report(generate_markdown_report({}, args.min_score, filename=filename,
                                              total_words=total_words, api_url=args.api_url,
                                              api_key_masked=api_key_masked,
                                              error_note=f"环境变量 {API_KEY_ENV} 未配置"))
        print(f"Error: 环境变量 {API_KEY_ENV} 未配置, 无法调用朱雀官方 API。"
              f"请在 EdgeOne 控制台创建网关获取 API Key 后设置环境变量。", file=sys.stderr)
        return 2

    if len(text.strip()) < MIN_TEXT_WARN:
        print(f"[zhuque_api_final] 警告: 文稿不足 {MIN_TEXT_WARN} 字, "
              f"官方模型置信度可能不可靠 (当前仅 {len(text.strip())} 字符)。", file=sys.stderr)

    try:
        payload = call_zhuque_api(text, args.api_url, api_key, timeout=args.timeout)
    except ZhuqueApiError as e:
        write_report(generate_markdown_report({}, args.min_score, filename=filename,
                                              total_words=total_words, api_url=args.api_url,
                                              api_key_masked=api_key_masked,
                                              error_note=str(e)))
        print(f"Error: 朱雀 API 调用失败: {e}", file=sys.stderr)
        return 2

    result = parse_zhuque_response(payload)
    report_md = generate_markdown_report(result, args.min_score, filename=filename,
                                         total_words=total_words,
                                         api_url=args.api_url, api_key_masked=api_key_masked)
    write_report(report_md)

    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "raw"},
                         ensure_ascii=False, indent=2))
    else:
        print(f"=== 朱雀官方 API 终审: {filename} ===")
        print(f"AI 风险置信度: {result['ai_confidence']}% | 综合人类得分: {result['overall']} 分 (门槛: {args.min_score})")
        if result.get("labels"):
            lb = result["labels"]
            print(f"  - 分段占比: 人工 {lb.get('human', '—')}% / AI {lb.get('ai', '—')}% / 疑似 {lb.get('suspect', '—')}%")
        if result.get("total_tokens") is not None:
            print(f"  - 本次用量: {result['total_tokens']} tokens")
        print(f"SCORES: {json.dumps(result['scores'], ensure_ascii=False)}")

    if result["overall"] < args.min_score:
        print(f"❌ 官方终审未通过 ({result['overall']} < {args.min_score})，拦截打回！", file=sys.stderr)
        return 1
    print(f"✅ 官方终审通过 ({result['overall']} >= {args.min_score})，允许流转下游！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
