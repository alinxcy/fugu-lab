"""UsageRecord — schema/usage-record.md のデータ契約を実装する。

このモジュールはスキーマの「唯一の正」に従うだけで、集計やコスト計算は行わない
(それは dashboard/ の担当)。フィールドの増減は schema/usage-record.md を変えた
ときだけ行うこと。
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    # ISO 8601 + タイムゾーン付き (schema 要件)
    return datetime.now(timezone.utc).isoformat()


@dataclass
class UsageRecord:
    """schema/usage-record.md のフィールド定義に 1:1 対応。

    譲れない要件:
      - null と 0 を区別する: 取得できなかった数値フィールドは None のまま(0 で埋めない)。
      - raw_usage はプロバイダが返した usage を無加工で保持する(唯一の保険)。
      - 失敗・欠損でもレコードは必ず 1 件生成する(取れないフィールドは None)。
    """

    # 必須
    provider: str
    model: str
    conversation_id: str
    ttft_s: Optional[float]
    elapsed_s: Optional[float]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    raw_usage: Optional[dict[str, Any]]

    # 任意 (取れなければ None)
    cached_tokens: Optional[int] = None
    orchestration_input_tokens: Optional[int] = None
    orchestration_output_tokens: Optional[int] = None
    error: Optional[str] = None

    # 自動採番
    id: str = field(default_factory=_new_id)
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        """JSONL への 1 行分。schema の列順に近い形で返す。"""
        d = asdict(self)
        ordered_keys = [
            "id",
            "timestamp",
            "provider",
            "model",
            "conversation_id",
            "ttft_s",
            "elapsed_s",
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "orchestration_input_tokens",
            "orchestration_output_tokens",
            "raw_usage",
            "error",
        ]
        return {k: d[k] for k in ordered_keys}
