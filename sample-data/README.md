# sample-data/

**実際に Fugu を叩いて生成した UsageRecord のサンプル**(会話本文・API キーは含まない。
token 数と `raw_usage` のみ)。②ダッシュボードを実データ形状に対して開発するための種。

- `usage.sample.jsonl` — Phase 0 の動作確認、および tool 実行往復ブランチの動作確認で出た実レコード。

## この2件が示す対照(最初の動作確認)

| model | elapsed | ttft | 表(in+out) | 裏(orch) | 裏率 |
|---|---|---|---|---|---|
| fugu-ultra | 287.4s | 287.4s | 7,286 | 25,389 | **78%** |
| fugu | 25.9s | 25.7s | 1,610 | 0 | **0%** |

- **裏率 78% と 0% の対照** — 「軽い/直接回答は裏0、重い orchestration は裏が跳ねる」傾向。
- **ttft ≈ elapsed(ultra)** — 初動まで無音で数分。総時間だけ見ると体感を見誤る。
- `raw_usage` に `reasoning_tokens`(ultra で 4,920)や `orchestration_input_cached_tokens` など
  スキーマ未定義の追加フィールドが残っている(昇格是非の検討材料)。

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
- サンプルは少数精鋭。ダッシュボードは「サンプル数の少なさを隠さない」ことが要件なので、
  この薄さ自体が挙動確認(外挿警告・幅表示)に使える。
