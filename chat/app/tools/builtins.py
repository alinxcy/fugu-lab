"""デモ用の組み込みツール(Phase A)。

`get_weather` は fixture(fugu_stream_toolcall_weather.txt)の tool_call に対応する
**決定論的・ネットワーク不要**の実装。目的は「Fugu が tool_call を返す → 実行して
結果を返す → 往復が完了する」仕組みを、外部依存なしで実証・テストできるようにすること。

repo を触る破壊的なツール(read/write/bash)は Phase B で別モジュールに置き、
allowlist で明示オプトインする(既定オフ)。ここには入れない。
"""

from __future__ import annotations

from typing import Any

from app.tools.registry import Tool, ToolRegistry

# 決定論的なダミー気象データ(実運用では外部 API に置き換える。デモ/テストは固定値)。
_CANNED_WEATHER = {
    "osaka": "晴れ, 28°C, 湿度 60%",
    "tokyo": "曇り, 25°C, 湿度 70%",
    "sapporo": "雨, 19°C, 湿度 85%",
}


def get_weather(args: dict[str, Any]) -> str:
    """指定都市の(ダミー)天気を返す。未知都市でも例外を投げず不明として返す。"""
    city = str(args.get("city", "")).strip()
    if not city:
        return "city が指定されていません。"
    weather = _CANNED_WEATHER.get(city.lower())
    if weather is None:
        return f"{city} の天気データはありません(デモは Osaka/Tokyo/Sapporo のみ)。"
    return f"{city}: {weather}"


GET_WEATHER = Tool(
    name="get_weather",
    description="指定した都市の現在の天気を返す(デモ実装・固定値)。",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "都市名(例: Osaka)"},
        },
        "required": ["city"],
    },
    func=get_weather,
)

# Phase A のデフォルト登録ツール一覧。
DEFAULT_TOOLS: list[Tool] = [GET_WEATHER]


def build_registry(allowlist: list[str] | None = None) -> ToolRegistry:
    """既定ツールでレジストリを組む。allowlist=None は既定ツール全許可。"""
    return ToolRegistry(DEFAULT_TOOLS, allowlist=allowlist)
