"""/api/chat の tool 実行往復(execute_tools)経路の統合テスト。ネットワーク不要。

FakeProvider を注入し、SSE イベント列と、往復ごとに usage.jsonl が
1 行ずつ書かれることを検証する。
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.usage.assemble import iter_sse_data  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class _FakeProvider:
    def __init__(self, rounds):
        self._rounds = [list(r) for r in rounds]

    def parse_usage(self, raw_usage):
        from app.usage.assemble import parse_usage
        return parse_usage(raw_usage)

    async def stream_chat(self, messages, model, params=None):
        for c in self._rounds.pop(0):
            yield c


def _final_text_chunks(text):
    return [
        {"choices": [{"index": 0, "delta": {"content": text}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 130, "completion_tokens": 12,
                                  "total_tokens": 142,
                                  "prompt_tokens_details": {"orchestration_input_tokens": 40},
                                  "completion_tokens_details": {"orchestration_output_tokens": 30}}},
    ]


def _events(resp_text):
    return list(iter_sse_data(resp_text))


def test_execute_tools_round_trip_writes_per_round_records(tmp_path, monkeypatch):
    usage_path = tmp_path / "usage.jsonl"

    # 設定の usage_log_path を tmp に差し替え、provider を FakeProvider に。
    cfg = main._get_config()
    monkeypatch.setattr(type(cfg), "usage_log_path", property(lambda self: usage_path))
    tool_round = list(iter_sse_data((FIXTURES / "fugu_stream_toolcall_weather.txt").read_text()))
    fake = _FakeProvider([tool_round, _final_text_chunks("大阪は晴れです。")])
    monkeypatch.setattr(main, "_get_provider", lambda cfg, name: fake)

    client = TestClient(main.app)
    resp = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "大阪の天気は?"}],
        "execute_tools": True,
        "tools_allowlist": ["get_weather"],
    })
    assert resp.status_code == 200
    events = _events(resp.text)
    types = [e["type"] for e in events]

    # tool 実行結果と round 境界、最終 done が流れていること。
    assert "tool_result" in types
    assert "round_done" in types
    assert types[-1] == "done"

    tool_result = next(e for e in events if e["type"] == "tool_result")
    assert tool_result["ok"] is True
    assert "Osaka" in tool_result["content"]

    done = events[-1]
    assert done["stop_reason"] == "stop"
    assert done["rounds"] == 2
    assert done["final_content"] == "大阪は晴れです。"

    # 往復 2 回 = usage.jsonl に 2 行(per-round 記録)。
    lines = usage_path.read_text().strip().splitlines()
    assert len(lines) == 2
    recs = [json.loads(x) for x in lines]
    # 全レコードが同じ conversation_id を共有する。
    assert len({r["conversation_id"] for r in recs}) == 1
    # 2 ラウンド目は裏トークンが記録されている(エージェント的使用の実測)。
    assert recs[1]["orchestration_input_tokens"] == 40
    assert recs[1]["orchestration_output_tokens"] == 30
