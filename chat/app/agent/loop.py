"""エージェントループ(tool 実行往復)— Phase 2 / A。

Fugu が `finish_reason=tool_calls` を返したら、各 tool を実行し、結果を
`role:"tool"` メッセージとして会話に足して**再度リクエストする**。content が
返る(finish_reason != tool_calls)か、上限ラウンドに達するまで繰り返す。

契約判断のために重要な設計:
- **1 ラウンド = 1 リクエスト = 1 UsageRecord**。往復ごとの裏トークン/レイテンシを
  測れるようにする(「Fugu をエージェント的に使うといくら掛かるか」の実測)。
- メッセージ組み立て(assistant.tool_calls / role:tool)は純粋関数に分け、
  ネットワーク不要で単体テストする。ここが往復の心臓部。

このモジュールは provider を「stream_chat(messages, model, params) を持つもの」としか
仮定しない。テストでは fixture を再生する FakeProvider を差し込める。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Protocol

from app.tools.registry import ToolRegistry, ToolResult
from app.usage.assemble import StreamAssembler


class _StreamProvider(Protocol):
    def stream_chat(
        self, messages: list[dict[str, Any]], model: str,
        params: Optional[dict[str, Any]] = None,
    ) -> Any: ...


# ---- 純粋なメッセージ組み立て(単体テスト対象) --------------------------------

def to_openai_tool_calls(assembled_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """StreamAssembler.tool_calls() を OpenAI の assistant.tool_calls 形へ変換する。

    arguments は**生の連結文字列(arguments_raw)**を使う。モデルが出したものを
    無加工で次リクエストに載せる(再パースで壊さない)。
    """
    out: list[dict[str, Any]] = []
    for c in assembled_calls:
        out.append({
            "id": c.get("id"),
            "type": "function",
            "function": {
                "name": c.get("name"),
                "arguments": c.get("arguments_raw", ""),
            },
        })
    return out


def assistant_message(content: str, openai_tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    """tool_calls を含む assistant メッセージ。content は空なら None(OpenAI 準拠)。"""
    return {
        "role": "assistant",
        "content": content or None,
        "tool_calls": openai_tool_calls,
    }


def tool_result_message(result: ToolResult) -> dict[str, Any]:
    """ツール実行結果を role:"tool" メッセージにする(tool_call_id で対応づけ)。"""
    return {
        "role": "tool",
        "tool_call_id": result.tool_call_id,
        "content": result.content,
    }


# ---- ループ本体 --------------------------------------------------------------

def _chunk_has_visible(chunk: dict[str, Any]) -> bool:
    """content か tool_call の断片を含むか(ttft 判定用)。"""
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if delta.get("content") or delta.get("tool_calls"):
            return True
    return False


@dataclass
class RoundInfo:
    """1 ラウンドの観測。呼び出し側が per-round の UsageRecord を作れるように渡す。"""

    index: int                          # 1 始まり
    assembler: StreamAssembler
    executed: list[ToolResult] = field(default_factory=list)
    ttft_s: Optional[float] = None      # そのラウンドの初動(秒)
    elapsed_s: Optional[float] = None   # そのラウンドの総時間(秒)


@dataclass
class AgentResult:
    final_content: str
    stop_reason: str                    # "stop" / 他 finish_reason / "max_rounds"
    rounds: int
    messages: list[dict[str, Any]]      # 往復後の完全なトランスクリプト


async def run_agent_turn(
    provider: _StreamProvider,
    model: str,
    messages: list[dict[str, Any]],
    params: Optional[dict[str, Any]],
    registry: ToolRegistry,
    *,
    max_rounds: int = 4,
    on_round: Optional[Callable[[RoundInfo], Awaitable[None]]] = None,
    on_chunk: Optional[Callable[[int, dict[str, Any]], Awaitable[None]]] = None,
) -> AgentResult:
    """tool 実行往復を回す。

    max_rounds は「暴走(無限に tool を呼び続ける)」を止める安全弁。
    on_round があれば各ラウンド完了時に、on_chunk があれば各チャンク受信時に await で呼ぶ
    (per-round の UsageRecord 記録・ブラウザへの逐次中継に使う)。
    """
    working: list[dict[str, Any]] = [dict(m) for m in messages]
    tools_param = registry.openai_tools()

    for i in range(1, max_rounds + 1):
        asm = StreamAssembler()
        call_params = dict(params or {})
        call_params["tools"] = tools_param

        start = time.perf_counter()
        ttft: Optional[float] = None
        async for chunk in provider.stream_chat(working, model, call_params):
            asm.add_chunk(chunk)
            if ttft is None and _chunk_has_visible(chunk):
                ttft = time.perf_counter() - start
            if on_chunk is not None:
                await on_chunk(i, chunk)
        elapsed = time.perf_counter() - start

        round_info = RoundInfo(index=i, assembler=asm, ttft_s=ttft, elapsed_s=elapsed)

        if asm.finish_reason != "tool_calls":
            # ツール要求なし = このターン完了。
            if on_round is not None:
                await on_round(round_info)
            return AgentResult(asm.content, asm.finish_reason or "stop", i, working)

        # ツール要求あり: assistant(tool_calls) を会話に足し、各ツールを実行して結果を足す。
        assembled = asm.tool_calls()
        working.append(assistant_message(asm.content, to_openai_tool_calls(assembled)))
        for c in assembled:
            result = registry.execute(c)
            round_info.executed.append(result)
            working.append(tool_result_message(result))

        if on_round is not None:
            await on_round(round_info)

    # 上限到達: ツールを呼び続けて収束しなかった。事実として返す(握り潰さない)。
    return AgentResult("", "max_rounds", max_rounds, working)
