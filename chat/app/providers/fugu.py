"""fugu adapter — Sakana Fugu の OpenAI 互換エンドポイント。

実測で確認した挙動:
  - usage は stream_options.include_usage:true を送ると最終チャンク(choices:[])に載る。
  - orchestration_* は usage.*_details の中にネスト → base の既定 parse_usage で拾える。
  - エラーは {"error": {"message","type","request_id"}} 形式。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

import httpx

from app.providers.base import Provider, ProviderError


class FuguProvider(Provider):
    name = "fugu"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str,
        params: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[dict[str, Any]]:
        params = dict(params or {})
        # tools / tool_choice / max_tokens 等は params からそのまま素通しする(観測のみ)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            # これが無いとストリームに usage が載らない(このアプリの存在意義に直結)
            "stream_options": {"include_usage": True},
            **params,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        # httpx の timeout: 接続は短く、読み取り(生成待ち)は長く。ttft/elapsed は上位で計測。
        timeout = httpx.Timeout(self.timeout_s, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raw = _safe_json(body)
                    msg = _extract_error_message(raw, body)
                    raise ProviderError(msg, status=resp.status_code, raw=raw)

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        # 壊れた SSE 行は握り潰さず、その事実を chunk として流す
                        yield {"_parse_error": True, "_raw_line": data}


def _safe_json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except Exception:
        return None


def _extract_error_message(raw: Any, body: bytes) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("error"), dict):
        err = raw["error"]
        parts = [err.get("message") or "unknown error"]
        if err.get("type"):
            parts.append(f"type={err['type']}")
        if err.get("request_id"):
            parts.append(f"request_id={err['request_id']}")
        return " | ".join(parts)
    text = body.decode("utf-8", errors="replace")[:500]
    return text or "unknown provider error"
