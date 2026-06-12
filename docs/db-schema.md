# DB スキーマ（自動生成）

> **このファイルは編集禁止。** `python3 scripts/db.py schema-doc > docs/db-schema.md` で再生成する（CI が drift を検出）。スキーマの定義は `scripts/db.py` の SCHEMA。

## entries

| カラム | 型 | PK |
|---|---|---|
| race_id | TEXT | ✓ |
| horse_id | TEXT | ✓ |
| horse_name | TEXT |  |
| post_position | INTEGER |  |
| gate | INTEGER |  |
| sex | TEXT |  |
| age | INTEGER |  |
| weight_carry | REAL |  |
| jockey | TEXT |  |
| trainer | TEXT |  |

## fetch_log

| カラム | 型 | PK |
|---|---|---|
| target_id | TEXT | ✓ |
| kind | TEXT | ✓ |
| fetched_at | TEXT |  |

## horses

| カラム | 型 | PK |
|---|---|---|
| horse_id | TEXT | ✓ |
| name | TEXT |  |
| birthday | TEXT |  |
| sex | TEXT |  |
| color | TEXT |  |
| sire | TEXT |  |
| sire_id | TEXT |  |
| dam | TEXT |  |
| dam_id | TEXT |  |
| broodmare_sire | TEXT |  |
| broodmare_sire_id | TEXT |  |
| grandsire | TEXT |  |
| breeder | TEXT |  |
| owner | TEXT |  |
| fetched_at | TEXT |  |

## payouts

| カラム | 型 | PK |
|---|---|---|
| race_id | TEXT | ✓ |
| bet_type | TEXT | ✓ |
| combination | TEXT | ✓ |
| payout_yen | INTEGER |  |

## pedigree_stats

| カラム | 型 | PK |
|---|---|---|
| sire_id | TEXT | ✓ |
| sire_name | TEXT |  |
| course | TEXT | ✓ |
| distance | INTEGER | ✓ |
| surface | TEXT | ✓ |
| track_condition | TEXT | ✓ |
| starts | INTEGER |  |
| wins | INTEGER |  |
| seconds | INTEGER |  |
| thirds | INTEGER |  |
| win_rate | REAL |  |
| place_rate | REAL |  |
| show_rate | REAL |  |
| fetched_at | TEXT |  |
| n_horses | INTEGER |  |

## races

| カラム | 型 | PK |
|---|---|---|
| race_id | TEXT | ✓ |
| date | TEXT |  |
| course | TEXT |  |
| course_no | INTEGER |  |
| day_no | INTEGER |  |
| race_no | INTEGER |  |
| race_name | TEXT |  |
| grade | TEXT |  |
| race_class | TEXT |  |
| surface | TEXT |  |
| distance | INTEGER |  |
| direction | TEXT |  |
| weather | TEXT |  |
| track_condition | TEXT |  |
| post_time | TEXT |  |
| fetched_at | TEXT |  |
| field_size | INTEGER |  |
| pace_front_3f | REAL |  |
| pace_last_3f | REAL |  |
| pace_class | TEXT |  |
| lap_times | TEXT |  |

## results

| カラム | 型 | PK |
|---|---|---|
| race_id | TEXT | ✓ |
| horse_id | TEXT | ✓ |
| finish_position | INTEGER |  |
| finish_time | TEXT |  |
| margin | TEXT |  |
| last_3f | REAL |  |
| last_3f_rank | INTEGER |  |
| passing_order | TEXT |  |
| corner_position | TEXT |  |
| note | TEXT |  |
| jockey | TEXT |  |
| trainer | TEXT |  |
| weight_carry | REAL |  |
| popularity | INTEGER |  |
| win_odds | REAL |  |
| horse_weight | INTEGER |  |
| horse_weight_diff | INTEGER |  |

## 検証済みクエリ例（コピペ実行可）

すべて `python3 -c "..."` か `python3 scripts/db.py` の CLI で実行する（sqlite3 CLI は環境に無い）。

### 1コマンド系（まずこれを使う）

```bash
python3 scripts/db.py card 202605310511     # レースカード＋全頭の直近5走（ペース文脈付き）
python3 scripts/db.py history 2023103060    # 1頭の全戦績
python3 scripts/db.py sire-stats 11202426   # 種牡馬の産駒成績（要: 事前集計）
```

### 生 SQL（python3 -c で実行）

```python
# 同条件（コース×距離×芝ダ）の父系産駒成績 — pedigree-analyst 用
SELECT h.sire, COUNT(*) starts,
       SUM(re.finish_position = 1) wins,
       ROUND(AVG(re.finish_position <= 3), 3) show_rate,
       COUNT(DISTINCT re.horse_id) n_horses
FROM results re
JOIN horses h ON h.horse_id = re.horse_id
JOIN races  ra ON ra.race_id = re.race_id
WHERE ra.course = 'tokyo' AND ra.distance = 1600 AND ra.surface = 'turf'
GROUP BY h.sire ORDER BY starts DESC;

# 直近3走の通過順 → 脚質判定の材料 — track-analyst 用
SELECT ra.date, ra.course, ra.distance, re.passing_order, re.last_3f, re.last_3f_rank
FROM results re JOIN races ra ON ra.race_id = re.race_id
WHERE re.horse_id = '2023103060' ORDER BY ra.date DESC LIMIT 3;

# 騎手のコース別成績（results に蓄積した確定値から） — track-analyst 用
-- 注意: ローカル DB に当該騎手の騎乗結果が貯まっている範囲の集計。
-- N が小さいうちは「騎手当該コース勝率」の根拠に使わない（N=0 ルール参照）
SELECT re.jockey, COUNT(*) n,
       SUM(re.finish_position = 1) wins,
       ROUND(AVG(re.finish_position <= 2), 3) ren_rate
FROM results re JOIN races ra ON ra.race_id = re.race_id
WHERE ra.course = 'kyoto' AND ra.surface = 'turf' AND re.jockey IS NOT NULL
GROUP BY re.jockey HAVING n >= 10 ORDER BY wins DESC;

# レースの上がり最速馬（last_3f_rank はレース全頭取得時に自動計算）
SELECT re.horse_id, re.finish_position, re.last_3f, re.last_3f_rank
FROM results re WHERE re.race_id = '202605310511' ORDER BY re.last_3f_rank LIMIT 5;

# 枠番別成績（コースバイアス確認）
SELECT e.gate, COUNT(*) n, ROUND(AVG(re.finish_position <= 3), 3) show_rate
FROM results re
JOIN entries e ON e.race_id = re.race_id AND e.horse_id = re.horse_id
JOIN races  ra ON ra.race_id = re.race_id
WHERE ra.course = 'nakayama' AND ra.distance = 2000
GROUP BY e.gate ORDER BY e.gate;
```

### 注意

- **race_id から距離・条件は判定できない**（race_id は日付+場+R のみ）。条件で絞るときは必ず `races` と JOIN する
- `results.jockey` は過去レースの騎乗者（確定値）。**今走の騎手は `entries.jockey`**
- `pedigree_stats.n_horses` が小さい行は個体成績の言い換えに過ぎない。N=0 ルール（docs/output-schema.md §6）に従う

