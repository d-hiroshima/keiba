# predictions/ — 予想の確定保存（フィードバックループの起点）

`/analyze` の統合出力（`docs/output-schema.md` §4 準拠の Markdown）をここに保存する。
ファイル名は **`<race_id>-<レース名スラッグ>.md`**（例: `202606070511-yasuda-kinen.md`）。
race_id プレフィクスで `score_prediction.py` がレースを特定する。

## 確定の規約（ルックアヘッド汚染ガード）

1. **予想は「発走時刻前の git commit」をもって確定** とする。発走後に印・買い目を書き換えた
   予想は採点・校正の母集団に入れない（後知恵の混入）。
2. 結果は元の予想本文を書き換えず、**`## 結果検証（自動採点）` セクションの追記** のみで残す
   （`python3 scripts/score_prediction.py <file> --append`）。
3. **バックフィルした過去レースに対する「予想の練習」「回収率検証」は禁止**。
   LLM はカットオフ以前のレース結果を学習済みのため、過去レース予想は後知恵が混入し
   検証として無効。過去データは「集計の母数」（産駒成績・コース傾向）にのみ使う。
4. 校正（強気度・確信度 → 実際の的中率の照合）の母集団は
   「**モデルのカットオフ後 かつ 発走前確定**」の予想に限定する。

## 運用フロー

```
/analyze <race_id>
  → 統合出力を predictions/<race_id>-<slug>.md に保存
  → python3 scripts/validate_output.py predictions/<...>.md --type integrated
  → （発走前に）git commit
--- レース後 ---
/review-race <race_id>
  → fetch_results.py で結果・払戻を取得
  → score_prediction.py --append で採点を追記
  → 外した場合は docs/postmortems/ に教訓を書き、反映先を決める
```

## プライバシー・データ分類

買い目の金額は個人情報に近い。このリポジトリを公開にする場合は
`docs/data-policy.md` の分類表に従うこと（予想成果物の扱いを含む）。
