# fugu-lab

Sakana Fugu を月額契約すべきか判断するための計測環境。ローカルファーストの
マルチプロバイダ・チャットアプリ(`chat/`)で実使用データ(UsageRecord)を JSONL に
記録し、ダッシュボード(`dashboard/`)でその集計から契約可否を判断する。

`claudePlayGround` から `playground-spawn` で派生。由来は `.claude/SKILLS_ORIGIN.md`。

## 構成

| ディレクトリ | 中身 | 仕様書 |
|---|---|---|
| `chat/` | Fugu を叩くチャットアプリ。使用データを JSONL に記録 | `chat/SPEC.md` |
| `dashboard/` | JSONL を読み、契約判断のための集計を出す | `dashboard/SPEC.md`(別途配置) |
| `schema/` | 両者の唯一の結合点。UsageRecord の定義 | `schema/usage-record.md` |
| `docs/` | 実装プロンプト等の参考資料 | `docs/implementation-prompt.md` |

運用ルールは `CLAUDE.md` を参照。**実装前に担当ディレクトリの `SPEC.md` と
`schema/usage-record.md` を必ず読むこと。**
