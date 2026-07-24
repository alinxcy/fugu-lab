"""Fugu 使用データ ダッシュボード(Streamlit)。

表示層。集計ロジックは持たず ``core`` を呼ぶだけ(結合点は JSONL スキーマのみ)。

このアプリの最重要目的は「綺麗なグラフ」ではなく、
**薄いサンプルから誤った確信を生まないこと**。ゆえに:
- どの数字にも「何件・何日から」を添える
- 月間推定は点でなく幅で出し、薄いときは警告を強調する
- 「契約しない」を 3 択の第一級の結論として提示する

起動:  cd dashboard && streamlit run app.py
"""

from __future__ import annotations

import os
import time

import pandas as pd
import streamlit as st

# ライブの自動更新は time.sleep + st.rerun のループで実現する(追加依存なし)。
# テスト/CI ではこのループがあると script が終わらないので、環境変数で無効化できる。
_AUTO_LOOP_ENABLED = os.environ.get("FUGU_DASH_TEST") != "1"

from core.config import Settings, load_settings
from core.loader import load_file, load_files
from core.metrics import (
    analyze_latency,
    analyze_overhead,
    collect_unknown_raw_keys,
    group_by_day,
    observed_days,
    project_monthly,
    summarize_tokens,
)

st.set_page_config(page_title="Fugu 契約判断ダッシュボード", layout="wide")


# ---------------------------------------------------------------------------
# データ読み込み(ライブは末尾差分を session_state に蓄積)
# ---------------------------------------------------------------------------

def _reset_live_state():
    st.session_state.live_records = []
    st.session_state.live_skipped = []
    st.session_state.live_offset = 0
    st.session_state.live_line_no = 1


def load_live(path: str):
    """前回オフセット以降(追記分)だけを読み、蓄積に足す。"""
    if "live_records" not in st.session_state:
        _reset_live_state()
    result = load_file(
        path,
        since_offset=st.session_state.live_offset,
        start_line_no=st.session_state.live_line_no,
    )
    st.session_state.live_records.extend(result.records)
    st.session_state.live_skipped.extend(result.skipped)
    st.session_state.live_offset = result.offset
    st.session_state.live_line_no = result.next_line_no
    return st.session_state.live_records, st.session_state.live_skipped


# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------

settings: Settings = load_settings()

st.sidebar.title("⚙️ 設定")
mode = st.sidebar.radio("読み込みモード", ["ライブ", "バッチ"], index=0,
                        help="ライブ=追記を監視して末尾差分だけ読む / バッチ=指定ファイルを読む")

if mode == "ライブ":
    live_path = st.sidebar.text_input("入力 JSONL", value=settings.resolve(settings.live_path))
    auto = st.sidebar.checkbox("自動更新", value=True)
    interval = st.sidebar.slider("更新間隔(秒)", 2, 30, 3, disabled=not auto)
    col_a, col_b = st.sidebar.columns(2)
    if col_a.button("いま更新", width="stretch"):
        pass  # 再実行で末尾差分を読む
    if col_b.button("最初から読み直す", width="stretch"):
        _reset_live_state()
    st.sidebar.caption(f"開発用サンプル: `{settings.resolve(settings.sample_path)}`")
    records, skipped = load_live(live_path)
    source_label = f"ライブ: `{live_path}`"
else:
    default_batch = settings.resolve(settings.sample_path)
    paths_text = st.sidebar.text_area(
        "入力 JSONL(複数可・1 行 1 パス)", value=default_batch, height=100)
    paths = [p.strip() for p in paths_text.splitlines() if p.strip()]
    resolved = [settings.resolve(p) for p in paths]
    result = load_files(resolved)
    records, skipped = result.records, result.skipped
    auto = False
    interval = 0
    source_label = "バッチ: " + ", ".join(f"`{p}`" for p in paths)

st.sidebar.divider()
st.sidebar.caption(f"レート設定: `config/{settings.source_file}`")
if settings.rates_are_placeholder:
    st.sidebar.warning("レートがプレースホルダ(全 0)です。コスト換算は無効。"
                       "`config/rates.toml` に実レートを入れてください。")


# ---------------------------------------------------------------------------
# ヘッダと但し書き
# ---------------------------------------------------------------------------

st.title("🐡 Fugu 契約判断ダッシュボード")
st.caption(source_label)

st.info(
    "**このダッシュボードは 3 つの結論を等しく出せるように作られています: "
    "① Standard で足りる / ② Pro・Max が要る / ③ そもそも契約しない。** "
    "測定窓は金・土の 2 日だけ。数字は薄いサンプルからの外挿です。"
    "コスト表示は「正確な請求額」ではなく**相対的な重さの指標**として見てください。",
    icon="🧭",
)

if not records:
    st.warning("まだ有効なレコードがありません。チャットアプリで会話すると数字が伸びていきます。")
    if auto and _AUTO_LOOP_ENABLED:
        time.sleep(interval)
        st.rerun()
    st.stop()


# ---------------------------------------------------------------------------
# データ健全性ストリップ(サンプル数を常に可視化)
# ---------------------------------------------------------------------------

