"""_measured_summary(1レスポンス実測値の整形)の単体テスト。

裏トークンは表の部分集合ではなく追加課金される、という実測事実を固定する。
"""
import json
from pathlib import Path

from app.main import _measured_summary
from app.usage.assemble import parse_usage

FIXTURES = Path(__file__).parent / "fixtures"


def _record_from_usage(usage: dict) -> dict:
    f = parse_usage(usage)
    return {"ttft_s": 1.0, "elapsed_s": 2.0, "error": None, **f}


def test_orchestration_is_additive_not_subset_real_ultra_data():
    usage = json.loads((FIXTURES / "fugu_ultra_orchestration_usage.json").read_text())
    m = _measured_summary(_record_from_usage(usage))
    # 表 = 180 + 800 = 980
    assert m["visible_tokens"] == 980
    # 裏 = 20399 + 25988 = 46387
    assert m["orchestration_tokens"] == 46387
    # 課金総計 = 表 + 裏 = 47367 (裏を表に足す。部分集合ではない)
    assert m["total_tokens"] == 47367
    # 裏比率 = 46387 / 47367 ≒ 0.979。決して 1.0 を超えない。
    assert 0.97 <= m["orchestration_ratio"] <= 0.98


def test_zero_orchestration_is_zero_ratio_not_unknown():
    usage = {
        "prompt_tokens": 99, "completion_tokens": 18, "total_tokens": 117,
        "prompt_tokens_details": {"cached_tokens": 0, "orchestration_input_tokens": 0},
        "completion_tokens_details": {"orchestration_output_tokens": 0},
    }
    m = _measured_summary(_record_from_usage(usage))
    assert m["orchestration_tokens"] == 0
    assert m["orchestration_ratio"] == 0.0   # 0 は 0(不明ではない)


def test_unknown_orchestration_is_none_ratio():
    # orchestration が欠損(不明)なら比率は None
    usage = {"prompt_tokens": 10, "completion_tokens": 5}
    m = _measured_summary(_record_from_usage(usage))
    assert m["orchestration_tokens"] is None
    assert m["orchestration_ratio"] is None
    assert m["total_tokens"] == 15   # 裏不明なら表のみ


def test_failed_record_has_no_ratio():
    m = _measured_summary({
        "ttft_s": None, "elapsed_s": 0.5, "error": "boom",
        "input_tokens": None, "output_tokens": None,
        "cached_tokens": None,
        "orchestration_input_tokens": None, "orchestration_output_tokens": None,
    })
    assert m["total_tokens"] is None
    assert m["orchestration_ratio"] is None
    assert m["error"] == "boom"
