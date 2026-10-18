"""score_prediction.py の採点ロジックのテスト。"""

from __future__ import annotations

from score_prediction import parse_bets, parse_marks, score

PREDICTION_MD = """# レース予想: 202606010511 テスト記念（tokyo 1600m turf, GIII）

## 全頭評価サマリ（必須・出走全頭）
| 馬番 | 馬名 | 想定人気 | pedigree | track | race-context | devils | 総合 | 選定 | キー論点 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | アルファテスト | 2 | +3 | +2 | +1 | -1 | **+3** | ◎ | 軸 |
| 2 | ベータテスト | 1 | +2 | +2 | +1 | -1 | +2 | ○ | 対抗 |
| 3 | ガンマテスト | 3 | 0 | 0 | 0 | +1 | +1 | ▽ | 穴 |

## 買い目（参考・予算 1000円）

### ワイド 600円
| 買い目 | 推定オッズ | 投資額 | 想定払戻 |
|---|---|---|---|
| 1-2 | 約3倍 | 400 円 | 1200 円 |
| 2-3（△-▽保険） | 約8倍 | 200 円 | 1600 円 |
| **合計** | | 600 円 | |

### 三連複 400円
| 買い目 | 推定オッズ | 投資額 | 想定払戻 |
|---|---|---|---|
| 1-2-3 | 約12倍 | 400 円 | 4800 円 |
| **合計** | | 400 円 | |
"""


def test_parse_marks():
    marks = parse_marks(PREDICTION_MD)
    assert marks == {1: "◎", 2: "○", 3: "▽"}


def test_parse_bets():
    bets = parse_bets(PREDICTION_MD)
    assert [(b.bet_type, b.combination, b.amount) for b in bets] == [
        ("wide", "1-2", 400),
        ("wide", "2-3", 200),
        ("sanrenpuku", "1-2-3", 400),
    ]


def _seed(db):
    with db.connect() as conn:
        db.upsert_race(conn, {
            "race_id": "202606010511", "date": "2026-06-01", "course": "tokyo",
            "race_no": 11, "surface": "turf", "distance": 1600,
        }, authoritative=True)
        for no, (hid, name, fp, pop, odds) in enumerate([
            ("2099000001", "アルファテスト", 1, 2, 4.5),
            ("2099000002", "ベータテスト", 2, 1, 2.1),
            ("2099000003", "ガンマテスト", 3, 3, 10.0),
        ], start=1):
            conn.execute(
                "INSERT INTO entries (race_id, horse_id, horse_name, post_position)"
                " VALUES (?,?,?,?)",
                ("202606010511", hid, name, no),
            )
            db.upsert_result(conn, "202606010511", hid,
                             {"finish_position": fp, "popularity": pop, "win_odds": odds},
                             authoritative=True)
        for bt, combo, yen in [
            ("win", "1", 450), ("wide", "1-2", 300), ("wide", "1-3", 700),
            ("wide", "2-3", 500), ("sanrenpuku", "1-2-3", 1200),
        ]:
            conn.execute(
                "INSERT INTO payouts (race_id, bet_type, combination, payout_yen)"
                " VALUES (?,?,?,?)",
                ("202606010511", bt, combo, yen),
            )


def test_score_end_to_end(tmp_db):
    _seed(tmp_db)
    result = score("202606010511", parse_marks(PREDICTION_MD), parse_bets(PREDICTION_MD))
    assert result is not None
    assert result["invested"] == 1000
    # wide 1-2: 400円 → 4×300=1200 / wide 2-3: 200円 → 2×500=1000 / 三連複: 400円 → 4×1200=4800
    assert result["returned"] == 1200 + 1000 + 4800
    assert result["roi"] == 7.0
    by_mark = {m["mark"]: m for m in result["marks"]}
    assert by_mark["◎"]["finish"] == 1 and by_mark["◎"]["name"] == "アルファテスト"


def test_score_returns_none_without_results(tmp_db):
    assert score("209901010101", {1: "◎"}, []) is None


# 2026秋華賞: 「| # | 組み合わせ | 金額 |」の表を旧実装が 0 件と読み、採点が投資 0 円になった
ACTUAL_MD = """## 買い目（参考）

### 三連複 1,000円（推奨）
| # | 組み合わせ | 金額 |
|---|---|---|
| 1 | 8-13-3 | 100円 |
| 2 | 8-13-4 | 100円 |

### 馬連ボックス 1,000円（**実購入**）
| # | 組み合わせ | 金額 |
|---|---|---|
| 1 | 3-8 | 100円 |
| 2 | 8-13 | 100円 |

**決着パターン別の払戻**:
| 1-3着の組合せ | 的中する買い目 | 払戻 |
|---|---|---|
| 1・8・13 | 8-13 | 500 円 |
"""


def test_parse_bets_reads_columns_by_header_and_prefers_actual():
    bets = parse_bets(ACTUAL_MD)
    assert [(b.bet_type, b.combination, b.amount) for b in bets] == [
        ("umaren", "3-8", 100),
        ("umaren", "8-13", 100),
    ]


def test_parse_bets_without_actual_marker_returns_all():
    md = ACTUAL_MD.replace("**実購入**", "代替案")
    assert [b.combination for b in parse_bets(md)] == ["3-8-13", "4-8-13", "3-8", "8-13"]


def test_parse_bets_ignores_tables_without_stake_column():
    md = """### ワイド 900円
| 1-3着の組合せ | 的中する買い目 | 払戻 |
|---|---|---|
| 1・15・11 | 1-15, 11-15 | 1,940 円 |
"""
    assert parse_bets(md) == []
