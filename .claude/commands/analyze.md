---
description: 個別レースを多視点で予想する。例: /analyze 202604030611 / /analyze 202604030611 --full / /analyze --horse 2020100789
---

`analyze-race` スキルに従って、引数で渡された race_id を予想してください。

引数: $ARGUMENTS

手順:
1. 引数から race_id（または `--horse <horse_id>`）と オプション（--full / --quick）を抽出
2. `data/race.db` でコース・距離・グレードを取得
3. データ鮮度チェック（必要なら fetch_races.py / fetch_pedigree.py / fetch_results.py を実行）
4. プレイブック（`docs/playbooks/<course>-<distance>.md`）の存在確認
5. エージェント選抜（`.claude/skills/analyze-race.md` のステップ2のルールに従う）
6. pedigree / track / race-context を**並列**で呼び出し（独立した分析）
7. 全員の結論が揃ったら devils-advocate を**最後に**呼ぶ
8. 統合判断・買い目を生成

`devils-advocate` は省略しない。引数なしの場合は使い方を表示してください。

`--horse <horse_id>` を指定された場合は、対象馬の適性・次走分析モードで動作（出走予定があればそのレースも連動分析）。
