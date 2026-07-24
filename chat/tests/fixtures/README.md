# Fugu 実レスポンス fixtures（実データ）

これらは **実際に `https://api.sakana.ai/v1/chat/completions` を叩いて取得した生レスポンス**。
想定JSONではなく実データなので、`parse_usage` とチャンク組み立ての単体テストの正とする。

- `fugu_nonstream_hi.json` — 非ストリーミング（`stream:false`）の完全レスポンス。
- `fugu_stream_hi.txt` — ストリーミング（`stream:true` + `stream_options.include_usage:true`）の
  生 SSE。最終チャンクに usage が載る形を含む。

## 実測で判明した usage の実形状（重要）

```jsonc
"usage": {
  "prompt_tokens": 99,          // = 表の入力
  "completion_tokens": 18,      // = 表の出力
  "total_tokens": 117,
  "prompt_tokens_details": {
    "cached_tokens": 0,
    "orchestration_input_tokens": 0,          // ← ネスト！ トップレベルではない
    "orchestration_input_cached_tokens": 0    // ← スキーマ未定義の追加フィールド
  },
  "completion_tokens_details": {
    "reasoning_tokens": 13,                    // ← スキーマ未定義。非0になりうる（別呼出で285observed）
    "orchestration_output_tokens": 0          // ← ネスト！
  }
}
```

## UsageRecord へのマッピング（`../../../schema/usage-record.md` 準拠）

| UsageRecord フィールド | Fugu レスポンス上のパス |
|---|---|
| `input_tokens` | `usage.prompt_tokens` |
| `output_tokens` | `usage.completion_tokens` |
| `cached_tokens` | `usage.prompt_tokens_details.cached_tokens` |
| `orchestration_input_tokens` | `usage.prompt_tokens_details.orchestration_input_tokens` |
| `orchestration_output_tokens` | `usage.completion_tokens_details.orchestration_output_tokens` |
| `raw_usage` | `usage` オブジェクト全体を無加工で保存 |

**注意点（実装が守ること）:**

1. `orchestration_*` は `*_details` の中。トップレベルで探すと中心指標が全部 null になる。
2. **ストリーミング時、usage は最終チャンクに載る。** そのチャンクは
   `"choices": []`（空配列）。`choices[0]` を前提にすると落ちる。空 choices を許容すること。
3. `stream_options.include_usage: true` を送らないとストリームに usage が来ない可能性が高い。
   本 fixtures は付けて取得している。
4. スキーマ未定義の追加フィールド（`orchestration_input_cached_tokens`, `reasoning_tokens`）は
   `raw_usage` に丸ごと残るので取りこぼさない。first-class にするかは schema 側の判断（下記）。

## スキーマ検討事項（`schema/usage-record.md` の担当者/ユーザー判断）

- `reasoning_tokens` は「課金される出力のうち中身が見えない分」であり、
  裏トークン比率とは別軸の「隠れコスト」。実測で 285 tok（出力296中）になった例もある。
  現状は `raw_usage` 経由でしか拾えない。first-class フィールドに昇格するかは要判断。
  昇格する場合、`schema/usage-record.md` と ②ダッシュボードの両方に影響する。
