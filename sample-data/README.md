# sample-data/

**実際に Fugu を叩いて生成した UsageRecord のサンプル**(会話本文・API キーは含まない。
token 数と `raw_usage` のみ)。②ダッシュボードを実データ形状に対して開発するための種。

- `usage.sample.jsonl` — Phase 0 の動作確認で出た実レコード。

## この2件が示す対照(ダッシュボード開発の良いテストケース)

| model | elapsed | ttft | 表(in+out) | 裏(orch) | 裏率 |
|---|---|---|---|---|---|
| fugu-ultra | 287.4s | 287.4s | 7,286 | 25,389 | **78%** |
| fugu | 25.9s | 25.7s | 1,610 | 0 | **0%** |

- **裏率 78% と 0% の対照** — 「軽い/直接回答は裏0、重い orchestration は裏が跳ねる」傾向。
- **ttft ≈ elapsed(ultra)** — 初動まで無音で数分。総時間だけ見ると体感を見誤る。
- `raw_usage` に `reasoning_tokens`(ultra で 4,920)や `orchestration_input_cached_tokens` など
  スキーマ未定義の追加フィールドが残っている(昇格是非の検討材料)。

## 注意

- これは**サンプル**であって live ログではない。実運用の測定ログは
  `chat/data/usage.jsonl`(追記専用・`.gitignore` 済み=各自のローカルにのみ蓄積)。
- サンプルは2件と薄い。ダッシュボードは「サンプル数の少なさを隠さない」ことが要件なので、
  この薄さ自体が挙動確認(外挿警告・幅表示)に使える。
