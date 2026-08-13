"""metrics.py の単体テスト。集計・裏率・レイテンシ分離・外挿の幅と警告。"""

import math
from pathlib import Path

from dashboard.core.loader import load_file
from dashboard.core.metrics import (
    analyze_latency,
    analyze_overhead,
    collect_unknown_raw_keys,
    observed_days,
    project_monthly,
    summarize_tokens,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ANOMALIES = FIXTURES / "anomalies.jsonl"


def _records():
    return load_file(str(ANOMALIES)).records


def test_summary_counts_success_and_error():
    summary = summarize_tokens(_records())
    assert summary.request_count == 4
    assert summary.success_count == 3
    assert summary.error_count == 1


def test_summary_tracks_unknown_orchestration_separately():
    """裏不明のレコードは合計に足さず、不明件数として数える(null/0 区別)。"""
    summary = summarize_tokens(_records())
    # ok1: 裏 0(既知), ok2: 裏 4000+6000(既知), orch_unknown/failed: 不明。
    assert summary.orchestration_input_tokens == 4000
    assert summary.orchestration_output_tokens == 6000
    assert summary.orchestration_unknown_count == 2


def test_overhead_excludes_unknown_from_denominator():
    """裏率の全体値は「裏が分かるレコード」だけで計算し、不明件数を明示する。"""
    overhead = analyze_overhead(_records())
    assert overhead.unknown_requests == 2
    assert overhead.counted_requests == 2
    # 計上分: ok1(表300,裏0) + ok2(表1000,裏10000)。
    # overall = 10000 / (300 + 1000 + 10000) = 10000 / 11300。
    assert overhead.overall_ratio is not None
    assert math.isclose(overhead.overall_ratio, 10000 / 11300, rel_tol=1e-9)


def test_overhead_per_request_distribution():
    """リクエスト単位の裏率分布。中央値・最小・最大が出る。"""
    overhead = analyze_overhead(_records())
    # ok1 の裏率 0.0、ok2 の裏率 10000/11000。
    assert overhead.min_ratio == 0.0
    assert overhead.max_ratio is not None
    assert math.isclose(overhead.max_ratio, 10000 / 11000, rel_tol=1e-9)


def test_latency_separates_ttft_and_elapsed():
    """ttft と elapsed を分けて集計する(合算しない)。既定は成功のみ。"""
    latency = analyze_latency(_records())
    # 成功 3 件の ttft: [1.0, 50.0, 3.0], elapsed: [2.0, 60.0, 4.0]
    assert latency.ttft.count == 3
    assert latency.ttft.median == 3.0
    assert latency.ttft.maximum == 50.0
    assert latency.elapsed.median == 4.0
    assert latency.elapsed.maximum == 60.0
    # 別系列であること(取り違えていない)。
    assert latency.ttft.maximum != latency.elapsed.maximum


def test_observed_days_counts_unique_utc_dates():
    assert observed_days(_records()) == 1     # 全部 2026-07-24


def test_projection_returns_range_not_point():
    """月間外挿は low < point < high の帯で返す。"""
    proj = project_monthly(_records())
    assert proj.monthly_billed_low <= proj.monthly_billed_point <= proj.monthly_billed_high
    assert proj.sample_requests == 4
    assert proj.sample_days == 1


def test_projection_warns_when_thin():
    """薄いサンプルでは強い警告を必ず添える(自信ありげな点推定を出さない)。"""
    proj = project_monthly(_records())
    assert proj.is_thin is True
    assert proj.warnings                       # 空でない
    joined = " ".join(proj.warnings)
    assert "薄" in joined or "外挿" in joined


def test_projection_warns_about_unknown_orchestration():
    """裏不明が混じるとき、過小評価の可能性を警告する。"""
    proj = project_monthly(_records())
    assert any("裏トークン不明" in w for w in proj.warnings)


def test_projection_cost_scales_with_rates():
    """レートを渡すとコスト帯が出る。レート無しなら None。"""
    no_rate = project_monthly(_records())
    assert no_rate.monthly_cost_point is None

    with_rate = project_monthly(
        _records(),
        input_rate=1.0, output_rate=1.0,
        orchestration_input_rate=1.0, orchestration_output_rate=1.0,
    )
    assert with_rate.monthly_cost_point is not None
    assert with_rate.monthly_cost_low <= with_rate.monthly_cost_point <= with_rate.monthly_cost_high


def test_unknown_raw_keys_collected():
    """anomalies の ok2 に埋めた未知フィールドを集計できる。"""
    keys = collect_unknown_raw_keys(_records())
    assert "completion_tokens_details.new_hidden_field" in keys
