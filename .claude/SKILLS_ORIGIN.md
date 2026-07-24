# SKILLS_ORIGIN

このリポジトリの `.claude/skills/` は
[claudePlayGround](https://github.com/alinxcy/claudePlayGround) から
`playground-spawn` で持ち出したもの。

- 持ち出し元コミット: `6c27e5b`
- 持ち出し日: `2026-07-24`

## 持ち出したもの

| 名前 | 種別 | 元パス | 改変 | 備考 |
|---|---|---|---|---|
| frontend-design | skill | `.claude/skills/frontend-design` | なし | チャット UI / ダッシュボード UI の意匠 |
| dataviz | skill | `builtins-reconstructed/dataviz` | なし | ダッシュボードの使用量可視化 |
| md | skill | `.claude/skills/md` | なし | README・設計メモ |
| skill-creator | skill | `.claude/skills/skill-creator` | なし | 判断後の派生手順の Skill 化に使う |
| skill-harvester | skill | `.claude/skills/skill-harvester` | なし | 同上(Skill 化候補の発掘) |
| session-start-hook | skill | `builtins-reconstructed/session-start-hook` | なし | web セッションでのテスト/リンタ自動セットアップ |

## このリポジトリで新規作成したもの

| 名前 | 種別 | 汎用性 | 備考 |
|---|---|---|---|
| （なし） | | | |

## 還流について

スキルを改変・新規作成したら、上の表の「改変」列を `あり` に更新し、
何を変えたかを備考に1行書く。playground に戻したくなったら `skill-return` を使う。

CLAUDE.md の「判断後にやること」にある通り、一連の派生手順が Skill 化できたら
`skill-harvester` / `skill-creator` で起こし、汎用性が高いものは playground に還流する。
