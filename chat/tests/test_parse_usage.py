"""parse_usage の単体テスト(ネットワーク不要・実 fixture ベース)。"""
import json
from pathlib import Path

from app.usage.assemble import parse_usage

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_usage_from_real_nonstream_response():
    resp = json.loads((FIXTURES / "fugu_nonstream_hi.json").read_text())
    fields = parse_usage(resp["usage"])
    assert fields["input_tokens"] == 99
    assert fields["output_tokens"] == 18
    assert fields["cached_tokens"] == 0
    # orchestration_* は *_details にネストしている。正しく拾えること。
    assert fields["orchestration_input_tokens"] == 0
    assert fields["orchestration_output_tokens"] == 0


def test_parse_usage_none_returns_all_none():
    fields = parse_usage(None)
    assert set(fields.values()) == {None}


def test_parse_usage_distinguishes_null_from_zero():
    # cached は 0、orchestration_input はキー自体が無い(=不明=None)
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {},
    }
    fields = parse_usage(usage)
    assert fields["cached_tokens"] == 0            # 0 は 0
    assert fields["orchestration_input_tokens"] is None   # 欠損は None(0で埋めない)
    assert fields["orchestration_output_tokens"] is None


def test_parse_usage_missing_details_object():
    usage = {"prompt_tokens": 3, "completion_tokens": 4}
    fields = parse_usage(usage)
    assert fields["input_tokens"] == 3
    assert fields["output_tokens"] == 4
    assert fields["cached_tokens"] is None
