---
description: 終了したレースの予想を採点し、教訓を抽出する。例 /review-race 202606070511
---

引数: $ARGUMENTS（race_id 12桁。省略時は predictions/ 内の未採点ファイルを列挙して確認）

「予想 → 結果 → 採点 → 教訓の反映」ループの後半を回すコマンド。

# 手順

1. **対象特定**: 引数の race_id に対応する `predictions/<race_id>-*.md` を探す。
   無ければ「予想が保存されていない」と報告して終了（採点対象が無い）。
2. **結果取得**（不変データ）:
   ```
   python3 scripts/fetch_results.py <race_id>
   python3 scripts/fetch_races.py <race_id>
   ```
   ContentNotReadyError（未確定）ならレース前なので中断。
3. **機械採点**:
   ```
   python3 scripts/score_prediction.py predictions/<race_id>-*.md --append
   ```
   印別着順・買い目的中・回収率が md 末尾に追記される。
4. **教訓抽出（外した場合は必須、当たった場合も過程を点検）**:
   - `docs/postmortems/_template.md` をコピーして `docs/postmortems/<YYYY-MMDD>-<slug>.md` を作成
   - 「事実 → 判断のズレ」を具体的に。**当たっていた部分** も書く（過剰修正の防止）
   - 教訓ごとに **反映先**（プレイブック / エージェントのガード / 発走前ゲート / validator）を決め、
     反映できるものはその場で反映して「反映済み」、できないものは「候補」として残す
5. **過去の「候補」の確認**: `docs/postmortems/` の既存ファイルで「状態=候補」のままの教訓が
   あれば、今回反映するか判断する（放置させない）。
6. **報告**: 採点サマリ（回収率）＋教訓＋反映状況を簡潔に。

# ガード

- 採点は **機械突合の結果（score_prediction.py）を正** とし、手で書き換えない
- 予想本文（発走前に書いた部分）は編集しない。追記のみ（ルックアヘッド汚染ガード、predictions/README.md）
- 教訓は「次の予想で機械的に確認できる形」に落とす（曖昧な精神論は書かない）
