"""record.py の単体テスト。ネットワーク不要。

ここが壊れると日曜の判断を静かに誤らせる。最優先でテストする箇所:
裏率計算・null/0 区別・未知フィールド検知。
"""

import json
import math
from pathlib import Path

import pytest

from dashboard.core.record import RecordError, parse_record

# 実データサンプル(single source。コピーせず参照する)。
SAMPLE_PATH = Path(__file__).resolve().parents[2] / "sample-data" / "usage.sample.jsonl"


def _load_sample() -> list[dict]:
    lines = SAMPLE_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


def test_sample_ultra_ratio_matches_measured_78_percent():
    """fugu-ultra サンプル: 裏率 ≒ 78%(sample-data/README の対照表の正)。"""
    ultra = parse_record(_load_sample()[0])
    assert ultra.visible_tokens == 297 + 6989
    assert ultra.orchestration_tokens == 16328 + 9061
    # 課金総計 = 表 + 裏(裏は追加課金。表の部分集合ではない)。
    assert ultra.billed_tokens == 297 + 6989 + 16328 + 9061
    assert ultra.orchestration_ratio is not None
    assert math.isclose(ultra.orchestration_ratio, 0.78, abs_tol=0.01)


def test_sample_light_request_has_zero_overhead():
    """fugu(軽い直接回答)サンプル: 裏 0、裏率 0%。None ではなく 0 であること。"""
    light = parse_record(_load_sample()[1])
    assert light.orchestration_input_tokens == 0
    assert light.orchestration_output_tokens == 0
    assert light.orchestration_known is True          # 取得できている(不明ではない)
    assert light.orchestration_ratio == 0.0


def test_billed_denominator_uses_total_not_visible_only():
    """裏率の分母を表のみにすると 100% 超になる誤り。総計を使えているか。"""
    ultra = parse_record(_load_sample()[0])
    # 裏(25389) / 表のみ(7286) は 3.48 > 1。これになっていないこと。
    assert ultra.orchestration_ratio < 1.0


def test_null_orchestration_is_unknown_not_zero():
    """裏トークンが null のレコードは「不明」。0 と混同しない。"""
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,
        "input_tokens": 10, "output_tokens": 20,
        "orchestration_input_tokens": None, "orchestration_output_tokens": None,
        "raw_usage": {}, "error": None,
    }
    r = parse_record(obj)
    assert r.orchestration_known is False
    assert r.orchestration_tokens is None
    assert r.billed_tokens is None          # 裏不明なら総計も不明(0 埋めしない)
    assert r.orchestration_ratio is None    # 母数から除外できるように None


def test_zero_orchestration_is_counted():
    """裏トークンが 0 のレコードは集計に含める(既知の 0)。"""
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,
        "input_tokens": 10, "output_tokens": 20,
        "orchestration_input_tokens": 0, "orchestration_output_tokens": 0,
        "raw_usage": {}, "error": None,
    }
    r = parse_record(obj)
    assert r.orchestration_known is True
    assert r.orchestration_tokens == 0
    assert r.billed_tokens == 30
    assert r.orchestration_ratio == 0.0


def test_partial_orchestration_is_unknown():
    """片方だけ取れて片方 None なら、全体として「不明」に倒す。"""
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,
        "input_tokens": 10, "output_tokens": 20,
        "orchestration_input_tokens": 5, "orchestration_output_tokens": None,
        "raw_usage": {}, "error": None,
    }
    r = parse_record(obj)
    assert r.orchestration_known is False
    assert r.orchestration_ratio is None


def test_reasoning_tokens_pulled_from_raw_usage():
    """reasoning_tokens は raw_usage から参考値として拾う(スキーマ未定義)。"""
    ultra = parse_record(_load_sample()[0])
    assert ultra.reasoning_tokens == 4920


def test_unknown_raw_key_detection():
    """raw_usage に既知セット外のキーが現れたら検知する(プロバイダ仕様変更の兆候)。"""
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,
        "input_tokens": 10, "output_tokens": 20,
        "raw_usage": {
            "prompt_tokens": 10,
            "surprise_top_level": 1,
            "completion_tokens_details": {"reasoning_tokens": 3, "brand_new": 7},
        },
        "error": None,
    }
    r = parse_record(obj)
    assert "surprise_top_level" in r.unknown_raw_keys
    assert "completion_tokens_details.brand_new" in r.unknown_raw_keys
    # 既知キー(reasoning_tokens)は未知扱いしない。
    assert "completion_tokens_details.reasoning_tokens" not in r.unknown_raw_keys


def test_known_shape_has_no_unknown_keys():
    """実サンプル(既知形状)は未知キー無し。"""
    for obj in _load_sample():
        r = parse_record(obj)
        assert r.unknown_raw_keys == ()


def test_missing_required_field_raises():
    with pytest.raises(RecordError):
        parse_record({"id": "x", "provider": "fugu"})


def test_bool_is_not_a_number():
    """True/False を数値として受け入れない(型汚染を弾く)。"""
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,
        "input_tokens": True, "output_tokens": 20, "raw_usage": {}, "error": None,
    }
    with pytest.raises(RecordError):
        parse_record(obj)


def test_error_record_is_not_success():
    obj = {
        "id": "x", "timestamp": "2026-07-24T00:00:00+00:00", "provider": "fugu",
        "model": "fugu", "conversation_id": "c", "ttft_s": 0.0, "elapsed_s": 1.0,
        "input_tokens": 0, "output_tokens": 0, "raw_usage": {},
        "error": "invalid_request_error: bad model",
    }
    r = parse_record(obj)
    assert r.is_success is False
