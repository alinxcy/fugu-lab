"""ツールレジストリ — tool_call を実際に実行する層(Phase 2)。

設計方針:
- **握り潰さない**(schema/SPEC 要件): 未知ツール・不許可・引数 JSON 破損・実行時例外の
  いずれも、例外を上に投げず ToolResult(ok=False) に落として「何が起きたか」をモデルに
  返す。測定中にアプリを落とさないため、かつ壊れ方こそが判断材料のため。
- **allowlist**: 実行してよいツールは設定で明示したものだけ。既定オフ運用を可能にする
  (repo を触る破壊的ツールを Phase B で足すときの安全弁)。
- 純粋・ネットワーク不要でテストできること(実行関数の副作用はツール実装側の責務)。

`execute` が受け取る call は StreamAssembler.tool_calls() の 1 要素:
    {"index","id","name","arguments_raw","arguments","arguments_valid","arguments_error"}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Tool:
    """1 つのツール定義。`func` は引数 dict を受け取り、文字列(モデルに返す内容)を返す。"""

    name: str
    description: str
    parameters: dict[str, Any]          # JSON Schema(OpenAI tools の function.parameters)
    func: Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolResult:
    """ツール実行の結果。`content` は role:"tool" メッセージとしてモデルに返す本文。

    ok=False でも content には理由を入れる(モデルが次ラウンドで修正できるように)。
    """

    tool_call_id: Optional[str]
    name: Optional[str]
    ok: bool
    content: str
    error: Optional[str] = None


class ToolRegistry:
    """名前 → Tool の対応と allowlist を保持し、tool_call を安全に実行する。"""

    def __init__(self, tools: list[Tool], allowlist: Optional[list[str]] = None) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        # allowlist=None は「登録済み全部を許可」。空リストは「全部不許可」を意味する。
        self._allowlist: set[str] = (
            set(self._tools) if allowlist is None else set(allowlist)
        )

    def is_allowed(self, name: str) -> bool:
        return name in self._tools and name in self._allowlist

    def openai_tools(self) -> list[dict[str, Any]]:
        """リクエストの `tools` パラメータに載せる形(allowlist のもののみ)。"""
        out: list[dict[str, Any]] = []
        for name in sorted(self._allowlist):
            tool = self._tools.get(name)
            if tool is None:
                continue
            out.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })
        return out

    def execute(self, call: dict[str, Any]) -> ToolResult:
        """組み上がった tool_call を実行する。例外は投げず ToolResult に落とす。"""
        name = call.get("name")
        call_id = call.get("id")

        if not name or name not in self._tools:
            return ToolResult(call_id, name, False,
                              f"unknown tool: {name!r}", error="unknown_tool")

        if name not in self._allowlist:
            return ToolResult(call_id, name, False,
                              f"tool not allowed: {name!r}", error="not_allowed")

        # 引数 JSON が壊れて返っていたら実行しない。壊れた事実をモデルに返す(握り潰さない)。
        if not call.get("arguments_valid", False):
            err = call.get("arguments_error") or "arguments were not valid JSON"
            return ToolResult(
                call_id, name, False,
                f"invalid tool arguments: {err}. raw={call.get('arguments_raw')!r}",
                error="invalid_arguments",
            )

        args = call.get("arguments")
        if not isinstance(args, dict):
            return ToolResult(call_id, name, False,
                              f"arguments must be a JSON object, got {type(args).__name__}",
                              error="invalid_arguments")

        try:
            content = self._tools[name].func(args)
        except Exception as exc:  # noqa: BLE001 — 実行時失敗も測定を止めず記録する
            return ToolResult(call_id, name, False,
                              f"tool execution failed: {type(exc).__name__}: {exc}",
                              error="execution_error")

        return ToolResult(call_id, name, True, str(content))
