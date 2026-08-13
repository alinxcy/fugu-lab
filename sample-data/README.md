# sample-data/

**実際に Fugu を叩いて生成した UsageRecord のサンプル**(会話本文・API キーは含まない。
token 数と `raw_usage` のみ)。②ダッシュボードを実データ形状に対して開発するための種。

- `usage.sample.jsonl` — Phase 0 の動作確認・ミニベンチ・分散/外注実験、および
  tool 実行往復ブランチの動作確認で出た実レコード **43 件**。

## この43件の内訳(ダッシュボード開発の良いテストケース)

| 種別 | 件数 | 特徴 |
|---|---|---|
| fugu-ultra | 15 | 裏率 78〜97%。裏 1,260〜52,001。elapsed 5.2〜408.7s。本文空の行あり |
| fugu-ultra-v1.1 | 2 | 裏率 79〜87%、ttft 100〜156s(下記「追加の実測」) |
| fugu | 24 | **裏 0% が例外なし**(24/24)。elapsed 2.0〜29.3s(抽出/コード/翻訳/要約/正規表現など) |
| エラー | 2 | 不正モデル / fugu-cyber アクセス申請制。token 系すべて null(0ではない) |

含まれる分布・エッジ(ダッシュボードが扱うべきもの):

- **裏率 0% 〜 97% の広い分布** — 分布・幅表示のテストに。
- **レイテンシ 0.8s〜408s** — 中央値・最大の意味が出る広いレンジ。
- **null と 0 の共存** — エラー行は token 系 null、fugu 行は裏 0。両方を区別する必要。
- **本文空でも課金される行** — ultra の1件は `completion_tokens=900` が全て
  `reasoning_tokens`(可視出力ゼロ)で、さらに裏12,364。**「出力0なのに高額」**な行を
  正しく集計できるか(output_tokens>0 だが実質空)。
- `raw_usage` に `reasoning_tokens` / `orchestration_input_cached_tokens` 等の
  スキーマ未定義フィールドが残る(昇格検討材料)。

## 追加の実測(dashboard / chat-tool-execution ブランチの動作確認より)

`fugu`(通常)と `fugu-ultra-v1.1` を同一会話内で長めに使い分けて分かったこと:

- **`fugu` は一貫して裏率 0%** — 39件の実測(単発〜13,950 input tokens の長い会話まで)で
  例外なく `orchestration_input_tokens` / `orchestration_output_tokens` が 0。安定した挙動。
- **`fugu-ultra-v1.1` は裏率 79〜87%、ttft 100〜156秒 が複数ターンにわたって継続**
  (最初の1件だけでなく、同一会話内で3ターン連続)。最初の2件サンプルで見えた
  「ultra は裏が跳ねる・初動が長い」傾向は**単発の外れ値ではなく、ultraモデルの恒常的な特性**
  である可能性が高い。契約判断では「重い処理は常にこのレイテンシ・裏率を覚悟する」前提で
  見積もる必要がある。
- **tool 実行往復(`claude/chat-tool-execution` ブランチ)** — `execute_tools:true` で
  1往復ごとに UsageRecord が1行ずつ記録され、同一 `conversation_id` で紐づくことを実データで確認
  (round 1: tool_call 発行 → round 2: 最終回答)。今回のデモツール(`get_weather`、ネットワーク
  不要の固定値ダミー)では裏率は 0% のまま — **エージェント的な複数往復そのものが裏コストを
  生むわけではなく、モデル側(ultra系)の orchestration が主要因**という切り分けができた。

## 注意

- これは**サンプル**であって live ログではない。実運用の測定ログは
  `chat/data/usage.jsonl`(追記専用・`.gitignore` 済み=各自のローカルにのみ蓄積)。
- サンプルは43件。ダッシュボードは「サンプル数の少なさを隠さない」ことが要件なので、
  この薄さ自体が挙動確認(外挿警告・幅表示)に使える。
- 詳しい所感・ベンチ設問・料金は `../docs/fugu-findings.md`。
