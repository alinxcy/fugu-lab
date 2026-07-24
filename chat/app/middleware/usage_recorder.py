"""usage recorder フック — v1 の要。

parse_usage の結果を UsageRecord にして JSONL へ追記する。失敗・欠損でも
レコードは必ず 1 件生成する(取れないフィールドは None のまま)。
"""
from __future__ import annotations

from pathlib import Path

from app.middleware.chain import Middleware, RequestContext
from app.providers.base import Provider
from app.store import append_usage
from app.usage.record import UsageRecord


class UsageRecorder(Middleware):
    def __init__(self, provider: Provider, usage_log_path: Path) -> None:
        self.provider = provider
        self.usage_log_path = usage_log_path

    async def after_response(self, ctx: RequestContext) -> None:
        asm = ctx.assembler
        raw_usage = asm.raw_usage if asm is not None else None

        # provider.parse_usage はマッピングを担うが、raw_usage は無加工で必ず保存する。
        fields = self.provider.parse_usage(raw_usage)

        record = UsageRecord(
            provider=ctx.provider,
            model=ctx.model,
            conversation_id=ctx.conversation_id,
            ttft_s=ctx.ttft_s,
            elapsed_s=ctx.elapsed_s,
            input_tokens=fields["input_tokens"],
            output_tokens=fields["output_tokens"],
            cached_tokens=fields["cached_tokens"],
            orchestration_input_tokens=fields["orchestration_input_tokens"],
            orchestration_output_tokens=fields["orchestration_output_tokens"],
            raw_usage=raw_usage,  # 無加工。唯一の保険。
            error=ctx.error,
        )
        append_usage(self.usage_log_path, record.to_dict())
        # 上位(HTTP 層)が実測値をブラウザに返せるよう、結果を ctx に書き戻す。
        ctx.extra["record"] = record.to_dict()
