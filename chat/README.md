# chat/ — Fugu 計測用チャットアプリ (Phase 0)

Sakana Fugu を OpenAI 互換 API 越しに叩き、**全リクエストの UsageRecord を欠損なく
JSONL に記録する**チャットアプリ。集計・コスト・グラフは持たない(それは `../dashboard/`)。

仕様は `SPEC.md`、データ契約は `../schema/usage-record.md`。

## セットアップ

```bash
# conda(推奨)
conda env create -f environment.yml
conda activate fugu-chat
# または pip
pip install -e ".[dev]"
```

### 設定と鍵

- 設定ファイル: `config/endpoints.example.json` をコピーして `config/endpoints.json` を作る
  （実運用ファイル。`.gitignore` 済み）。無ければ example のまま動く。
- API キー: `.env` に置く(`.gitignore` 済み)。

  ```
  # chat/.env
  FUGU_API_KEY=sk-...   # Sakana Fugu の鍵
  ```

  鍵はサーバー側にのみ保持し、ブラウザには渡さない（`/api/config` は鍵を返さない）。

## 起動

```bash
uvicorn app.main:app --reload --port 8137
# ブラウザで http://127.0.0.1:8137
```

## テスト(ネットワーク不要)

```bash
pytest -q
```

`parse_usage` と「チャンク列 → usage / tool_call 組み立て」を、**実際に Fugu を叩いて
取得した fixtures**(`tests/fixtures/`)に対して検証する。ここが本アプリの心臓部。

## 実 Fugu で 1 往復して JSONL を確認する

```bash
uvicorn app.main:app --port 8137 &
curl -sN http://127.0.0.1:8137/api/chat -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Reply with exactly: hi"}],"params":{"max_tokens":16}}'
cat data/usage.jsonl | python -m json.tool   # UsageRecord が 1 件出る
```

## アーキテクチャ(SPEC の 3 層)

```
static/ (ブラウザ)  ──HTTP+SSE──▶  app/main.py (HTTP/SSE層: 中継のみ)
                                       │
                                       ├─ app/middleware/  (Chain: usage recorder / logger)
                                       └─ app/providers/   (fugu adapter。将来ここを増やす)
                                              │
                                       app/usage/assemble.py  ← 心臓部(チャンク組み立て)
                                       app/usage/record.py    ← schema 準拠の UsageRecord
```

- **Provider 抽象化**: `app/providers/base.py` の IF に揃える。新プロバイダは
  アダプタ 1 つ追加 + 設定追記で足せる(認証方式/usage フィールド名/usage 無しを想定)。
- **Middleware Chain**: `app/middleware/chain.py`。前処理/後処理フックを差せる骨組み。
  v1 は usage recorder と logger のみ。

## 実測で確定した Fugu の挙動(fixtures/README に詳細)

- usage の `orchestration_*` は `*_details` の中にネスト。
- ストリーミング時は `stream_options.include_usage:true` を送ると usage が
  最終チャンク(`choices:[]`)に載る。content 以外を捨てると失う。
- tool_calls は `index` で束ね、arguments は断片を連結してからパースする。

## スコープ(Phase 0)

- やる: ストリーミング表示 / 1 レスポンスごとの実測値 1 行 / tool_call の**観測**
  （実行しない）/ UsageRecord の JSONL 追記。
- やらない(Phase 1/2): 集計・コスト・グラフ(dashboard 担当)、LM Studio アダプタ、
  tool 実行往復・エージェント・MCP、認証、RAG、並列比較。