summary = summarize_tokens(records)
days = observed_days(records)
unknown_keys = collect_unknown_raw_keys(records)

h1, h2, h3, h4 = st.columns(4)
h1.metric("読み込み件数", summary.request_count)
h2.metric("測定日数", days)
h3.metric("スキップ行", len(skipped), help="壊れた/欠損した行。集計から除外済み")
h4.metric("未知フィールド", len(unknown_keys), help="raw_usage に現れたスキーマ外キー")

if skipped:
    with st.expander(f"⚠️ スキップした {len(skipped)} 行の内訳(クラッシュせず除外しました)"):
        st.dataframe(pd.DataFrame(
            [{"行": s.line_no, "理由": s.reason, "内容(先頭)": s.raw} for s in skipped]),
            width="stretch", hide_index=True)

if unknown_keys:
    st.warning(
        "raw_usage にスキーマ未定義のフィールドが出現しています(プロバイダ仕様変更の兆候かも): "
        + ", ".join(f"`{k}`×{c}" for k, c in unknown_keys.items()),
        icon="🔎",
    )

st.divider()


# ---------------------------------------------------------------------------
# 1. 消費サマリ
# ---------------------------------------------------------------------------

st.header("1. 消費サマリ")
st.caption(f"{summary.request_count} 件 / {days} 日から算出")

c1, c2, c3, c4 = st.columns(4)
c1.metric("成功 / 失敗", f"{summary.success_count} / {summary.error_count}")
c2.metric("表トークン(in+out)", f"{summary.visible_tokens:,}")
orch_label = f"{summary.orchestration_tokens:,}"
if summary.orchestration_unknown_count:
    orch_label += f"  (不明 {summary.orchestration_unknown_count} 件)"
c3.metric("裏トークン(orchestration)", orch_label,
          help="裏が不明(null)のレコードは合計から除外し件数で表示。0 とは区別しています。")
c4.metric("課金トークン総計", f"{summary.billed_tokens:,}",
          help="表 + 裏。裏は表の部分集合ではなく追加課金。")

# 日別内訳
day_rows = []
for day, day_recs in group_by_day(records).items():
    ds = summarize_tokens(day_recs)
    day_rows.append({
        "日付(UTC)": day,
        "件数": ds.request_count,
        "失敗": ds.error_count,
        "表": ds.visible_tokens,
        "裏": ds.orchestration_tokens,
        "裏不明": ds.orchestration_unknown_count,
        "cached": ds.cached_tokens,
        "課金総計": ds.billed_tokens,
    })
