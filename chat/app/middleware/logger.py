"""logger フック — リクエスト/レスポンスの生ログをローカル保存する。

デバッグと後の分析用。生チャンクを丸ごと残すことで、SSE の取りこぼしや
プロバイダ側の仕様変更を後から追える(content 以外を捨てない要件の裏付け)。
追記専用・別ファイル(usage の JSONL は汚さない)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.middleware.chain import Middleware, RequestContext
from app.store import append_raw_log


class RawLogger(Middleware):
    def __init__(self, raw_log_path: Path) -> None:
        self.raw_log_path = raw_log_path

    async def after_response(self, ctx: RequestContext) -> None:
        asm = ctx.assembler
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": ctx.provider,
            "model": ctx.model,
            "conversation_id": ctx.conversation_id,
            "request": {"messages": ctx.messages, "params": ctx.params},
            "raw_chunks": asm.raw_chunks if asm is not None else None,
            "content": asm.content if asm is not None else None,
            "finish_reason": asm.finish_reason if asm is not None else None,
            "error": ctx.error,
            "error_raw": ctx.error_raw,
        }
        append_raw_log(self.raw_log_path, entry)
