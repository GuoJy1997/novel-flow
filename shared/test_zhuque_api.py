# -*- coding: utf-8 -*-
"""朱雀官方 API 终审门禁脚本测试 (mock HTTP, 不打真实 API)。"""
import io
import json
import urllib.error
from pathlib import Path

import pytest

import check_zhuque_api as zq
from pipeline import parse_scores_from_text


GOOD_PAYLOAD = {
    "softmax_confidence": 0.15,
    "labels_ratio": {"0": 0.90, "1": 0.05, "2": 0.05},
    "makers_models_usage": {"total_tokens": 3120},
}


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def test_parse_labels_ratio_str_and_int_keys():
    assert zq._parse_labels_ratio({"0": 0.9, "1": 0.05, "2": 0.05}) == {
        "human": 90.0, "ai": 5.0, "suspect": 5.0}
    assert zq._parse_labels_ratio({0: 1.0, 1: 0.0, 2: 0.0})["human"] == 100.0
    # 未知标签忽略
    assert zq._parse_labels_ratio({"9": 0.5, "0": 0.5}) == {"human": 50.0}


def test_parse_labels_ratio_percentage_defense():
    # 值已是百分数口径 (>1.5) 时不再乘 100
    assert zq._parse_labels_ratio({"0": 88.0, "1": 9.0, "2": 3.0}) == {
        "human": 88.0, "ai": 9.0, "suspect": 3.0}


def test_parse_labels_ratio_invalid():
    assert zq._parse_labels_ratio(None) is None
    assert zq._parse_labels_ratio({"0": "abc"}) is None
    assert zq._parse_labels_ratio({}) is None


def test_parse_zhuque_response_ok():
    r = zq.parse_zhuque_response(GOOD_PAYLOAD)
    assert r["overall"] == 85.0
    assert r["ai_confidence"] == 15.0
    assert r["labels"]["human"] == 90.0
    assert r["total_tokens"] == 3120
    assert r["scores"]["overall"] == 85.0
    assert r["scores"]["zhuque_ai_confidence"] == 15.0


def test_parse_zhuque_response_without_labels():
    r = zq.parse_zhuque_response({"softmax_confidence": 0.42})
    assert r["overall"] == 58.0
    assert r["labels"] is None
    assert "zhuque_human_ratio" not in r["scores"]


def test_parse_zhuque_response_missing_confidence():
    with pytest.raises(zq.ZhuqueApiError):
        zq.parse_zhuque_response({"foo": 1})
    with pytest.raises(zq.ZhuqueApiError):
        zq.parse_zhuque_response("not a dict")


# ---------------------------------------------------------------------------
# HTTP 重试逻辑
# ---------------------------------------------------------------------------

def _http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://test", code, "err",
                                  hdrs=None, fp=io.BytesIO(body))


def test_call_retries_on_5xx(monkeypatch):
    calls = []

    def fake_http(url, key, body, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise _http_error(502)
        return dict(GOOD_PAYLOAD)

    monkeypatch.setattr(zq, "_http_request", fake_http)
    raw = zq.call_zhuque_api("测试文本", "http://test", "k", retries=1)
    assert raw == dict(GOOD_PAYLOAD)  # call 层返回原始 payload, 解析在 parse 层
    assert zq.parse_zhuque_response(raw)["overall"] == 85.0
    assert len(calls) == 2


def test_call_no_retry_on_4xx(monkeypatch):
    calls = []

    def fake_http(url, key, body, timeout):
        calls.append(url)
        raise _http_error(401)

    monkeypatch.setattr(zq, "_http_request", fake_http)
    with pytest.raises(zq.ZhuqueApiError):
        zq.call_zhuque_api("测试文本", "http://test", "k", retries=1)
    assert len(calls) == 1  # 4xx 不重试


def test_call_retries_exhausted(monkeypatch):
    def fake_http(url, key, body, timeout):
        raise zq.ZhuqueApiError("网络或响应错误: boom")

    monkeypatch.setattr(zq, "_http_request", fake_http)
    with pytest.raises(zq.ZhuqueApiError):
        zq.call_zhuque_api("测试文本", "http://test", "k", retries=1)


# ---------------------------------------------------------------------------
# main 门禁流程 (临时文件 + mock HTTP)
# ---------------------------------------------------------------------------

def _make_input(tmp_path: Path) -> Path:
    p = tmp_path / "03_去AI味润色稿.md"
    p.write_text("# 第一章：测试\n\n冷凝水顺着气压面罩滑下，在边缘凝成碎冰。" * 5,
                 encoding="utf-8")
    return p


def test_main_gate_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHUQUE_API_KEY", "test-key-123456")
    monkeypatch.setattr(zq, "_http_request",
                        lambda url, key, body, timeout: dict(GOOD_PAYLOAD))
    args_input = _make_input(tmp_path)
    out_path = tmp_path / "03_4_朱雀API终审报告.md"
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(args_input),
        "--output", str(out_path)])
    assert zq.main() == 0
    assert "✅" in out_path.read_text(encoding="utf-8")


def test_main_gate_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHUQUE_API_KEY", "test-key-123456")
    monkeypatch.setattr(zq, "_http_request",
                        lambda url, key, body, timeout:
                        {"softmax_confidence": 0.72,
                         "labels_ratio": {"0": 0.2, "1": 0.7, "2": 0.1}})
    args_input = _make_input(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(args_input),
        "--output", str(tmp_path / "out.md"), "--min-score", "60"])
    assert zq.main() == 1
    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "❌" in text
    scores = parse_scores_from_text(text)
    assert scores["overall"] == 28.0


def test_main_gate_pass_report_parseable(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHUQUE_API_KEY", "test-key-123456")
    monkeypatch.setattr(zq, "_http_request",
                        lambda url, key, body, timeout: dict(GOOD_PAYLOAD))
    args_input = _make_input(tmp_path)
    out_path = tmp_path / "03_4_朱雀API终审报告.md"
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(args_input),
        "--output", str(out_path)])
    assert zq.main() == 0
    scores = parse_scores_from_text(out_path.read_text(encoding="utf-8"))
    # pipeline.evaluate_asserts 将按 score_field=overall 用此分数卡门禁
    assert scores["overall"] == 85.0
    assert scores["zhuque_ai_confidence"] == 15.0


def test_main_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ZHUQUE_API_KEY", raising=False)
    args_input = _make_input(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(args_input),
        "--output", str(tmp_path / "out.md")])
    assert zq.main() == 2  # 配置缺失 = 基础设施错误, 区别于门禁拦截
    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "ZHUQUE_API_KEY" in text


def test_main_http_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHUQUE_API_KEY", "test-key-123456")

    def fake_http(url, key, body, timeout):
        raise zq.ZhuqueApiError("HTTP 500 oops")

    monkeypatch.setattr(zq, "_http_request", fake_http)
    args_input = _make_input(tmp_path)
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(args_input),
        "--output", str(tmp_path / "out.md")])
    assert zq.main() == 2
    text = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "未完成" in text


def test_main_input_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZHUQUE_API_KEY", "test-key-123456")
    monkeypatch.setattr("sys.argv", [
        "check_zhuque_api.py", "--input", str(tmp_path / "不存在.md")])
    assert zq.main() == 1
