"""StreamAssembler の単体テスト(ネットワーク不要・実 fixture ベース)。

チャンク列から usage と tool_call を組み立てるロジックが本アプリの心臓部。
"""
import json
from pathlib import Path

import pytest

from app.usage.assemble import StreamAssembler, iter_sse_data

FIXTURES = Path(__file__).parent / "fixtures"


def _assemble(fixture_name: str) -> StreamAssembler:
    raw = (FIXTURES / fixture_name).read_text()
    asm = StreamAssembler()
    for chunk in iter_sse_data(raw):
        asm.add_chunk(chunk)
    return asm


def test_stream_content_and_usage_from_final_empty_choices_chunk():
    asm = _assemble("fugu_stream_hi.txt")
    assert asm.content == "hi"
    # usage は choices:[] の最終チャンクに載る。捨てずに拾えていること。
    assert asm.raw_usage is not None
    fields = asm.usage_fields()
    assert fields["input_tokens"] == 99
    assert fields["output_tokens"] == 17
    assert fields["orchestration_input_tokens"] == 0
    assert asm.finish_reason == "stop"


def test_raw_chunks_are_retained():
    asm = _assemble("fugu_stream_hi.txt")
    # 生チャンクを一つも捨てていないこと(content 以外破棄しない要件)
    assert len(asm.raw_chunks) == 4
    assert any("usage" in c for c in asm.raw_chunks)


def test_tool_call_assembled_across_chunks():
    asm = _assemble("fugu_stream_toolcall_weather.txt")
    calls = asm.tool_calls()
    assert len(calls) == 1
    call = calls[0]
    assert call["id"] == "call_VhibycA1j04wMv9iFnZ7yHiI"
    assert call["name"] == "get_weather"
    # 断片(`{"` `city` `":"` `Os` `aka` `"}`) を連結して正しい JSON になること
    assert call["arguments_valid"] is True
    assert call["arguments"] == {"city": "Osaka"}
    assert asm.finish_reason == "tool_calls"
    # tool_call ストリームでも最終チャンクの usage を拾えること
    assert asm.usage_fields()["input_tokens"] == 100


def test_broken_tool_call_arguments_are_flagged_not_swallowed():
    # 引数 JSON が壊れて返るケース(壊れて返ること自体が知りたい情報)
    chunks = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "call_x", "type": "function",
             "function": {"name": "f", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": '{"city": "Os'}}]}}]},
        # 閉じ括弧が来ないまま終了
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]
    asm = StreamAssembler()
    for c in chunks:
        asm.add_chunk(c)
    call = asm.tool_calls()[0]
    assert call["arguments_valid"] is False
    assert call["arguments_error"] is not None
    # 生の断片は保持されている(復元・可視化のため)
    assert call["arguments_raw"] == '{"city": "Os'
    assert call["arguments"] is None


def test_multiple_tool_calls_kept_separate_by_index():
    chunks = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "a", "function": {"name": "f0", "arguments": "{}"}},
            {"index": 1, "id": "b", "function": {"name": "f1", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 1, "function": {"arguments": '{"x":1}'}}]}}]},
    ]
    asm = StreamAssembler()
    for c in chunks:
        asm.add_chunk(c)
    calls = asm.tool_calls()
    assert [c["name"] for c in calls] == ["f0", "f1"]
    assert calls[0]["arguments"] == {}
    assert calls[1]["arguments"] == {"x": 1}


def test_empty_arguments_is_valid_empty_object():
    chunks = [
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "a", "function": {"name": "noargs", "arguments": ""}}]}}]},
    ]
    asm = StreamAssembler()
    for c in chunks:
        asm.add_chunk(c)
    call = asm.tool_calls()[0]
    assert call["arguments_valid"] is True
    assert call["arguments"] == {}
