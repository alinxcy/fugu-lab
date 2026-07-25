"""ToolRegistry の単体テスト。握り潰さず ToolResult に落とすことを検証する。"""

from app.tools.builtins import build_registry, get_weather
from app.tools.registry import Tool, ToolRegistry


def _call(name, *, id="c1", arguments=None, arguments_raw="{}",
          arguments_valid=True, arguments_error=None):
    return {
        "index": 0, "id": id, "name": name,
        "arguments_raw": arguments_raw,
        "arguments": {} if arguments is None else arguments,
        "arguments_valid": arguments_valid, "arguments_error": arguments_error,
    }


def test_get_weather_success():
    reg = build_registry()
    res = reg.execute(_call("get_weather", arguments={"city": "Osaka"}))
    assert res.ok is True
    assert "Osaka" in res.content
    assert res.error is None


def test_unknown_tool_is_reported_not_raised():
    reg = build_registry()
    res = reg.execute(_call("does_not_exist"))
    assert res.ok is False
    assert res.error == "unknown_tool"
    assert "does_not_exist" in res.content


def test_not_allowed_tool_blocked():
    # get_weather は登録されているが allowlist から外す。
    reg = build_registry(allowlist=[])
    res = reg.execute(_call("get_weather", arguments={"city": "Osaka"}))
    assert res.ok is False
    assert res.error == "not_allowed"


def test_broken_arguments_are_not_executed():
    reg = build_registry()
    res = reg.execute(_call(
        "get_weather", arguments=None, arguments_raw='{"city": "Os',
        arguments_valid=False, arguments_error="unterminated string",
    ))
    assert res.ok is False
    assert res.error == "invalid_arguments"
    # 生断片を含め、壊れた事実がモデルに返る内容になっている。
    assert "Os" in res.content


def test_execution_error_is_captured():
    def boom(args):
        raise RuntimeError("kaboom")

    reg = ToolRegistry([Tool("boom", "always fails", {"type": "object"}, boom)])
    res = reg.execute(_call("boom"))
    assert res.ok is False
    assert res.error == "execution_error"
    assert "kaboom" in res.content


def test_openai_tools_only_lists_allowlisted():
    reg = build_registry(allowlist=["get_weather"])
    tools = reg.openai_tools()
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "get_weather"
    assert "parameters" in tools[0]["function"]

    assert build_registry(allowlist=[]).openai_tools() == []


def test_get_weather_unknown_city_is_graceful():
    assert "ありません" in get_weather({"city": "Atlantis"})
    assert "指定されていません" in get_weather({})
