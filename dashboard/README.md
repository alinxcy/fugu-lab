# dashboard/

`chat/` が吐く UsageRecord の JSONL を読み、**Fugu を契約すべきか(するならどのプランか、
あるいは契約しないか)を判断する**ためのダッシュボード。

仕様は [`SPEC.md`](SPEC.md) が正。データ契約は [`../schema/usage-record.md`](../schema/usage-record.md)。
このアプリは `chat/` のコードに一切依存しない(結合点は JSONL スキーマのみ)。

## 設計上いちばん大事なこと

薄いサンプル(測定窓は金・土の 2 日)から**誤った確信を生まない**こと。だから:

- どの数字にも「何件・何日から算出したか」を添える
- 月間推定は点でなく**幅**で出し、薄いときは警告を強調する
- **「契約しない」を第一級の結論**として提示する(どれかのプランを前提にしない)
- 裏トークン比率(orchestration / 課金総計)を**中心指標**として扱う
- null(取れなかった)と 0(実際に 0)を区別する
- 壊れた行・欠損・未知フィールドでも落とさず、スキップした事実を表示する

## 構成

```
dashboard/
  core/            # 依存ゼロの純粋ロジック(ここを最優先でテスト)
    record.py      # UsageRecord パース・null/0区別・裏率・未知フィールド検知
    loader.py      # JSONL 読み込み(壊れ行スキップ)＋末尾差分(tail)ロード
    metrics.py     # サマリ・オーバーヘッド・レイテンシ・枠フィット外挿(幅つき)
    config.py      # パス/レート/プラン設定(レートはコードに埋めない)
  config/
    rates.example.toml   # 設定テンプレ(実値は rates.toml にコピーして埋める)
  app.py           # Streamlit UI(表示のみ。ロジックは core を呼ぶだけ)
  tests/           # ネットワーク不要の単体テスト + AppTest スモーク
```

## セットアップ

```bash
pip install -e '.[dev]'          # streamlit + pytest
cp config/rates.example.toml config/rates.toml   # 実レートを入れる(任意)
```

## 実行

```bash
cd dashboard
streamlit run app.py
```

- **ライブ(既定)**: 追記を監視し、末尾差分だけを読んで自動更新する。
  既定の入力は `../chat/data/usage.jsonl`。サイドバーでパスを変えられる。
- **バッチ**: 指定した JSONL を読む(複数可)。開発時は
  `../sample-data/usage.sample.jsonl` を読むと実データ形状で確認できる。

レートは `config/rates.toml`(無ければ `rates.example.toml`)から読む。
プレースホルダ(全 0)のあいだはコスト換算を無効化し、UI に警告を出す。
**コスト表示は「正確な請求額」ではなく相対的な重さの指標**。

## テスト

```bash
cd dashboard && pytest
```

`core/` の集計ロジック(裏率・null/0 区別・壊れ行スキップ・外挿の幅と警告)を
ネットワーク不要で検証する。ここが壊れると日曜の判断を静かに誤らせるため、最優先。
```
