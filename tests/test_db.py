"""db.py のスキーマ・upsert セマンティクス・マイグレーションのテスト。"""

from __future__ import annotations

import sqlite3

import pytest


def test_parse_race_id():
    import db

    meta = db.parse_race_id("202605030811")
    assert meta["date"] == "2026-05-03"
    assert meta["course"] == "kyoto"
    assert meta["race_no"] == 11
    with pytest.raises(ValueError):
        db.parse_race_id("2026")


def _base_race(**over):
    r = {
        "race_id": "202606010511", "date": "2026-06-01", "course": "tokyo",
        "race_no": 11, "surface": "turf", "distance": 1600,
    }
    r.update(over)
    return r


def test_upsert_race_null_safety(tmp_db):
    db = tmp_db
    with db.connect() as conn:
        # 戦績表由来（略記・非権威）が先に入る
        db.upsert_race(conn, _base_race(race_name="テスト記念", weather=None), authoritative=False)
        # 結果ページ（権威）が確定値を上書き
        db.upsert_race(conn, _base_race(weather="晴", post_time="15:40"), authoritative=True)
        # 後から来た非権威の別値は既存を壊さない
        db.upsert_race(conn, _base_race(weather="雨", race_name=None), authoritative=False)
        # 権威ソースでも NULL は既存値を消さない
        db.upsert_race(conn, _base_race(weather=None), authoritative=True)

        row = conn.execute("SELECT * FROM races WHERE race_id='202606010511'").fetchone()
        assert row["weather"] == "晴"          # 非権威の「雨」に上書きされない
        assert row["race_name"] == "テスト記念"  # 権威ソースの NULL で消えない
        assert row["post_time"] == "15:40"


def test_upsert_result_null_safety(tmp_db):
    db = tmp_db
    with db.connect() as conn:
        # 馬ページ戦績由来: ペース・人気はあるがオッズが無い
        db.upsert_result(conn, "202606010511", "2099000001",
                         {"finish_position": 1, "popularity": 2, "win_odds": None},
                         authoritative=False)
        # 結果ページ由来: オッズあり
        db.upsert_result(conn, "202606010511", "2099000001",
                         {"finish_position": 1, "popularity": 2, "win_odds": 4.5},
                         authoritative=True)
        row = conn.execute("SELECT * FROM results").fetchone()
        assert row["win_odds"] == 4.5 and row["popularity"] == 2


def test_recompute_last_3f_rank_with_ties(tmp_db):
    db = tmp_db
    with db.connect() as conn:
        for hid, l3f in [("h1", 34.0), ("h2", 33.5), ("h3", 34.0), ("h4", None)]:
            db.upsert_result(conn, "r1", hid, {"last_3f": l3f}, authoritative=True)
        db.recompute_last_3f_rank(conn, "r1")
        ranks = {
            r["horse_id"]: r["last_3f_rank"]
            for r in conn.execute("SELECT horse_id, last_3f_rank FROM results")
        }
    assert ranks["h2"] == 1
    assert ranks["h1"] == 2 and ranks["h3"] == 2  # 同タイムは同順位
    assert ranks["h4"] is None


def test_migration_adds_columns_to_old_schema(tmp_path, monkeypatch):
    import db

    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        """CREATE TABLE results (
            race_id TEXT NOT NULL, horse_id TEXT NOT NULL,
            finish_position INTEGER, finish_time TEXT, margin TEXT,
            last_3f REAL, last_3f_rank INTEGER, passing_order TEXT,
            corner_position TEXT, note TEXT, PRIMARY KEY (race_id, horse_id))"""
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DB_PATH", old)
    db.init_db()  # CREATE IF NOT EXISTS + _migrate
    with db.connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(results)")}
    assert {"jockey", "popularity", "win_odds", "horse_weight", "weight_carry"} <= cols


def test_playbook_key():
    import db

    assert db.playbook_key("tokyo", 2400) == "tokyo-2400"
