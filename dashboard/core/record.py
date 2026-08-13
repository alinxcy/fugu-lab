"""UsageRecord のパースと派生指標。

依存は ``../../schema/usage-record.md`` の定義のみ。``chat/`` のコードは import しない。

このモジュールの責務:
- 生 dict(JSON 1 行分)を UsageRecord に変換する
- **null と 0 を厳密に区別する**(裏 0 と 裏不明はまったく別の意味)
- 契約判断の中心指標である**裏トークン比率**を、
  スキーマ/実データで確認した定義で計算する
- ``raw_usage`` に現れた**未知フィールド**(プロバイダ仕様変更の兆候)を検知する

裏率の定義(schema/usage-record.md・sample-data/README.md で実測裏付け済み):

    課金トークン総計 = input + output + orchestration_input + orchestration_output
    裏トークン比率   = (orchestration_input + orchestration_output) / 課金トークン総計

orchestration_* は表(prompt/completion)の部分集合ではなく**追加課金**。
分母を「表のみ」にすると 100% を超える誤りになる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# UsageRecord の必須フィールド(schema/usage-record.md「フィールド定義」の必須列)。
# これらが欠けている行は「壊れている」とみなしてスキップ対象にする。
REQUIRED_FIELDS = (
    "id",
    "timestamp",
    "provider",
    "model",
    "conversation_id",
    "ttft_s",
    "elapsed_s",
    "input_tokens",
    "output_tokens",
    "raw_usage",
)

# raw_usage の中に現れることが既に分かっているキー(スキーマ未定義の追加分も含む)。
# ここに無いキーが raw_usage に現れたら「未知フィールド出現」として知らせる。
# — プロバイダ側の仕様変更に気づくための保険(schema 要件 1)。
KNOWN_RAW_TOP_KEYS = frozenset(
    {"prompt_tokens", "completion_tokens", "total_tokens",
     "prompt_tokens_details", "completion_tokens_details"}
)
KNOWN_RAW_PROMPT_DETAIL_KEYS = frozenset(
    {"cached_tokens", "orchestration_input_tokens", "orchestration_input_cached_tokens"}
)
KNOWN_RAW_COMPLETION_DETAIL_KEYS = frozenset(
    {"reasoning_tokens", "orchestration_output_tokens"}
)


class RecordError(ValueError):
    """1 レコードがパースできないときに投げる。ローダがこれを捕まえて行をスキップする。"""


def _num(value: Any, field_name: str) -> float:
    """数値フィールドを float として取り出す。bool は数値扱いしない。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{field_name} は数値である必要があります: {value!r}")
    return float(value)


