---
description: 個別レースを多視点で予想する。例: /analyze 202605030811 / /analyze 202605030811 --full / /analyze --horse 2020103060
---

`analyze-race` スキルに従って、引数で渡された race_id を予想してください。

引数: $ARGUMENTS

手順は **`.claude/skills/analyze-race.md` のステップ 1〜5 がすべて**（ここに再掲しない。
エージェント選抜・全頭分析必須ルール・発走前ゲート・保存と機械検証もスキル側に定義済み）。

このコマンド固有の注意のみ:

- 引数から race_id（または `--horse <horse_id>`）とオプション（`--full` / `--quick`）を抽出する。
  keibalab の URL が貼られた場合は ID を抽出（`/db/race/<race_id>/...`、`/db/horse/<horse_id>/`）
- `devils-advocate` は省略しない。`macro-scout` も毎回必須（揮発データ担当）
- `--horse <horse_id>` 指定時は対象馬の適性・次走分析モード（出走予定があればそのレースも連動分析）
- 引数なしの場合は使い方を表示する
