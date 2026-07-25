"""HTTP/SSE 層 — ブラウザとの中継に徹する(モデル固有の知識を持たない)。

責務:
  - 静的ファイル(チャット UI)の配信
  - POST /api/chat: ブラウザ→provider の橋渡し。SSE で逐次中継しつつ、
    生チャンクを StreamAssembler に貯め、完了後に Middleware Chain を回す。
  - 実測値(ttft/elapsed、このレコード 1 件分の裏トークン比率)を done イベントで返す。

スコープ規律: ここでは集計・コスト計算・グラフを一切やらない(dashboard/ の担当)。
done で返すのは「手元の 1 レコードの値」だけ。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.loop import RoundInfo, run_agent_turn
from app.config import Config, load_config
from app.middleware.chain import MiddlewareChain, RequestContext
from app.middleware.logger import RawLogger
from app.middleware.usage_recorder import UsageRecorder
from app.providers.base import Provider, ProviderError
from app.providers.fugu import FuguProvider
from app.store import append_usage
from app.tools.builtins import build_registry
from app.usage.assemble import StreamAssembler
from app.usage.record import UsageRecord

CHAT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = CHAT_DIR / "static"

app = FastAPI(title="fugu-chat", version="0.1.0")

_config: Optional[Config] = None
_providers: dict[str, Provider] = {}


def _build_provider(cfg: Config, name: str) -> Provider:
    pc = cfg.provider_config(name)
    adapter = pc.get("adapter")
    if adapter == "fugu":
        api_key = cfg.resolve_api_key(name)
        if not api_key:
            raise ProviderError(
                f"API キーが未設定です(環境変数 {pc.get('api_key_env')} を .env 等で設定してください)"
            )
        return FuguProvider(
            base_url=pc["base_url"],
            api_key=api_key,
            timeout_s=float(pc.get("request_timeout_s", 600)),
        )
    # 将来: openai-compat(LM Studio 等)は adapter を増やすだけで足せる(Phase 2)
    raise ProviderError(f"未知の adapter: {adapter}")


@app.on_event("startup")
def _startup() -> None:
    global _config
    _config = load_config()


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _get_provider(cfg: Config, name: str) -> Provider:
    # 鍵の解決に失敗するケースもあるので、都度組み立てても安いが、成功したものは使い回す。
    if name not in _providers:
        _providers[name] = _build_provider(cfg, name)
    return _providers[name]


class ChatRequest(BaseModel):
    messages: list[dict[str, Any]]
    provider: Optional[str] = None
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    # tools / tool_choice / max_tokens / temperature 等はそのまま provider に素通し(観測のみ)
    params: dict[str, Any] = Field(default_factory=dict)
    # --- Phase 2 / tool 実行往復(既定オフ。明示 opt-in のときだけエージェントループを回す)---
    execute_tools: bool = False
    tools_allowlist: Optional[list[str]] = None   # None なら設定の allowlist を使う
    max_rounds: int = 4                            # 暴走を止める往復上限


def _sse(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _chunk_has_content(chunk: dict[str, Any]) -> bool:
    for ch in chunk.get("choices") or []:
        if (ch.get("delta") or {}).get("content"):
            return True
    return False


def _chunk_has_tool_calls(chunk: dict[str, Any]) -> bool:
    for ch in chunk.get("choices") or []:
        if (ch.get("delta") or {}).get("tool_calls"):
            return True
    return False


def _measured_summary(record: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """この 1 レコード分の実測値だけを整形する(集計ではない)。

    実測で確認した重要事実: orchestration_* は表(prompt/completion)の部分集合ではなく
    「追加で」課金されるトークン(fugu-ultra の例で 表980 に対し 裏46,387)。
    したがって:
      課金トークン総計 = input + output + orchestration_input + orchestration_output
      裏トークン比率   = (orchestration_input + orchestration_output) / 課金トークン総計
    null と 0 を区別: orchestration がどちらか None なら比率は None(=不明)。
    (dashboard/ が中心指標として権威ある集計を行う。これは 1 レコードの目安表示。)
    """
    if not record:
        return None
    inp = record.get("input_tokens")
    out = record.get("output_tokens")
    oi = record.get("orchestration_input_tokens")
    oo = record.get("orchestration_output_tokens")

    visible = inp + out if (inp is not None and out is not None) else None
    orch = oi + oo if (oi is not None and oo is not None) else None

    total_billed: Optional[int]
    orch_ratio: Optional[float]
    if visible is not None and orch is not None:
        total_billed = visible + orch
        orch_ratio = (orch / total_billed) if total_billed else None
    else:
        total_billed = visible  # 裏が不明なら表のみ(比率は不明)
        orch_ratio = None

    return {
        "ttft_s": record.get("ttft_s"),
        "elapsed_s": record.get("elapsed_s"),
        "input_tokens": inp,
        "output_tokens": out,
        "visible_tokens": visible,
        "orchestration_tokens": orch,
        "total_tokens": total_billed,  # 表＋裏(課金総計)。裏不明なら表のみ。
        "orchestration_input_tokens": oi,
        "orchestration_output_tokens": oo,
        "orchestration_ratio": orch_ratio,
        "error": record.get("error"),
    }


@app.get("/api/config")
def api_config() -> JSONResponse:
    cfg = _get_config()
    return JSONResponse(cfg.public_view())  # 鍵は含めない


def _record_from_usage(
    cfg: Config, provider: Provider, provider_name: str, model: str,
    conversation_id: str, raw_usage: Optional[dict[str, Any]],
    ttft_s: Optional[float], elapsed_s: Optional[float], error: Optional[str],
) -> dict[str, Any]:
    """usage(または None/エラー)から UsageRecord を 1 件作って追記し、dict を返す。

    tool 実行往復では 1 ラウンド = 1 リクエスト = 1 レコード。往復ごとの裏トークン/
    レイテンシを dashboard 側が集計できるようにする。null/0 区別は parse_usage が担保。
    """
    fields = provider.parse_usage(raw_usage)
    record = UsageRecord(
        provider=provider_name, model=model, conversation_id=conversation_id,
        ttft_s=ttft_s, elapsed_s=elapsed_s,
        input_tokens=fields["input_tokens"], output_tokens=fields["output_tokens"],
        cached_tokens=fields["cached_tokens"],
        orchestration_input_tokens=fields["orchestration_input_tokens"],
        orchestration_output_tokens=fields["orchestration_output_tokens"],
        raw_usage=raw_usage, error=error,
    )
    append_usage(cfg.usage_log_path, record.to_dict())
    return record.to_dict()


async def _agent_event_gen(
    cfg: Config, req: ChatRequest, provider_name: str, model: str, conversation_id: str,
):
    """tool 実行往復を SSE で中継する。

    コールバック(on_chunk/on_round)はジェネレータに直接 yield できないので、
    asyncio.Queue を挟んで橋渡しする。エージェントは別タスクで走らせ、こちらは
    キューを吐き出し続ける。各ラウンドで UsageRecord を必ず 1 件記録する。
    """
    # provider 構築失敗(鍵未設定など)でもレコードは 1 件残す(schema 要件)。
    try:
        provider = _get_provider(cfg, provider_name)
    except ProviderError as e:
        record = _record_from_usage(
            cfg, _NullProvider(), provider_name, model, conversation_id,
            None, None, None, e.message)
        yield _sse({"type": "error", "error": e.message})
        yield _sse({"type": "done", "conversation_id": conversation_id,
                    "stop_reason": "error", "rounds": 0,
                    "measured": _measured_summary(record)})
        return

    allowlist = req.tools_allowlist if req.tools_allowlist is not None else cfg.tools_allowlist
    registry = build_registry(allowlist=allowlist)
    # execute モードではツール定義はレジストリが与える。params 側の tools は使わない。
    params = {k: v for k, v in (req.params or {}).items() if k != "tools"}

    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    async def on_chunk(round_i: int, chunk: dict[str, Any]) -> None:
        if _chunk_has_content(chunk):
            for ch in chunk.get("choices") or []:
                c = (ch.get("delta") or {}).get("content")
                if c:
                    await queue.put(_sse({"type": "delta", "round": round_i, "content": c}))
        if _chunk_has_tool_calls(chunk):
            await queue.put(_sse({"type": "tool_partial", "round": round_i}))
        if chunk.get("_parse_error"):
            await queue.put(_sse({"type": "warning", "message": "壊れた SSE 行を受信",
                                  "raw": chunk.get("_raw_line")}))

    async def on_round(info: RoundInfo) -> None:
        record = _record_from_usage(
            cfg, provider, provider_name, model, conversation_id,
            info.assembler.raw_usage, info.ttft_s, info.elapsed_s, None)
        for res in info.executed:
            await queue.put(_sse({"type": "tool_result", "round": info.index,
                                  "name": res.name, "ok": res.ok, "content": res.content}))
        await queue.put(_sse({"type": "round_done", "round": info.index,
                              "finish_reason": info.assembler.finish_reason,
                              "measured": _measured_summary(record)}))

    async def drive() -> None:
        try:
            result = await run_agent_turn(
                provider, model, req.messages, params, registry,
                max_rounds=req.max_rounds, on_round=on_round, on_chunk=on_chunk)
            await queue.put(_sse({"type": "done", "conversation_id": conversation_id,
                                  "final_content": result.final_content,
                                  "stop_reason": result.stop_reason, "rounds": result.rounds}))
        except ProviderError as e:
            # あるラウンドの呼び出しが失敗。エラーレコードを 1 件残す(usage は取れないので None)。
            _record_from_usage(cfg, provider, provider_name, model, conversation_id,
                               None, None, None, e.message)
            await queue.put(_sse({"type": "error", "error": e.message}))
            await queue.put(_sse({"type": "done", "conversation_id": conversation_id,
                                  "stop_reason": "error"}))
        except Exception as e:  # noqa: BLE001
            await queue.put(_sse({"type": "error", "error": f"{type(e).__name__}: {e}"}))
            await queue.put(_sse({"type": "done", "conversation_id": conversation_id,
                                  "stop_reason": "error"}))
        finally:
            await queue.put(_SENTINEL)

    task = asyncio.create_task(drive())
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item
    finally:
        await task


class _NullProvider(Provider):
    """usage を持たないダミー(provider 構築前に失敗したときの parse_usage 用)。"""

    name = "null"

    def stream_chat(self, messages, model, params=None):  # pragma: no cover - 呼ばれない
        raise NotImplementedError


@app.post("/api/chat")
async def api_chat(req: ChatRequest, request: Request) -> StreamingResponse:
    cfg = _get_config()
    provider_name = req.provider or cfg.default_provider
    model = req.model or cfg.provider_config(provider_name).get("default_model") or cfg.default_model
    conversation_id = req.conversation_id or uuid.uuid4().hex

    # --- Phase 2: tool 実行往復(明示 opt-in のときだけ)---------------------------
    if req.execute_tools:
        return StreamingResponse(
            _agent_event_gen(cfg, req, provider_name, model, conversation_id),
            media_type="text/event-stream",
        )

    assembler = StreamAssembler()
    ctx = RequestContext(
        provider=provider_name,
        model=model,
        conversation_id=conversation_id,
        messages=req.messages,
        params=req.params,
        assembler=assembler,
    )

    async def event_gen():
        start = time.perf_counter()
        # provider 構築失敗(鍵未設定など)もレコードを残す
        try:
            provider = _get_provider(cfg, provider_name)
        except ProviderError as e:
            ctx.error = e.message
            ctx.error_raw = e.raw
            ctx.elapsed_s = time.perf_counter() - start
            yield _sse({"type": "error", "error": e.message})
            await _finalize(ctx, cfg, provider=None, assembler=assembler)
            yield _sse(_done_event(ctx, assembler))
            return

        chain = MiddlewareChain([
            UsageRecorder(provider, cfg.usage_log_path),
            RawLogger(cfg.raw_log_path),
        ])
        await chain.before_request(ctx)

        try:
            async for chunk in provider.stream_chat(req.messages, model, req.params):
                assembler.add_chunk(chunk)
                if ctx.ttft_s is None and _chunk_has_content(chunk):
                    ctx.ttft_s = time.perf_counter() - start
                # ブラウザへ逐次中継
                if _chunk_has_content(chunk):
                    # content の断片だけ抜いて送る(表示用。生は assembler が保持済み)
                    for ch in chunk.get("choices") or []:
                        c = (ch.get("delta") or {}).get("content")
                        if c:
                            yield _sse({"type": "delta", "content": c})
                if _chunk_has_tool_calls(chunk):
                    # 組み立て途中のスナップショットを送る(観測: delta 蓄積の可視化)
                    yield _sse({"type": "tool_partial", "tool_calls": assembler.tool_calls()})
                if chunk.get("_parse_error"):
                    yield _sse({"type": "warning", "message": "壊れた SSE 行を受信", "raw": chunk.get("_raw_line")})
        except ProviderError as e:
            ctx.error = e.message
            ctx.error_raw = e.raw
            yield _sse({"type": "error", "error": e.message})
        except Exception as e:  # noqa: BLE001
            ctx.error = f"{type(e).__name__}: {e}"
            yield _sse({"type": "error", "error": ctx.error})
        finally:
            ctx.elapsed_s = time.perf_counter() - start
            await chain.after_response(ctx)

        yield _sse(_done_event(ctx, assembler))

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def _done_event(ctx: RequestContext, assembler: StreamAssembler) -> dict[str, Any]:
    record = ctx.extra.get("record")
    return {
        "type": "done",
        "conversation_id": ctx.conversation_id,
        "record_id": record["id"] if record else None,
        "measured": _measured_summary(record),
        "tool_calls": assembler.tool_calls(),
        "content": assembler.content,
        "finish_reason": assembler.finish_reason,
    }


async def _finalize(ctx: RequestContext, cfg: Config, provider: Optional[Provider], assembler: StreamAssembler) -> None:
    """provider 構築前に失敗したときでも、レコードは必ず 1 件残す。"""
    from app.usage.record import UsageRecord
    from app.store import append_usage

    record = UsageRecord(
        provider=ctx.provider,
        model=ctx.model,
        conversation_id=ctx.conversation_id,
        ttft_s=ctx.ttft_s,
        elapsed_s=ctx.elapsed_s,
        input_tokens=None,
        output_tokens=None,
        raw_usage=None,
        error=ctx.error,
    )
    append_usage(cfg.usage_log_path, record.to_dict())
    ctx.extra["record"] = record.to_dict()


# 静的ファイル(UI)。API ルートの後にマウントする。
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
