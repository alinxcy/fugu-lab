"""app.py のスモークテスト(Streamlit AppTest)。

UI ロジックが例外なく描画されること、ライブの末尾差分蓄積が効くことを、
ブラウザ無しで検証する。集計の正しさは test_metrics.py が担保するので、
ここは「落ちない・つながる」ことの確認に絞る。

ライブの自動更新ループ(time.sleep+st.rerun)は FUGU_DASH_TEST=1 で無効化する。
"""

import os
from pathlib import Path

import pytest

os.environ["FUGU_DASH_TEST"] = "1"

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app.py")

_REC = (
    '{{"id": "{id}", "timestamp": "{ts}", "provider": "fugu", "model": "fugu",'
    ' "conversation_id": "c", "ttft_s": 1.0, "elapsed_s": 2.0, "input_tokens": 10,'
    ' "output_tokens": 20, "cached_tokens": 0, "orchestration_input_tokens": 5,'
    ' "orchestration_output_tokens": 5, "raw_usage": {{"prompt_tokens": 10}},'
    ' "error": null}}\n'
)


def test_live_empty_renders_without_exception():
    """既定(ライブ・ファイル未作成=空)でも落ちず、案内を出す。"""
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert at.exception == []


def test_batch_sample_renders_all_sections():
    """バッチ + 実サンプルで 4 セクションが例外なく描画される。"""
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.radio[0].set_value("バッチ").run()
    assert at.exception == []
    headers = [h.value for h in at.header]
    assert any("消費サマリ" in h for h in headers)
    assert any("オーバーヘッド" in h for h in headers)
    assert any("枠フィット" in h for h in headers)
    assert any("レイテンシ" in h for h in headers)
    # 薄いサンプルなので外挿警告(st.error)が必ず出ている。
    assert len(at.error) >= 1


def test_live_tail_diff_accumulates(tmp_path):
    """追記を検知して末尾差分だけ読み、蓄積が増える(全体再読み込みしない)。"""
    path = tmp_path / "usage.jsonl"
    path.write_text(_REC.format(id="r1", ts="2026-07-25T01:00:00+00:00"), encoding="utf-8")

    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].set_value(str(path)).run()
    assert len(at.session_state["live_records"]) == 1

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(_REC.format(id="r2", ts="2026-07-25T02:00:00+00:00"))
    at.run()
    assert [r.id for r in at.session_state["live_records"]] == ["r1", "r2"]
    assert at.exception == []
