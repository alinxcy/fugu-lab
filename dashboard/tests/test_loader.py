"""loader.py の単体テスト。壊れ行スキップと末尾差分読み。"""

from pathlib import Path

from dashboard.core.loader import load_file, load_files

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ANOMALIES = FIXTURES / "anomalies.jsonl"


def test_broken_lines_are_skipped_not_fatal():
    """壊れた行(不正 JSON / 必須欠落)はスキップし、正常行は読める。落ちない。"""
    result = load_file(str(ANOMALIES))
    ids = [r.id for r in result.records]
    assert ids == ["ok1", "ok2", "orch_unknown", "failed"]
    # 「json でない行」と「必須欠落行」の 2 件がスキップされる。
    assert result.skipped_count == 2
    reasons = " ".join(s.reason for s in result.skipped)
    assert "JSON パース失敗" in reasons
    assert "スキーマ不正" in reasons


def test_skipped_line_numbers_are_reported():
    """スキップ行には行番号が付く(UI で位置を示せる)。"""
    result = load_file(str(ANOMALIES))
    line_nos = sorted(s.line_no for s in result.skipped)
    assert line_nos == [2, 3]      # 2行目=非JSON, 3行目=必須欠落


def test_missing_file_returns_empty():
    """ファイルが無い(まだ 1 件も測定していない)状態は正常。空を返す。"""
    result = load_file(str(FIXTURES / "does_not_exist.jsonl"))
    assert result.records == []
    assert result.skipped == []


def test_tail_incremental_reads_only_appended(tmp_path):
    """末尾差分: 前回 offset 以降だけを読む。既存行を再読み込みしない。"""
    path = tmp_path / "usage.jsonl"
    line1 = (
        '{"id": "a", "timestamp": "2026-07-24T10:00:00+00:00", "provider": "fugu",'
        ' "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,'
        ' "input_tokens": 1, "output_tokens": 1, "raw_usage": {}, "error": null}\n'
    )
    line2 = (
        '{"id": "b", "timestamp": "2026-07-24T11:00:00+00:00", "provider": "fugu",'
        ' "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,'
        ' "input_tokens": 1, "output_tokens": 1, "raw_usage": {}, "error": null}\n'
    )
    path.write_text(line1, encoding="utf-8")
    first = load_file(str(path))
    assert [r.id for r in first.records] == ["a"]

    # 追記してから、前回の offset/line_no を渡して増分読み。
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line2)
    second = load_file(str(path), since_offset=first.offset, start_line_no=first.next_line_no)
    assert [r.id for r in second.records] == ["b"]     # a は再読み込みされない
    assert second.records[0].id == "b"


def test_partial_last_line_is_held_until_complete(tmp_path):
    """改行で終わっていない最終行(書き込み途中)は読まず、次回に持ち越す。"""
    path = tmp_path / "usage.jsonl"
    full = (
        '{"id": "a", "timestamp": "2026-07-24T10:00:00+00:00", "provider": "fugu",'
        ' "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,'
        ' "input_tokens": 1, "output_tokens": 1, "raw_usage": {}, "error": null}\n'
    )
    partial = '{"id": "b", "timestamp": "2026-07-24T11:00:00+00:00", "prov'
    path.write_text(full + partial, encoding="utf-8")

    first = load_file(str(path))
    assert [r.id for r in first.records] == ["a"]      # b はまだ読まない

    # b の残りが書き込まれたら、次の増分で完全な行として読める。
    rest = (
        'ider": "fugu", "model": "fugu", "conversation_id": "c", "ttft_s": 1.0,'
        ' "elapsed_s": 1.0, "input_tokens": 1, "output_tokens": 1, "raw_usage": {},'
        ' "error": null}\n'
    )
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(rest)
    second = load_file(str(path), since_offset=first.offset, start_line_no=first.next_line_no)
    assert [r.id for r in second.records] == ["b"]


def test_truncated_file_restarts_from_head(tmp_path):
    """ファイルが縮んだら(ローテーション)頭から読み直す。"""
    path = tmp_path / "usage.jsonl"
    line = (
        '{"id": "a", "timestamp": "2026-07-24T10:00:00+00:00", "provider": "fugu",'
        ' "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,'
        ' "input_tokens": 1, "output_tokens": 1, "raw_usage": {}, "error": null}\n'
    )
    path.write_text(line + line, encoding="utf-8")
    first = load_file(str(path))
    assert first.ok_count == 2

    path.write_text(line, encoding="utf-8")   # 縮んだ
    reread = load_file(str(path), since_offset=first.offset)
    assert reread.ok_count == 1               # since_offset > size を検知して頭から


def test_load_files_batch_continues_line_numbers(tmp_path):
    """複数ファイル(バッチ)を通し行番号で読む。"""
    p1 = tmp_path / "a.jsonl"
    p2 = tmp_path / "b.jsonl"
    rec = (
        '{{"id": "{id}", "timestamp": "2026-07-24T10:00:00+00:00", "provider": "fugu",'
        ' "model": "fugu", "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 1.0,'
        ' "input_tokens": 1, "output_tokens": 1, "raw_usage": {{}}, "error": null}}\n'
    )
    p1.write_text(rec.format(id="a"), encoding="utf-8")
    p2.write_text(rec.format(id="b"), encoding="utf-8")
    result = load_files([str(p1), str(p2)])
    assert [r.id for r in result.records] == ["a", "b"]
