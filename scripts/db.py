"""SQLite ヘルパ。race.db のスキーマ定義と接続管理。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "race.db"

SCHEMA = """
-- =====================================================================
-- データ取り扱い方針:
--   このスキーマは「不変データ」のみを永続化する。
--   揮発データ（オッズ・馬体重・馬場発表・天候・調教気配・直前の乗り替わり）は
--   永続化せず、必要時に macro-scout が WebFetch で都度取得する。
--   詳細は CLAUDE.md「データ取り扱い方針」を参照。
-- =====================================================================

-- レース基本情報（不変）
-- weather と track_condition は「レース後の確定値」のみ書き込む。
-- レース前の予想・速報は DB に入れず、macro-scout が都度取得する。
CREATE TABLE IF NOT EXISTS races (
    race_id         TEXT PRIMARY KEY,        -- netkeiba 形式 12桁: 202604030611
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    course          TEXT NOT NULL,           -- 'tokyo' / 'nakayama' / ...
    course_no       INTEGER,                 -- 開催回（例: 4回東京なら 4）
    day_no          INTEGER,                 -- 何日目（例: 6日目なら 6）
    race_no         INTEGER NOT NULL,        -- 1〜12R
    race_name       TEXT,
    grade           TEXT,                    -- 'GI' / 'GII' / 'GIII' / 'OP' / 'L' / null
    race_class      TEXT,                    -- '3勝' / '2勝' / '1勝' / '未勝利' / '新馬' など
    surface         TEXT NOT NULL,           -- 'turf' / 'dirt' / 'jump'
    distance        INTEGER NOT NULL,        -- メートル
    direction       TEXT,                    -- 'right' / 'left' / 'straight'
    weather         TEXT,                    -- レース後の確定値のみ。前は scout が取得
    track_condition TEXT,                    -- レース後の確定値のみ。前は scout が取得
    post_time       TEXT,                    -- 発走時刻 HH:MM
    fetched_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_races_date   ON races(date);
CREATE INDEX IF NOT EXISTS idx_races_course ON races(course, distance);

-- 出走表（出馬投票締切後の確定情報のみ。出走馬一頭ずつ）
-- ここに オッズ・人気・馬体重・前走比 は入れない（揮発データのため scout が WebFetch）
CREATE TABLE IF NOT EXISTS entries (
    race_id         TEXT NOT NULL,
    horse_id        TEXT NOT NULL,
    horse_name      TEXT,
    post_position   INTEGER,                 -- 馬番
    gate            INTEGER,                 -- 枠番
    sex             TEXT,                    -- '牡' / '牝' / 'セ'
    age             INTEGER,
    weight_carry    REAL,                    -- 斤量（出馬投票後ほぼ確定）
    jockey          TEXT,                    -- 直前の乗り替わりがあり得るが基本確定
    trainer         TEXT,
    PRIMARY KEY (race_id, horse_id)
);

CREATE INDEX IF NOT EXISTS idx_entries_horse ON entries(horse_id);

-- レース結果
CREATE TABLE IF NOT EXISTS results (
    race_id         TEXT NOT NULL,
    horse_id        TEXT NOT NULL,
    finish_position INTEGER,                 -- 着順（1〜、降着・取消は NULL）
    finish_time     TEXT,                    -- 1:23.4 形式
    margin          TEXT,                    -- 着差
    last_3f         REAL,                    -- 上がり3F秒
    last_3f_rank    INTEGER,                 -- 上がり3F順位
    passing_order   TEXT,                    -- 通過順 例: '4-3-3-2'
    corner_position TEXT,                    -- 4角通過順位（テキスト）
    note            TEXT,                    -- '降着' / '失格' / '取消' など
    PRIMARY KEY (race_id, horse_id)
);

CREATE INDEX IF NOT EXISTS idx_results_horse ON results(horse_id);

-- 馬の基本情報・血統
CREATE TABLE IF NOT EXISTS horses (
    horse_id            TEXT PRIMARY KEY,    -- netkeiba 形式 10桁
    name                TEXT,
    birthday            TEXT,
    sex                 TEXT,
    color               TEXT,
    sire                TEXT,                -- 父
    sire_id             TEXT,
    dam                 TEXT,                -- 母
    dam_id              TEXT,
    broodmare_sire      TEXT,                -- 母父
    broodmare_sire_id   TEXT,
    grandsire           TEXT,                -- 父父
    breeder             TEXT,
    owner               TEXT,
    fetched_at          TEXT
);

-- 種牡馬別のコース・距離・馬場別産駒成績（集計）
-- データ分析の高速化のため `pedigree_stats` に集計済みの値を持つ
CREATE TABLE IF NOT EXISTS pedigree_stats (
    sire_id         TEXT NOT NULL,
    sire_name       TEXT,
    course          TEXT NOT NULL,
    distance        INTEGER NOT NULL,
    surface         TEXT NOT NULL,
    track_condition TEXT,                    -- 馬場別、null = 全馬場集計
    starts          INTEGER NOT NULL,
    wins            INTEGER NOT NULL,
    seconds         INTEGER NOT NULL,
    thirds          INTEGER NOT NULL,
    win_rate        REAL,
    place_rate      REAL,
    show_rate       REAL,
    fetched_at      TEXT,
    PRIMARY KEY (sire_id, course, distance, surface, track_condition)
);

-- 取得ログ（同日内スキップ判定用）
CREATE TABLE IF NOT EXISTS fetch_log (
    target_id   TEXT NOT NULL,               -- race_id / horse_id / sire_id
    kind        TEXT NOT NULL,               -- 'race' | 'result' | 'pedigree' | 'pedigree_stats'
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (target_id, kind)
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def parse_race_id(race_id: str) -> dict:
    """netkeiba 形式の race_id を分解。

    例: '202604030611' →
        {year: 2026, course_code: '04', course_no: 03, day_no: 06, race_no: 11}

    course_code:
        01=札幌, 02=函館, 03=福島, 04=新潟, 05=東京,
        06=中山, 07=中京, 08=京都, 09=阪神, 10=小倉
    """
    if len(race_id) != 12 or not race_id.isdigit():
        raise ValueError(f"invalid race_id: {race_id} (expected 12 digits)")
    return {
        "year": int(race_id[:4]),
        "course_code": race_id[4:6],
        "course_no": int(race_id[6:8]),
        "day_no": int(race_id[8:10]),
        "race_no": int(race_id[10:12]),
    }


COURSE_CODE_MAP = {
    "01": "sapporo",
    "02": "hakodate",
    "03": "fukushima",
    "04": "niigata",
    "05": "tokyo",
    "06": "nakayama",
    "07": "chukyo",
    "08": "kyoto",
    "09": "hanshin",
    "10": "kokura",
}


def course_code_to_name(code: str) -> str:
    return COURSE_CODE_MAP.get(code, "unknown")


def playbook_key(course: str, distance: int) -> str:
    """`<course>-<distance>` のプレイブックキー。"""
    return f"{course}-{distance}"


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
