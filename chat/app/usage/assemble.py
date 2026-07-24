"""ストリーミングのチャンク列から usage / tool_call / content を組み立てる。

このモジュールが本アプリで最も壊してはいけない箇所(schema/usage-record.md「テスト要件」)。
ネットワーク不要で単体テストできるよう、副作用を持たない純粋なロジックに保つこと。

守っている譲れない要件:
  - チャンクの content 以外を破棄しない。usage は choices が空の最終チャンクに載る。
  - tool_call の arguments は複数チャンクに分割されて届くので index ごとに連結する。
  - arguments JSON は「全断片を連結してから」パースする。途中でパースしない。
  - 壊れた arguments はエラーとして保持・可視化する(握り潰さない)。
"""
from __future__ import annotations

import json
from typing import Any, Optional


def parse_usage(usage: Optional[dict[str, Any]]) -> dict[str, Optional[int]]:
    """Fugu(OpenAI 互換)の usage オブジェクトを UsageRecord のトークン系フィールドに正規化。

    null と 0 を区別する: キーが無ければ None、0 が入っていれば 0。
    orchestration_* は *_details の中にネストしている(実測で確認)。
    マッピングできない未知フィールドは呼び出し側が raw_usage に丸ごと残すことで救済する。
    """
    keys = [
        "input_tokens",
        "output_tokens",
        "cached_tokens",
        "orchestration_input_tokens",
        "orchestration_output_tokens",
    ]
    if not isinstance(usage, dict):
        return {k: None for k in keys}

    def get(*path: str) -> Optional[int]:
        cur: Any = usage
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return None
            cur = cur[k]
        return cur

    return {
        "input_tokens": get("prompt_tokens"),
        "output_tokens": get("completion_tokens"),
        "cached_tokens": get("prompt_tokens_details", "cached_tokens"),
        "orchestration_input_tokens": get("prompt_tokens_details", "orchestration_input_tokens"),
        "orchestration_output_tokens": get("completion_tokens_details", "orchestration_output_tokens"),
    }


class StreamAssembler:
    """SSE のチャンク(パース済み dict)を順に食わせ、最後に組み上がった結果を取り出す。

    使い方:
        asm = StreamAssembler()
        for chunk in chunks:      # chunk は json.loads 済みの dict
            asm.add_chunk(chunk)
        asm.content               # 連結された本文
        asm.raw_usage             # usage オブジェクト(無いなら None)
        asm.tool_calls()          # 組み上がった tool_call のリスト
        asm.raw_chunks            # 生チャンク(ログ保存用。捨てない)
    """

    def __init__(self) -> None:
        self._content_parts: list[str] = []
        # index -> {"id": str|None, "name": str|None, "arg_parts": [str]}
        self._tool_calls: dict[int, dict[str, Any]] = {}
        self.raw_usage: Optional[dict[str, Any]] = None
        self.finish_reason: Optional[str] = None
        self.raw_chunks: list[dict[str, Any]] = []

    def add_chunk(self, chunk: dict[str, Any]) -> None:
        # 生チャンクは必ず保持する(content 以外を捨てない)
        self.raw_chunks.append(chunk)

        # usage は choices が空([])の最終チャンクに載ることがある。choices を見る前に拾う。
        if chunk.get("usage") is not None:
            self.raw_usage = chunk["usage"]

        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}

            content = delta.get("content")
            if content:
                self._content_parts.append(content)

            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = self._tool_calls.setdefault(
                    idx, {"id": None, "name": None, "arg_parts": []}
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                # arguments は "" の断片も来るが連結には影響しない
                if fn.get("arguments"):
                    slot["arg_parts"].append(fn["arguments"])

            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]

    @property
    def content(self) -> str:
        return "".join(self._content_parts)

    def usage_fields(self) -> dict[str, Optional[int]]:
        """UsageRecord 用に正規化した usage(null/0 区別つき)。"""
        return parse_usage(self.raw_usage)

    def tool_calls(self) -> list[dict[str, Any]]:
        """組み上がった tool_call のリスト。

        arguments は全断片を連結してから 1 度だけパースする。壊れていたら
        arguments_valid=False と arguments_error を立てて握り潰さない。
        """
        result: list[dict[str, Any]] = []
        for idx in sorted(self._tool_calls):
            slot = self._tool_calls[idx]
            raw_args = "".join(slot["arg_parts"])
            parsed: Optional[Any] = None
            valid = True
            err: Optional[str] = None
            if raw_args == "":
                # 引数なしの関数呼び出し(空)。壊れているわけではない。
                parsed = {}
            else:
                try:
                    parsed = json.loads(raw_args)
                except json.JSONDecodeError as e:
                    valid = False
                    err = f"{e.msg} (pos {e.pos})"
            result.append(
                {
                    "index": idx,
                    "id": slot["id"],
                    "name": slot["name"],
                    "arguments_raw": raw_args,
                    "arguments": parsed,
                    "arguments_valid": valid,
                    "arguments_error": err,
                }
            )
        return result


def iter_sse_data(raw: str):
    """生の SSE テキストから `data:` 行の JSON を順に yield する(テスト/ログ用ヘルパ)。

    `data: [DONE]` は終端として読み飛ばす。空行は無視。
    """
    for line in raw.splitlines():
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        yield json.loads(payload)
