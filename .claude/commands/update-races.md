---
description: 指定したレース／馬の出走表・結果・血統データを最新化する
---

引数: $ARGUMENTS（race_id(12桁) / horse_id(10桁) / keibalab URL を1つ以上。オプション: `--results-only` / `--force`）

> watchlist は廃止。対象は**この引数で都度指定**する（一括取得の固定リストは持たない）。
> keibalab の URL を貼られた場合は ID を抽出して使う（`/db/race/<race_id>/...`、`/db/horse/<horse_id>/`）。

手順:

1. 引数の ID を種類で振り分けて取得（同日内取得済みは自動スキップ。`--force` で強制）:
   ```
   # レース（12桁）: 出走表 + 結果
   python scripts/fetch_races.py <race_id>...
   python scripts/fetch_results.py <race_id>...
   # 馬（10桁）: 全戦績 + 血統
   python scripts/fetch_results.py <horse_id>...
   python scripts/fetch_pedigree.py <horse_id>...
   # レース出走馬の血統を一括で:
   python scripts/fetch_pedigree.py --race <race_id>
   ```

2. 取得結果（成功/失敗の件数）をサマリで報告。

3. **取得後の追加チェック**:
   - 出走確定済みレースで `horses`（血統）が欠けている馬を抽出
   - `python scripts/fetch_pedigree.py <horse_id>...` で補完
   - 必要なら `python scripts/fetch_pedigree.py --sire-stats <sire_id>`（ローカル集計）で産駒成績を更新

4. `--results-only` 指定時は結果のみ取得（出走表・血統はスキップ）。

引数が無い場合は「対象の race_id / horse_id / keibalab URL を指定してください」と促す。