def _opt_int(value: Any, field_name: str) -> Optional[int]:
    """null 許容の整数フィールド。**キー欠落と null は None、0 は 0 として保つ**。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{field_name} は数値か null である必要があります: {value!r}")
    return int(value)


def _detect_unknown_raw_keys(raw_usage: dict) -> list[str]:
    """raw_usage 内のスキーマ/既知セット外キーを列挙する(ドット記法のパスで返す)。"""
    unknown: list[str] = []
    for key in raw_usage:
        if key not in KNOWN_RAW_TOP_KEYS:
            unknown.append(key)
    prompt_details = raw_usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        for key in prompt_details:
            if key not in KNOWN_RAW_PROMPT_DETAIL_KEYS:
                unknown.append(f"prompt_tokens_details.{key}")
    completion_details = raw_usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        for key in completion_details:
            if key not in KNOWN_RAW_COMPLETION_DETAIL_KEYS:
                unknown.append(f"completion_tokens_details.{key}")
    return unknown


@dataclass(frozen=True)
class UsageRecord:
    """1 リクエスト分の使用記録と、そこから導かれる指標。

    トークン系のうち ``cached_tokens`` / ``orchestration_input_tokens`` /
    ``orchestration_output_tokens`` は **None(取得できず=不明)** と
    **0(実際に 0 だった)** を区別する。集計側もこれを尊重すること。
    """

    id: str
    timestamp: str
    provider: str
    model: str
    conversation_id: str
    ttft_s: float
    elapsed_s: float
    input_tokens: int
    output_tokens: int
    cached_tokens: Optional[int]
    orchestration_input_tokens: Optional[int]
    orchestration_output_tokens: Optional[int]
    raw_usage: dict
    error: Optional[str]
    # raw_usage に現れた未知キー(空なら既知形状)。
    unknown_raw_keys: tuple[str, ...] = field(default_factory=tuple)

    # ---- 派生指標 --------------------------------------------------------

    @property
    def is_success(self) -> bool:
        """error が None なら成功。空文字は「エラー内容不明の失敗」とはせず成功扱いしない。"""
        return self.error is None

    @property
    def orchestration_known(self) -> bool:
        """裏トークンが両方とも取得できているか。片方でも None なら「不明」として扱う。"""
        return (
            self.orchestration_input_tokens is not None
            and self.orchestration_output_tokens is not None
        )

    @property
    def orchestration_tokens(self) -> Optional[int]:
        """裏トークン合計。取れていなければ None(0 埋めしない)。"""
        if not self.orchestration_known:
            return None
        return self.orchestration_input_tokens + self.orchestration_output_tokens

    @property
    def visible_tokens(self) -> int:
        """表(見えている)トークン = input + output。"""
        return self.input_tokens + self.output_tokens

    @property
    def billed_tokens(self) -> Optional[int]:
        """課金トークン総計 = 表 + 裏。裏が不明なら総計も不明(None)。

        裏は表の部分集合ではなく追加課金なので、単純加算でよい。
        """
        orch = self.orchestration_tokens
        if orch is None:
            return None
        return self.visible_tokens + orch

    @property
    def orchestration_ratio(self) -> Optional[float]:
        """裏トークン比率 = 裏 / 課金総計。中心指標。

        裏が不明なら None(母数から除外できるように)。
        課金総計が 0(全トークン 0)なら比率は定義できないので None。
        """
        billed = self.billed_tokens
        if billed is None or billed == 0:
            return None
        return self.orchestration_tokens / billed

    @property
    def reasoning_tokens(self) -> Optional[int]:
        """raw_usage から拾う reasoning_tokens(スキーマ未定義・参考の隠れコスト)。

        「課金される出力のうち中身が見えない分」。裏率とは別軸。
        schema への昇格是非はユーザー判断なので、ここでは参考値として拾うだけ。
        """
        details = self.raw_usage.get("completion_tokens_details")
        if not isinstance(details, dict):
            return None
        value = details.get("reasoning_tokens")
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)


def parse_record(obj: Any) -> UsageRecord:
    """JSON パース済みの 1 レコード(dict)を UsageRecord にする。

    必須フィールド欠落・型不正は :class:`RecordError` を投げる(ローダがスキップ)。
    """
    if not isinstance(obj, dict):
        raise RecordError(f"レコードはオブジェクトである必要があります: {type(obj).__name__}")

    missing = [f for f in REQUIRED_FIELDS if f not in obj]
    if missing:
        raise RecordError(f"必須フィールド欠落: {', '.join(missing)}")

    raw_usage = obj["raw_usage"]
    if not isinstance(raw_usage, dict):
        raise RecordError(f"raw_usage はオブジェクトである必要があります: {type(raw_usage).__name__}")

    error = obj.get("error")
    if error is not None and not isinstance(error, str):
        raise RecordError(f"error は文字列か null である必要があります: {error!r}")

    for name in ("id", "timestamp", "provider", "model", "conversation_id"):
        if not isinstance(obj[name], str):
            raise RecordError(f"{name} は文字列である必要があります: {obj[name]!r}")

    return UsageRecord(
        id=obj["id"],
        timestamp=obj["timestamp"],
        provider=obj["provider"],
        model=obj["model"],
        conversation_id=obj["conversation_id"],
        ttft_s=_num(obj["ttft_s"], "ttft_s"),
        elapsed_s=_num(obj["elapsed_s"], "elapsed_s"),
        input_tokens=int(_num(obj["input_tokens"], "input_tokens")),
        output_tokens=int(_num(obj["output_tokens"], "output_tokens")),
        cached_tokens=_opt_int(obj.get("cached_tokens"), "cached_tokens"),
        orchestration_input_tokens=_opt_int(
            obj.get("orchestration_input_tokens"), "orchestration_input_tokens"
        ),
        orchestration_output_tokens=_opt_int(
            obj.get("orchestration_output_tokens"), "orchestration_output_tokens"
        ),
        raw_usage=raw_usage,
        error=error,
        unknown_raw_keys=tuple(_detect_unknown_raw_keys(raw_usage)),
    )
