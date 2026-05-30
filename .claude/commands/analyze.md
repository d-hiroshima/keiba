---
description: 個別レースを多視点で予想する。例: /analyze 202605030811 / /analyze 202605030811 --full / /analyze --horse 2020103060
---

`analyze-race` スキルに従って、引数で渡された race_id を予想してください。

引数: $ARGUMENTS

手順:
1. 引数から race_id（または `--horse <horse_id>`）と オプション（--full / --quick）を抽出
2. `data/race.db` でコース・距離・グレードを取得
3. データ鮮度チェック（必要なら fetch_races.py / fetch_pedigree.py / fetch_results.py を実行）
4. プレイブック（`docs/playbooks/<course>-<distance>.md`）の存在確認
5. **対象馬リスト確定**: `entries` から出馬表全頭を取得し、馬番順の対象馬リストを作成。出馬表が取れていない場合は scout の WebFetch で先に確定させる
6. エージェント選抜（`.claude/skills/analyze-race.md` のステップ2のルールに従う）
7. pedigree / track / race-context を**並列**で呼び出し（独立した分析）。**各エージェントには対象馬リスト全頭を渡し、「全頭評価必須」を明示する**
8. 全員の結論が揃ったら devils-advocate を**最後に**呼ぶ
9. 統合判断・買い目を生成。**統合出力には全頭評価サマリ表を必ず含める**

`devils-advocate` は省略しない。引数なしの場合は使い方を表示してください。

**全頭分析必須（ハードルール）**: pedigree / track / race-context / devils-advocate はすべて出走全頭を評価対象とする。「上位人気だけ」「注目馬だけ」のような暗黙の絞り込みは禁止。詳細は `.claude/skills/analyze-race.md` の「全頭分析必須ルール」を参照。

`--horse <horse_id>` を指定された場合は、対象馬の適性・次走分析モードで動作（出走予定があればそのレースも連動分析）。
