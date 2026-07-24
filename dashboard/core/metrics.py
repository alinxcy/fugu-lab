"""集計ロジック。純粋関数のみ。表示層(Streamlit)からもテストからも呼べる。

設計上もっとも重要なこと(dashboard/SPEC.md・PROMPT.md):
- **サンプル数を隠さない**。どの集計値にも「何件・何日から算出したか」を添える。
- **null と 0 を区別**。裏が不明なレコードは裏率の母数から除外し、その件数を明示。
- **枠フィット推定は外挿**。点推定でなく**幅**で返し、薄いときの警告を必ず添える。
- コストは「正確な請求額」ではなく**相対的な重さの指標**。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .record import UsageRecord

# 月間外挿の基準日数。金・土の測定窓を 30 日相当に伸ばす。
DAYS_PER_MONTH = 30

# サンプルが「薄い」とみなす閾値(これ以下なら強い警告を出す)。
THIN_REQUEST_THRESHOLD = 10
THIN_DAY_THRESHOLD = 3


# ---------------------------------------------------------------------------
# トークン消費サマリ
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TokenSummary:
    """トークン各種の合計と件数。null(不明)は合計に足さず件数で追跡する。"""

    request_count: int
    success_count: int
    error_count: int

    input_tokens: int
    output_tokens: int

    # cached / orchestration は「不明(None)」が混じりうるので、
    # 合計と「不明だった件数」を分けて持つ。0 は合計に含める。
    cached_tokens: int
    cached_unknown_count: int

    orchestration_input_tokens: int
    orchestration_output_tokens: int
    orchestration_unknown_count: int

    # 参考: reasoning_tokens(スキーマ未定義の隠れコスト)。
    reasoning_tokens: int
    reasoning_unknown_count: int

    @property
    def visible_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def orchestration_tokens(self) -> int:
        return self.orchestration_input_tokens + self.orchestration_output_tokens

    @property
    def billed_tokens(self) -> int:
        """課金トークン総計(裏が分かっている分のみの合計に基づく)。"""
        return self.visible_tokens + self.orchestration_tokens


def summarize_tokens(records: list[UsageRecord]) -> TokenSummary:
    """レコード列のトークン合計を出す。null は 0 埋めせず「不明件数」で追跡。"""
    input_sum = output_sum = 0
    cached_sum = cached_unknown = 0
    orch_in_sum = orch_out_sum = orch_unknown = 0
    reasoning_sum = reasoning_unknown = 0
    success = error = 0

    for r in records:
        input_sum += r.input_tokens
        output_sum += r.output_tokens

        if r.cached_tokens is None:
            cached_unknown += 1
        else:
            cached_sum += r.cached_tokens

        if r.orchestration_known:
            orch_in_sum += r.orchestration_input_tokens
            orch_out_sum += r.orchestration_output_tokens
        else:
            orch_unknown += 1

        if r.reasoning_tokens is None:
            reasoning_unknown += 1
        else:
            reasoning_sum += r.reasoning_tokens

        if r.is_success:
            success += 1
        else:
            error += 1

    return TokenSummary(
        request_count=len(records),
        success_count=success,
        error_count=error,
        input_tokens=input_sum,
        output_tokens=output_sum,
        cached_tokens=cached_sum,
        cached_unknown_count=cached_unknown,
        orchestration_input_tokens=orch_in_sum,
        orchestration_output_tokens=orch_out_sum,
        orchestration_unknown_count=orch_unknown,
        reasoning_tokens=reasoning_sum,
        reasoning_unknown_count=reasoning_unknown,
    )


# ---------------------------------------------------------------------------
# オーバーヘッド(裏トークン比率)分析 — 中心指標
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OverheadAnalysis:
    """裏トークン比率の全体値とリクエスト単位の分布。"""

    # 全体値: 母集団(裏が分かるレコード)の合計 裏 / 合計 課金。
    overall_ratio: Optional[float]
    # 分布に使えたリクエスト数(裏が分かるもの)と、除外した「不明」件数。
    counted_requests: int
    unknown_requests: int
    # リクエスト単位の裏率の分布(裏が分かるレコードそれぞれの ratio)。
    per_request_ratios: tuple[float, ...] = field(default_factory=tuple)

    @property
    def median_ratio(self) -> Optional[float]:
        if not self.per_request_ratios:
            return None
        return statistics.median(self.per_request_ratios)

    @property
    def min_ratio(self) -> Optional[float]:
        return min(self.per_request_ratios) if self.per_request_ratios else None

    @property
    def max_ratio(self) -> Optional[float]:
        return max(self.per_request_ratios) if self.per_request_ratios else None


def analyze_overhead(records: list[UsageRecord]) -> OverheadAnalysis:
    """裏トークン比率を、全体値とリクエスト単位分布の両方で出す。

    「裏が不明(None)」のレコードは母数から除外し、その件数を明示する
    (null と 0 の区別。0 は含める)。
    """
    visible_sum = 0
    orch_sum = 0
    counted = 0
    unknown = 0
    ratios: list[float] = []

    for r in records:
        if not r.orchestration_known:
            unknown += 1
            continue
        counted += 1
        visible_sum += r.visible_tokens
        orch_sum += r.orchestration_tokens
        ratio = r.orchestration_ratio
        if ratio is not None:
            ratios.append(ratio)

    billed = visible_sum + orch_sum
    overall = (orch_sum / billed) if billed > 0 else None

    return OverheadAnalysis(
        overall_ratio=overall,
        counted_requests=counted,
        unknown_requests=unknown,
        per_request_ratios=tuple(ratios),
    )


# ---------------------------------------------------------------------------
# レイテンシ分析 — ttft と elapsed を分けて
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LatencyStats:
    """1 系列(ttft か elapsed)の分布統計。平均だけにしない(中央値・最大も)。"""

    count: int
    median: Optional[float]
    maximum: Optional[float]
    mean: Optional[float]


def _latency_stats(values: list[float]) -> LatencyStats:
    if not values:
        return LatencyStats(0, None, None, None)
    return LatencyStats(
        count=len(values),
        median=statistics.median(values),
        maximum=max(values),
        mean=statistics.fmean(values),
    )


@dataclass(frozen=True)
class LatencyAnalysis:
    """ttft(初動)と elapsed(総時間)を**分けて**保持する。合算しない。"""

    ttft: LatencyStats
    elapsed: LatencyStats


def analyze_latency(records: list[UsageRecord], *, success_only: bool = True) -> LatencyAnalysis:
    """レイテンシを ttft / elapsed 別に集計する。既定では成功レコードのみ。"""
    target = [r for r in records if r.is_success] if success_only else list(records)
    ttft_values = [r.ttft_s for r in target]
    elapsed_values = [r.elapsed_s for r in target]
    return LatencyAnalysis(_latency_stats(ttft_values), _latency_stats(elapsed_values))


# ---------------------------------------------------------------------------
# 期間(日別)集計
# ---------------------------------------------------------------------------

def _record_date(r: UsageRecord) -> Optional[str]:
    """timestamp から YYYY-MM-DD(UTC)を取り出す。パースできなければ None。"""
    try:
        dt = datetime.fromisoformat(r.timestamp)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()


def observed_days(records: list[UsageRecord]) -> int:
    """レコードが実際に存在する日数(ユニークな UTC 日付の数)。"""
    days = {d for r in records if (d := _record_date(r)) is not None}
    return len(days)


def group_by_day(records: list[UsageRecord]) -> dict[str, list[UsageRecord]]:
    """日別(UTC)にレコードをまとめる。日付不明のものは 'unknown' キーへ。"""
    buckets: dict[str, list[UsageRecord]] = {}
    for r in records:
        key = _record_date(r) or "unknown"
        buckets.setdefault(key, []).append(r)
    return dict(sorted(buckets.items()))


# ---------------------------------------------------------------------------
# 枠フィット推定(月間外挿)— 点推定でなく幅・警告を必ず添える
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MonthlyProjection:
    """月間の課金トークン/コストの外挿。**幅**とサンプル情報を必ず伴う。

    - low / point / high は「軽く使えば / 現ペース / ヘビーに使えば」の帯。
    - sample_requests / sample_days は算出の根拠。
    - warnings は薄さ・不明混入などの明示警告。空でないなら UI で強調する。
    """

    sample_requests: int
    sample_days: int

    billed_tokens_observed: int          # 測定窓での課金トークン実測合計
    orchestration_unknown_count: int     # 裏不明で総計に含められなかった件数

    daily_billed_point: float            # 1 日あたり課金トークン(現ペース)
    monthly_billed_low: float
    monthly_billed_point: float
    monthly_billed_high: float

    monthly_cost_low: Optional[float]
    monthly_cost_point: Optional[float]
    monthly_cost_high: Optional[float]

    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_thin(self) -> bool:
        return (
            self.sample_requests <= THIN_REQUEST_THRESHOLD
            or self.sample_days <= THIN_DAY_THRESHOLD
        )


def project_monthly(
    records: list[UsageRecord],
    *,
    input_rate: Optional[float] = None,
    output_rate: Optional[float] = None,
    orchestration_input_rate: Optional[float] = None,
    orchestration_output_rate: Optional[float] = None,
    spread: float = 0.5,
) -> MonthlyProjection:
    """測定窓から月間使用量を外挿する。

    レート(1 トークンあたり)は設定ファイルから渡す。渡さなければコストは None
    (トークン量だけ外挿する)。``spread`` は幅の広さ(0.5 なら ±50%)。

    幅の考え方: 2 日しか窓が無いので分散を信頼できない。よって観測日ごとの
    ばらつきが取れるならそれを使い、取れないほど薄いときは ``spread`` で
    機械的に帯を広げ、「これは外挿の不確実性であって実測ではない」ことを警告で明示する。
    """
    warnings: list[str] = []

    days = observed_days(records)
    n = len(records)
    summary = summarize_tokens(records)
    billed_observed = summary.billed_tokens

    if summary.orchestration_unknown_count > 0:
        warnings.append(
            f"裏トークン不明のレコードが {summary.orchestration_unknown_count} 件あり、"
            f"課金トークン総計に含めていません(過小評価の可能性)。"
        )

    # 日別の課金トークン量(裏が分かる分のみ)。
    daily_billed: list[float] = []
    for _, day_records in group_by_day(records).items():
        day_summary = summarize_tokens(day_records)
        daily_billed.append(float(day_summary.billed_tokens))

    effective_days = max(days, 1)
    daily_point = billed_observed / effective_days

    if days >= 2 and len(daily_billed) >= 2:
        # 観測日の最小/最大を帯の下限/上限の材料に使う(実測ベースの幅)。
        low_daily = min(daily_billed)
        high_daily = max(daily_billed)
    else:
        # 1 日以下しか無い/日別に割れない → 機械的に spread で広げる。
        low_daily = daily_point * (1 - spread)
        high_daily = daily_point * (1 + spread)
        warnings.append(
            "観測日数が 1 日相当以下のため、幅は実測のばらつきではなく "
            f"±{int(spread * 100)}% の外挿仮定です。"
        )

    monthly_point = daily_point * DAYS_PER_MONTH
    monthly_low = low_daily * DAYS_PER_MONTH
    monthly_high = high_daily * DAYS_PER_MONTH

    if n <= THIN_REQUEST_THRESHOLD:
        warnings.append(
            f"サンプルが {n} 件と薄く、この月間推定は強い不確実性を含みます。"
            f"点推定として受け取らないこと。"
        )
    if days <= THIN_DAY_THRESHOLD:
        warnings.append(
            f"測定日数が {days} 日と短く、曜日・用途の偏りが平準化されていません。"
        )

    cost_low = cost_point = cost_high = None
    if None not in (input_rate, output_rate, orchestration_input_rate, orchestration_output_rate):
        # 課金トークンをそのまま金額換算するのではなく、
        # 「入力/出力/裏入力/裏出力」ごとに月間量を按分してレートを掛ける。
        share_scale_point = monthly_point / billed_observed if billed_observed else 0.0
        share_scale_low = monthly_low / billed_observed if billed_observed else 0.0
        share_scale_high = monthly_high / billed_observed if billed_observed else 0.0

        def _cost(scale: float) -> float:
            return (
                summary.input_tokens * scale * input_rate
                + summary.output_tokens * scale * output_rate
                + summary.orchestration_input_tokens * scale * orchestration_input_rate
                + summary.orchestration_output_tokens * scale * orchestration_output_rate
            )

        cost_low = _cost(share_scale_low)
        cost_point = _cost(share_scale_point)
        cost_high = _cost(share_scale_high)

    return MonthlyProjection(
        sample_requests=n,
        sample_days=days,
        billed_tokens_observed=billed_observed,
        orchestration_unknown_count=summary.orchestration_unknown_count,
        daily_billed_point=daily_point,
        monthly_billed_low=monthly_low,
        monthly_billed_point=monthly_point,
        monthly_billed_high=monthly_high,
        monthly_cost_low=cost_low,
        monthly_cost_point=cost_point,
        monthly_cost_high=cost_high,
        warnings=tuple(warnings),
    )


def collect_unknown_raw_keys(records: list[UsageRecord]) -> dict[str, int]:
    """raw_usage に現れた未知フィールドを集計する(プロバイダ仕様変更の検知)。"""
    counts: dict[str, int] = {}
    for r in records:
        for key in r.unknown_raw_keys:
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
