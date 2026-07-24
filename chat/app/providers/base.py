"""Provider Abstraction Layer(コア・拡張の要)。

上位層(HTTP/SSE 層・Middleware)は「どのプロバイダか」を意識しない。
新プロバイダの追加 = アダプタ 1 つ実装 + 設定追記、で完結すること。

アダプタが吸収すべき差異(設計時に想定したケース):
  - 認証方式が違う           → stream_chat 内のヘッダ組み立て
  - usage のフィールド名が違う → parse_usage を override
  - usage を返さない          → parse_usage が全 None を返し、レコードは生成される
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from app.usage.assemble import parse_usage as _openai_parse_usage


class ProviderError(Exception):
    """プロバイダ呼び出しが HTTP エラー等で失敗したときに投げる。

    レコードは必ず生成する要件のため、上位はこれを捕まえて error 付き
    UsageRecord を作る。生のエラー本文は raw に保持する。
    """

    def __init__(self, message: str, *, status: Optional[int] = None, raw: Any = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.raw = raw


class Provider(ABC):
    """全アダプタ共通インターフェース。"""

    name: str = "base"

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """ストリーミングでチャンク(パース済み dict)を 1 つずつ yield する。

        重要: チャンクは content 以外を捨てず、生の dict のまま流す。
        usage や tool_calls の抽出は後段(StreamAssembler)の責務。
        """
        raise NotImplementedError

    def parse_usage(self, raw_usage: Optional[dict[str, Any]]) -> dict[str, Optional[int]]:
        """usage を UsageRecord のトークン系フィールドに正規化する。

        既定は OpenAI 互換のマッピング。フィールド配置が違うプロバイダは override する。
        """
        return _openai_parse_usage(raw_usage)
