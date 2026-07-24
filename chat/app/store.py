"""Store — 会話/usage/生ログのローカル永続化。

UsageRecord の JSONL は追記専用(schema/usage-record.md 要件):
  - 既存行を書き換えない。途中で壊れても既存レコードを失わない。
  - dashboard 側は末尾差分だけを読むので、追記以外の操作をしない。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with _lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()


def append_usage(path: Path, record: dict[str, Any]) -> None:
    """UsageRecord を 1 行追記する。"""
    _append_jsonl(path, record)


def append_raw_log(path: Path, entry: dict[str, Any]) -> None:
    """リクエスト/レスポンスの生ログを 1 行追記する(デバッグ・後分析用)。"""
    _append_jsonl(path, entry)
