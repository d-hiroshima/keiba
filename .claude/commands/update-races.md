---
description: ウォッチリストの出走表・結果・血統データを最新化する
---

引数: $ARGUMENTS（オプション: 個別 race_id 指定、`--results-only` など）

手順:

1. 引数なし → ウォッチリスト一括更新:
   ```
   python scripts/fetch_races.py --watchlist
   python scripts/fetch_results.py --watchlist
   python scripts/fetch_pedigree.py --watchlist
   ```

2. 引数に race_id があれば対象を限定:
   ```
   python scripts/fetch_races.py $ARGUMENTS
   python scripts/fetch_results.py $ARGUMENTS
   ```

3. 取得結果（成功/失敗の件数）をサマリで報告

4. **取得後の追加チェック**:
   - 出走確定済みのレースで pedigree データが欠けている馬を抽出
   - 自動的に `python scripts/fetch_pedigree.py <horse_id>...` で補完

同日内取得済みの場合はスキップされる。`--force` で強制再取得。

`--results-only` が指定されたら結果のみ取得（出走表と血統はスキップ）。
