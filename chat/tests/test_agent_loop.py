"""エージェントループ(tool 実行往復)の単体テスト。ネットワーク不要。

round 1 は実 fixture(fugu_stream_toolcall_weather.txt)を再生し、round 2 で
最終テキストを返す FakeProvider を差し込んで、往復が完了することを検証する。
"""

import asyncio
from pathlib import Path

from app.agent.loop import (
    AgentResult,
    assistant_message,
    run_agent_turn,
    to_openai_tool_calls,
    tool_result_message,
)
from app.tools.builtins import build_registry
from app.tools.registry import ToolResult
from app.usage.assemble import iter_sse_data

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_chunks(name: str) -> list[dict]:
    return list(iter_sse_data((FIXTURES / name).read_text()))


def _final_text_chunks(text: str) -> list[dict]:
    """content を1つ返して stop で終わり、最後に usage を載せる最小の応答チャンク列。"""
    return [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 130, "completion_tokens": 12,
                                  "total_tokens": 142}},
    ]


class FakeProvider:
    """事前に用意したチャンク列を、呼ばれるたびに 1 ラウンドずつ再生する。"""

    def __init__(self, scripted_rounds: list[list[dict]]) -> None:
        self._rounds = list(scripted_rounds)
        self.calls: list[dict] = []

    async def stream_chat(self, messages, model, params=None):
        # 各リクエストの messages / params(tools 込み)を検証できるよう記録する。
        self.calls.append({"messages": [dict(m) for m in messages], "params": params})
        chunks = self._rounds.pop(0)
        for c in chunks:
            yield c


# ---- 純粋なメッセージ組み立て ----------------------------------------------

def test_to_openai_tool_calls_uses_raw_arguments():
    assembled = [{"id": "call_1", "name": "get_weather",
                  "arguments_raw": '{"city":"Osaka"}', "arguments": {"city": "Osaka"},
                  "arguments_valid": True}]
    out = to_openai_tool_calls(assembled)
    assert out == [{
        "id": "call_1", "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"Osaka"}'},
    }]


def test_assistant_message_empty_content_is_none():
    msg = assistant_message("", [{"id": "x"}])
    assert msg["role"] == "assistant"
    assert msg["content"] is None
    assert msg["tool_calls"] == [{"id": "x"}]


def test_tool_result_message_shape():
    res = ToolResult("call_1", "get_weather", True, "Osaka: 晴れ")
    msg = tool_result_message(res)
    assert msg == {"role": "tool", "tool_call_id": "call_1", "content": "Osaka: 晴れ"}


# ---- 往復ループ本体 ---------------------------------------------------------

def test_full_round_trip_executes_tool_and_completes():
    provider = FakeProvider([
        _fixture_chunks("fugu_stream_toolcall_weather.txt"),   # round1: get_weather(Osaka)
        _final_text_chunks("大阪は晴れ、28°Cです。"),              # round2: 最終回答
    ])
    registry = build_registry(allowlist=["get_weather"])
    rounds_seen = []

    async def on_round(info):
        rounds_seen.append(info)

    result: AgentResult = asyncio.run(run_agent_turn(
        provider, "fugu", [{"role": "user", "content": "大阪の天気は?"}],
        params={}, registry=registry, max_rounds=4, on_round=on_round,
    ))

    assert result.stop_reason == "stop"
    assert result.rounds == 2
    assert result.final_content == "大阪は晴れ、28°Cです。"

    # round1 でツールが実行され、その結果メッセージが会話に入っていること。
    assert len(rounds_seen) == 2
    assert rounds_seen[0].executed[0].ok is True
    assert "Osaka" in rounds_seen[0].executed[0].content

    roles = [m["role"] for m in result.messages]
    assert roles == ["user", "assistant", "tool", "assistant"] or \
           roles[:3] == ["user", "assistant", "tool"]
    # 2 回目のリクエストには、tool 結果を含む messages が渡っていること。
    second_req_roles = [m["role"] for m in provider.calls[1]["messages"]]
    assert "tool" in second_req_roles
    # tools パラメータが毎リクエストに載っていること。
    assert provider.calls[0]["params"]["tools"][0]["function"]["name"] == "get_weather"


def test_max_rounds_caps_runaway_tool_loop():
    # 毎回 tool_calls を返し続ける(収束しない)provider。
    tool_round = _fixture_chunks("fugu_stream_toolcall_weather.txt")
    provider = FakeProvider([list(tool_round) for _ in range(10)])
    registry = build_registry(allowlist=["get_weather"])

    result = asyncio.run(run_agent_turn(
        provider, "fugu", [{"role": "user", "content": "loop"}],
        params={}, registry=registry, max_rounds=3,
    ))
    assert result.stop_reason == "max_rounds"
    assert result.rounds == 3


def test_broken_tool_arguments_flow_back_and_loop_continues():
    """引数が壊れて返っても落ちず、エラーを tool メッセージで返して次ラウンドへ進む。"""
    broken_round = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_b", "type": "function",
             "function": {"name": "get_weather", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"city": "Os'}}]}}]},  # 閉じない
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    provider = FakeProvider([broken_round, _final_text_chunks("すみません、都市名を教えてください。")])
    registry = build_registry(allowlist=["get_weather"])

    result = asyncio.run(run_agent_turn(
        provider, "fugu", [{"role": "user", "content": "天気"}],
        params={}, registry=registry, max_rounds=4,
    ))
    assert result.stop_reason == "stop"
    assert result.rounds == 2
    # 壊れた引数の tool メッセージが会話に入っている(握り潰していない)。
    tool_msgs = [m for m in result.messages if m["role"] == "tool"]
    assert tool_msgs and "invalid tool arguments" in tool_msgs[0]["content"]