day_df = pd.DataFrame(day_rows)
st.dataframe(day_df, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# 2. オーバーヘッド分析(中心指標)
# ---------------------------------------------------------------------------

st.header("2. オーバーヘッド分析 — 裏トークン比率(中心指標)")
overhead = analyze_overhead(records)

st.caption(
    f"裏が取得できた {overhead.counted_requests} 件で算出"
    + (f" / 裏不明で除外 {overhead.unknown_requests} 件" if overhead.unknown_requests else "")
)

if overhead.overall_ratio is None:
    st.warning("裏トークンが取得できたレコードがありません。オーバーヘッドを評価できません。")
else:
    o1, o2, o3, o4 = st.columns(4)
    o1.metric("全体の裏率", f"{overhead.overall_ratio:.0%}",
              help="合計裏 / 合計課金。支払いのうち自分に見えない処理に消えた割合。")
    o2.metric("中央値(リクエスト単位)", f"{overhead.median_ratio:.0%}")
    o3.metric("最小", f"{overhead.min_ratio:.0%}")
    o4.metric("最大", f"{overhead.max_ratio:.0%}")

    st.markdown(
        "> **判断への接続**: この割合が高いほど、支払いの多くが見えない処理に消えています。"
        "許容できない水準なら、プラン選択以前に **③「契約しない」が結論**になりえます。"
    )

    # リクエスト単位の分布(ばらつきを隠さない)
    ratio_df = pd.DataFrame({
        "リクエスト": [f"#{i+1}" for i in range(len(overhead.per_request_ratios))],
        "裏率": list(overhead.per_request_ratios),
    })
    dist_col, ts_col = st.columns(2)
    with dist_col:
        st.caption("リクエスト単位の裏率(ばらつき)")
        st.bar_chart(ratio_df.set_index("リクエスト"), y="裏率")
    with ts_col:
        st.caption("裏率の時系列(使い方で変動するか)")
        ts_rows = []
        for r in records:
            if r.orchestration_ratio is not None:
                ts_rows.append({"timestamp": r.timestamp, "裏率": r.orchestration_ratio,
                                "model": r.model})
        if ts_rows:
            ts_df = pd.DataFrame(ts_rows)
            ts_df["timestamp"] = pd.to_datetime(ts_df["timestamp"])
            st.line_chart(ts_df.set_index("timestamp"), y="裏率")

    # 種類別(モデル別)傾向 — 軽い質問ほど比率が悪化するなら常用に致命的
    model_rows = []
    by_model: dict[str, list] = {}
    for r in records:
        by_model.setdefault(r.model, []).append(r)
    for model, recs in sorted(by_model.items()):
        mo = analyze_overhead(recs)
        model_rows.append({
            "model": model,
            "件数": len(recs),
            "裏率(全体)": None if mo.overall_ratio is None else round(mo.overall_ratio, 3),
            "裏不明": mo.unknown_requests,
        })
    st.caption("モデル別の裏率傾向(参考)")
    st.dataframe(pd.DataFrame(model_rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# 3. 枠フィット推定(外挿・幅・警告を必須併記)
# ---------------------------------------------------------------------------

st.header("3. 枠フィット推定(月間外挿)")

rates = settings.rates
proj = project_monthly(
    records,
    input_rate=None if rates.all_zero else rates.input,
    output_rate=None if rates.all_zero else rates.output,
    orchestration_input_rate=None if rates.all_zero else rates.orchestration_input,
    orchestration_output_rate=None if rates.all_zero else rates.orchestration_output,
)

st.caption(f"根拠: {proj.sample_requests} 件 / {proj.sample_days} 日の実測からの外挿")

if proj.is_thin:
    st.error(
        "⚠️ **サンプルが薄いため、これは点推定ではなく外挿の帯です。**"
        "自信ありげな 1 つの数字として受け取らないでください。",
        icon="⚠️",
    )
for w in proj.warnings:
    st.warning(w)

p1, p2, p3 = st.columns(3)
p1.metric("月間 課金トークン(軽め)", f"{proj.monthly_billed_low:,.0f}")
p2.metric("月間 課金トークン(現ペース)", f"{proj.monthly_billed_point:,.0f}")
p3.metric("月間 課金トークン(ヘビー)", f"{proj.monthly_billed_high:,.0f}")

if proj.monthly_cost_point is not None:
    st.subheader("月間コスト(相対指標・幅)")
    st.caption("※ 正確な請求額ではありません。設定レートによる相対的な重さの目安です。")
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("軽め", f"{proj.monthly_cost_low:,.1f}")
    cc2.metric("現ペース", f"{proj.monthly_cost_point:,.1f}")
    cc3.metric("ヘビー", f"{proj.monthly_cost_high:,.1f}")

    if settings.plans:
        st.caption("プラン月額との対比(「契約しない」も含めて判断する)")
        plan_rows = []
        for plan in settings.plans:
            verdict = "帯が収まる" if proj.monthly_cost_high <= plan.price else (
                "現ペースは収まる" if proj.monthly_cost_point <= plan.price else "超過しうる")
            plan_rows.append({"プラン": plan.name, "月額": plan.price, "対比": verdict})
        st.dataframe(pd.DataFrame(plan_rows), width="stretch", hide_index=True)
else:
    st.info("レート未設定のため、月間コストは算出していません(トークン量のみ外挿)。"
            "`config/rates.toml` に実レートを入れると相対コストが出ます。")


# ---------------------------------------------------------------------------
# 4. レイテンシ分析(ttft と elapsed を分けて)
# ---------------------------------------------------------------------------

st.header("4. レイテンシ分析")
latency = analyze_latency(records)
st.caption(f"成功 {latency.ttft.count} 件から算出。ttft(初動)と elapsed(総時間)は分けて表示。")

lat_cols = st.columns(2)
with lat_cols[0]:
    st.subheader("ttft(初動まで)")
    if latency.ttft.count:
        st.metric("中央値", f"{latency.ttft.median:.1f} s")
        st.metric("最大", f"{latency.ttft.maximum:.1f} s")
        st.caption(f"平均 {latency.ttft.mean:.1f} s(外れ値に注意)")
with lat_cols[1]:
    st.subheader("elapsed(総時間)")
    if latency.elapsed.count:
        st.metric("中央値", f"{latency.elapsed.median:.1f} s")
        st.metric("最大", f"{latency.elapsed.maximum:.1f} s")
        st.caption(f"平均 {latency.elapsed.mean:.1f} s")
st.caption("初動が速ければ総時間が長くても体感は良い。両者を合算しないのはこのため。")


# ---------------------------------------------------------------------------
# 参考: 隠れコスト(reasoning_tokens)
# ---------------------------------------------------------------------------

with st.expander("参考: reasoning_tokens(スキーマ未定義の隠れコスト)"):
    st.caption(
        "「課金される出力のうち中身が見えない分」。裏率とは別軸の隠れコスト。"
        "schema への昇格是非はユーザー判断のため、ここでは raw_usage から拾った参考値です。")
    st.metric("reasoning_tokens 合計", f"{summary.reasoning_tokens:,}",
              help=f"取得できなかったレコード: {summary.reasoning_unknown_count} 件")


# ---------------------------------------------------------------------------
# ライブ自動更新
# ---------------------------------------------------------------------------

if auto:
    st.caption(f"🔄 自動更新: {interval} 秒ごとに末尾差分を読みます")
    if _AUTO_LOOP_ENABLED:
        time.sleep(interval)
        st.rerun()
