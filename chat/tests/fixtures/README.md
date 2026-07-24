# Fugu 実レスポンス fixtures（実データ）

これらは **実際に `https://api.sakana.ai/v1/chat/completions` を叩いて取得した生レスポンス**。
想定JSONではなく実データなので、`parse_usage` とチャンク組み立ての単体テストの正とする。

- `fugu_nonstream_hi.json` — 非ストリーミング（`stream:false`）の完全レスポンス。
- `fugu_stream_hi.txt` — ストリーミング（`stream:true` + `stream_options.include_usage:true`）の
  生 SSE。最終チャンクに usage が載る形を含む。
- `fugu_stream_toolcall_weather.txt` — tool_calls を含むストリーミング SSE（get_weather を呼ぶ例）。
- `fugu_error_invalid_model.json` — エラー時のレスポンス封筒（不正モデル名 → 4xx）。
- `fugu_models.json` — `GET /v1/models` の実レスポンス（既定モデルIDの正）。

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

## tool_calls のストリーミング組み立て規則（実測）

- delta は `choices[0].delta.tool_calls[]`。**`index` で束ねる。**
- **初回チャンク**のみ `id` / `function.name` / `type` が入り、`function.arguments` は `""`。
- **以降のチャンク**は `index` と `function.arguments` の**断片**だけ（`{"` → `city` → `":"`
  → `Os` → `aka` → `"}`）。同じ index の arguments を順に連結する。
- 完了時 `finish_reason: "tool_calls"`。その後に usage チャンク（`choices: []`）→ `[DONE]`。
- **引数 JSON は全断片を連結してから初めてパースする。** 途中でパースしない。
  連結後にパース失敗したら「壊れて返った」事実として保持・表示する（握り潰さない＝SPEC要件）。

## エラー封筒（実測）

```json
{ "error": { "message": "...", "type": "invalid_request_error", "request_id": "..." } }
```

失敗時も UsageRecord は必ず1件生成し、`error` に message（＋できれば type/request_id）を入れ、
usage 系は取れなければ null にする（0で埋めない）。

## モデルID（`GET /v1/models` 実測）

`fugu`, `fugu-cyber`, `fugu-ultra`, `fugu-ultra-20260615`, `fugu-ultra-v1.0`, `fugu-ultra-v1.1`
（`endpoints.example.json` の既定はこの実在値から選ぶ）。
※ `fugu-ultra` 系は fan-out が重く、実測で 2 分でも完了しないことがある（レイテンシ注意）。

## 裏トークンは「追加課金」であって表の部分集合ではない（重要・実測）

`fugu_ultra_orchestration_usage.json` は fugu-ultra に複雑タスクを投げた実 usage:

```
prompt_tokens 180 / completion_tokens 800 / total_tokens 980   ← 表(見える分)
orchestration_input_tokens  20,399
orchestration_output_tokens 25,988                              ← 裏 = 46,387
```

`orchestration_input_tokens`(20,399) は `prompt_tokens`(180) を大きく超える。
つまり **orchestration_* は prompt/completion の内訳(部分集合)ではなく、別枠で追加課金される**。
`total_tokens` にも裏は含まれない。したがって裏トークン比率の分母は表だけではダメで:

```
課金トークン総計 = input + output + orchestration_input + orchestration_output
裏トークン比率   = (orchestration_input + orchestration_output) / 課金トークン総計
```

この例では 46,387 / 47,367 ≒ **98%** が裏。②ダッシュボードの中心指標はこの定義で。
（`orchestration_input_cached_tokens` は orchestration_input の内数=キャッシュヒット分。二重計上しない。）

補足: fugu-ultra はこの1リクエストで **427 秒** かかった。ttft/elapsed を分けて記録する
意義が実データで裏付けられた(初動と総時間の体感差)。

## スキーマ検討事項（`schema/usage-record.md` の担当者/ユーザー判断）

- `reasoning_tokens` は「課金される出力のうち中身が見えない分」であり、
  裏トークン比率とは別軸の「隠れコスト」。実測で 285 tok（出力296中）になった例もある。
  現状は `raw_usage` 経由でしか拾えない。first-class フィールドに昇格するかは要判断。
  昇格する場合、`schema/usage-record.md` と ②ダッシュボードの両方に影響する。
