"""JSONL の読み込み。壊れた行をスキップし、追記分だけを増分で読む。

要件(dashboard/SPEC.md・PROMPT.md):
- **入力の堅牢性**: 壊れた行・欠損・想定外フィールドでもクラッシュせず、
  スキップした事実を呼び出し側に返す(測定中に落ちるのが最悪)。
- **ライブ更新は末尾差分だけ読む**: 追記専用ファイルなので、前回読んだ
  バイトオフセット以降だけを読む(全体再読み込みしない)。
- パスは呼び出し側(設定)から渡す。相対パス決め打ちにしない。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .record import RecordError, UsageRecord, parse_record


@dataclass(frozen=True)
class SkippedLine:
    """スキップした行の記録。UI で「N 行スキップ」を可視化するために返す。"""

    line_no: int          # ファイル先頭からの 1 始まり行番号(概算・増分読み込み時は通し番号)
    reason: str           # なぜスキップしたか(JSON 不正 / スキーマ不正)
    raw: str              # 元テキスト(先頭のみ・デバッグ用)


@dataclass(frozen=True)
class LoadResult:
    """1 回の読み込み結果。"""

    records: list[UsageRecord]
    skipped: list[SkippedLine]
    offset: int           # 次回の増分読み込みで使う、読み終えたバイトオフセット
    next_line_no: int     # 次回に振る行番号(通し番号を継続させるため)

    @property
    def ok_count(self) -> int:
        return len(self.records)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def _parse_lines(
    lines: list[str], start_line_no: int
) -> tuple[list[UsageRecord], list[SkippedLine], int]:
    """テキスト行のリストをパースする。壊れた行は SkippedLine に落とす。"""
    records: list[UsageRecord] = []
    skipped: list[SkippedLine] = []
    line_no = start_line_no
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            # 空行は「壊れ」ではないので静かに飛ばす(行番号だけ進める)。
            line_no += 1
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            skipped.append(SkippedLine(line_no, f"JSON パース失敗: {exc}", stripped[:200]))
            line_no += 1
            continue
        try:
            records.append(parse_record(obj))
        except RecordError as exc:
            skipped.append(SkippedLine(line_no, f"スキーマ不正: {exc}", stripped[:200]))
        line_no += 1
    return records, skipped, line_no


def load_file(path: str, *, since_offset: int = 0, start_line_no: int = 1) -> LoadResult:
    """1 ファイルを読む。``since_offset`` を渡すとそのバイト位置以降(追記分)だけを読む。

    ライブ更新では、前回の :attr:`LoadResult.offset` と
    :attr:`LoadResult.next_line_no` をそのまま渡せば、末尾差分だけを増分で読める。

    ファイルが存在しない場合は空の結果を返す(まだ 1 件も測定していない状態=正常)。
    途中で切れた最終行(改行で終わっていない=書き込み途中)は**読まずに残し**、
    offset を進めないことで、次回に完全な行として読み直せるようにする。
    """
    if not os.path.exists(path):
        return LoadResult([], [], since_offset, start_line_no)

    size = os.path.getsize(path)
    if since_offset > size:
        # ファイルが縮んだ = ローテーション/切り詰め。頭から読み直す。
        since_offset = 0
        start_line_no = 1

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        fh.seek(since_offset)
        chunk = fh.read()

    if not chunk:
        return LoadResult([], [], since_offset, start_line_no)

    # 最後が改行で終わっていなければ、最終行は書き込み途中の可能性がある。
    # その行はこの回では処理せず、offset を「最後の改行の直後」までしか進めない。
    last_newline = chunk.rfind("\n")
    if last_newline == -1:
        # 完結した行が 1 つも無い(部分行のみ)。次回に持ち越す。
        return LoadResult([], [], since_offset, start_line_no)

    complete = chunk[: last_newline + 1]
    consumed_bytes = len(complete.encode("utf-8"))
    new_offset = since_offset + consumed_bytes

    lines = complete.splitlines()
    records, skipped, next_line_no = _parse_lines(lines, start_line_no)
    return LoadResult(records, skipped, new_offset, next_line_no)


def load_files(paths: list[str]) -> LoadResult:
    """複数ファイルをまとめて読む(バッチモード)。行番号は通しで振る。"""
    all_records: list[UsageRecord] = []
    all_skipped: list[SkippedLine] = []
    line_no = 1
    last_offset = 0
    for path in paths:
        result = load_file(path, since_offset=0, start_line_no=line_no)
        all_records.extend(result.records)
        all_skipped.extend(result.skipped)
        line_no = result.next_line_no
        last_offset = result.offset
    return LoadResult(all_records, all_skipped, last_offset, line_no)
