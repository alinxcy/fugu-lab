"""Middleware Chain — このアプリの拡張の中心(骨組み)。

リクエスト送出前(before_request)とレスポンス受信後(after_response)にフックを差せる。
v1 では usage recorder と logger だけを載せるが、後からコアを触らずに
並列比較ディスパッチ・RAG 注入・レート制御・リトライ等を足せることが要件。

意図的に「関数フック列」ではなく最小のクラスベースにした。状態(設定・ストアパス)を
持たせやすく、after_response で例外が出ても他フックを止めない運用にできるため。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.usage.assemble import StreamAssembler


@dataclass
class RequestContext:
    """1 リクエストのライフサイクルを通じて共有される箱。

    フックはここに読み書きする。上位(HTTP 層)が計測値やアセンブラを詰める。
    """

    provider: str
    model: str
    conversation_id: str
    messages: list[dict[str, Any]]
    params: dict[str, Any]

    # 完了後に上位が埋める
    assembler: Optional[StreamAssembler] = None
    ttft_s: Optional[float] = None
    elapsed_s: Optional[float] = None
    error: Optional[str] = None
    error_raw: Any = None

    # フックが結果を書き戻す用(例: usage recorder が採番した record id)
    extra: dict[str, Any] = field(default_factory=dict)


class Middleware:
    """フックの基底。必要な側だけ override する。"""

    async def before_request(self, ctx: RequestContext) -> None:  # noqa: D401
        return None

    async def after_response(self, ctx: RequestContext) -> None:
        return None


class MiddlewareChain:
    def __init__(self, middlewares: list[Middleware]) -> None:
        self.middlewares = middlewares

    async def before_request(self, ctx: RequestContext) -> None:
        for m in self.middlewares:
            await m.before_request(ctx)

    async def after_response(self, ctx: RequestContext) -> None:
        # 1 つのフックが落ちても測定データを失わないよう、他フックは続行する。
        errors: list[str] = []
        for m in self.middlewares:
            try:
                await m.after_response(ctx)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{type(m).__name__}: {e}")
        if errors:
            ctx.extra.setdefault("middleware_errors", []).extend(errors)
