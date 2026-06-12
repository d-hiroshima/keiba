"""SQLite ヘルパ。race.db のスキーマ定義・接続管理・LLM 向けクエリ CLI。

CLI（分析セッションから直接使う）:
  python3 scripts/db.py                      # スキーマ初期化（CI のスモークテスト互換）
  python3 scripts/db.py schema-doc           # docs/db-schema.md の内容を stdout に生成
  python3 scripts/db.py card <race_id>       # レースカード（出走表＋各馬の直近5走）を Markdown で
  python3 scripts/db.py history <horse_id>   # 馬の全戦績（ペース文脈付き）を Markdown で
  python3 scripts/db.py sire-stats <sire_id> # 種牡馬の産駒成績（pedigree_stats）を表示
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "race.db"

SCHEMA = """
-- =====================================================================
-- データ取り扱い方針:
--   このスキーマは「不変データ」のみを永続化する。
--   発走前に動く値（事前オッズ・事前馬体重・馬場/天候の予想・調教気配）は
--   永続化せず、必要時に macro-scout が WebFetch で都度取得する。
--   ただし「レース確定後の値」（確定人気・確定単勝オッズ・当日馬体重・
--   確定馬場/天候・払戻）は不変データなので results/races/payouts に保存する。
--   詳細は CLAUDE.md「データ取り扱い方針」を参照。
-- =====================================================================

-- レース基本情報（不変）
-- weather と track_condition は「レース後の確定値」のみ書き込む。
-- レース前の予想・速報は DB に入れず、macro-scout が都度取得する。
CREATE TABLE IF NOT EXISTS races (
    race_id         TEXT PRIMARY KEY,        -- keibalab 日付ベース 12桁: YYYYMMDD+場(2)+R(2)
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    course          TEXT NOT NULL,           -- 'tokyo' / 'nakayama' / ...
    course_no       INTEGER,                 -- 開催回（例: 4回東京なら 4）
    day_no          INTEGER,                 -- 何日目（例: 6日目なら 6）
    race_no         INTEGER NOT NULL,        -- 1〜12R
    race_name       TEXT,
    grade           TEXT,                    -- 'GI' / 'GII' / 'GIII' / 'OP' / 'L' / null
    race_class      TEXT,                    -- '3歳オープン' / '4歳以上2勝クラス' など
    surface         TEXT NOT NULL,           -- 'turf' / 'dirt' / 'jump'
    distance        INTEGER NOT NULL,        -- メートル
    direction       TEXT,                    -- 'right' / 'left' / 'straight'
    weather         TEXT,                    -- レース後の確定値のみ。前は scout が取得
    track_condition TEXT,                    -- レース後の確定値のみ。前は scout が取得
    post_time       TEXT,                    -- 発走時刻 HH:MM
    field_size      INTEGER,                 -- 頭数（戦績表・結果ページ由来の確定値）
    pace_front_3f   REAL,                    -- レース前半3F（確定値）
    pace_last_3f    REAL,                    -- レース上がり3F（確定値）
    pace_class      TEXT,                    -- 'H' / 'M' / 'S'（keibalab 戦績表のペース区分）
    lap_times       TEXT,                    -- 200m毎ラップ '12.3-10.8-...'（結果ページ由来）
    fetched_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_races_date   ON races(date);
CREATE INDEX IF NOT EXISTS idx_races_course ON races(course, distance);

-- 出走表（出馬投票締切後の確定情報のみ。出走馬一頭ずつ）
-- 事前オッズ・事前馬体重は入れない（揮発データのため scout が WebFetch）
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

-- レース結果（確定値のみ＝すべて不変データ）
CREATE TABLE IF NOT EXISTS results (
    race_id           TEXT NOT NULL,
    horse_id          TEXT NOT NULL,
    finish_position   INTEGER,               -- 着順（1〜、降着・取消は NULL）
    finish_time       TEXT,                  -- 1:23.4 形式
    margin            TEXT,                  -- 着差
    last_3f           REAL,                  -- 上がり3F秒
    last_3f_rank      INTEGER,               -- 上がり3F順位（レース全頭取得時にローカル計算）
    passing_order     TEXT,                  -- 通過順 例: '4-3-3-2'
    corner_position   TEXT,                  -- 4角通過順位（テキスト）
    jockey            TEXT,                  -- そのレースで騎乗した騎手（確定値）
    trainer           TEXT,                  -- 当時の厩舎
    weight_carry      REAL,                  -- 斤量（確定値）
    popularity        INTEGER,               -- 確定人気（レース後は不変）
    win_odds          REAL,                  -- 確定単勝オッズ（レース後は不変）
    horse_weight      INTEGER,               -- 当日馬体重 kg（確定値）
    horse_weight_diff INTEGER,               -- 馬体重前走比
    note              TEXT,                  -- '降着' / '失格' / '取消' など
    PRIMARY KEY (race_id, horse_id)
);

CREATE INDEX IF NOT EXISTS idx_results_horse ON results(horse_id);

-- 払戻（レース確定後の不変データ。予想の事後採点 score_prediction.py が参照）
CREATE TABLE IF NOT EXISTS payouts (
    race_id     TEXT NOT NULL,
    bet_type    TEXT NOT NULL,               -- 'win'/'place'/'wakuren'/'umaren'/'wide'/'umatan'/'sanrenpuku'/'sanrentan'
    combination TEXT NOT NULL,               -- '17' / '13-17' / '17-13-5'（数字昇順、馬単・三連単のみ着順）
    payout_yen  INTEGER NOT NULL,            -- 100円あたり払戻
    PRIMARY KEY (race_id, bet_type, combination)
);

-- 馬の基本情報・血統
CREATE TABLE IF NOT EXISTS horses (
    horse_id            TEXT PRIMARY KEY,    -- 10桁（netkeiba/keibalab 共通）
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

-- 種牡馬別のコース・距離・馬場別産駒成績（ローカル results×horses×races 集計）
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
    n_horses        INTEGER,                 -- 集計対象の産駒頭数（N=1 の個体成績を誤用しないため）
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

# 既存 DB への後方互換マイグレーション（CREATE TABLE IF NOT EXISTS は列追加しないため）
_MIGRATIONS: dict[str, dict[str, str]] = {
    "races": {
        "field_size": "INTEGER",
        "pace_front_3f": "REAL",
        "pace_last_3f": "REAL",
        "pace_class": "TEXT",
        "lap_times": "TEXT",
    },
    "results": {
        "jockey": "TEXT",
        "trainer": "TEXT",
        "weight_carry": "REAL",
        "popularity": "INTEGER",
        "win_odds": "REAL",
        "horse_weight": "INTEGER",
        "horse_weight_diff": "INTEGER",
    },
    "pedigree_stats": {
        "n_horses": "INTEGER",
    },
}


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    for table, cols in _MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


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


# --------------------------------------------------------------------------- #
# upsert（NULL 上書き防止）
#   ソースによって取れるカラムが違う（馬ページ戦績はペース・人気あり/オッズなし、
#   結果ページはオッズあり/ペース区分なし）。素朴な INSERT OR REPLACE は
#   片方のソースが持たないカラムを NULL で潰すため、COALESCE で合成する。
#   authoritative=True : 新しい非NULL値が勝つ（結果ページ＝確定情報）
#   authoritative=False: 既存の非NULL値が勝つ（戦績表＝略記情報で補完のみ）
# --------------------------------------------------------------------------- #
_RACE_COLS = [
    "date", "course", "course_no", "day_no", "race_no", "race_name", "grade",
    "race_class", "surface", "distance", "direction", "weather",
    "track_condition", "post_time", "field_size", "pace_front_3f",
    "pace_last_3f", "pace_class", "lap_times", "fetched_at",
]

_RESULT_COLS = [
    "finish_position", "finish_time", "margin", "last_3f", "last_3f_rank",
    "passing_order", "corner_position", "jockey", "trainer", "weight_carry",
    "popularity", "win_odds", "horse_weight", "horse_weight_diff", "note",
]


def _upsert(conn, table: str, key_cols: dict, data_cols: list[str],
            data: dict, authoritative: bool) -> None:
    cols = list(key_cols) + data_cols
    placeholders = ",".join("?" for _ in cols)
    if authoritative:
        sets = ",".join(f"{c}=COALESCE(excluded.{c},{table}.{c})" for c in data_cols)
    else:
        sets = ",".join(f"{c}=COALESCE({table}.{c},excluded.{c})" for c in data_cols)
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT ({','.join(key_cols)}) DO UPDATE SET {sets}"
    )
    conn.execute(sql, [*key_cols.values(), *[data.get(c) for c in data_cols]])


def upsert_race(conn, r: dict, authoritative: bool) -> bool:
    """races へ NULL 安全 upsert。surface/distance 不明（NOT NULL 不可）は False。"""
    race_id = r.get("race_id")
    if not race_id or not (r.get("surface") and r.get("distance")):
        return False
    if not r.get("race_no"):
        r = {**r, "race_no": parse_race_id(race_id)["race_no"]}
    _upsert(conn, "races", {"race_id": race_id}, _RACE_COLS, r, authoritative)
    return True


def upsert_result(conn, race_id: str, horse_id: str, r: dict,
                  authoritative: bool) -> None:
    """results へ NULL 安全 upsert。"""
    _upsert(
        conn, "results", {"race_id": race_id, "horse_id": horse_id},
        _RESULT_COLS, r, authoritative,
    )


def recompute_last_3f_rank(conn, race_id: str) -> None:
    """レース全頭の last_3f からローカルで順位を計算して埋める。"""
    rows = conn.execute(
        "SELECT horse_id, last_3f FROM results "
        "WHERE race_id=? AND last_3f IS NOT NULL ORDER BY last_3f",
        (race_id,),
    ).fetchall()
    rank, prev = 0, None
    for i, row in enumerate(rows, start=1):
        if row["last_3f"] != prev:
            rank, prev = i, row["last_3f"]
        conn.execute(
            "UPDATE results SET last_3f_rank=? WHERE race_id=? AND horse_id=?",
            (rank, race_id, row["horse_id"]),
        )


def parse_race_id(race_id: str) -> dict:
    """race_id を分解（keibalab 形式 = 日付ベース）。

    本プロジェクトの正規 race_id は keibalab のデータベース URL に一致する
    日付ベース形式: ``YYYYMMDD + 場コード(2) + R(2)``（計 12 桁）。
    netkeiba の ``年+場+回+日+R`` 形式とは別物（相互変換にはカレンダー照合が要る）。

    例: '202605030811' →
        {date: '2026-05-03', year: 2026, course_code: '08',
         course: 'kyoto', race_no: 11}

    開催回(course_no)・何日目(day_no)・距離 は race_id に含まれないため、
    取得元ページの本文から補完する（fetcher 側で埋める）。

    course_code:
        01=札幌, 02=函館, 03=福島, 04=新潟, 05=東京,
        06=中山, 07=中京, 08=京都, 09=阪神, 10=小倉（地方/海外は範囲外）
    """
    if len(race_id) != 12 or not race_id.isdigit():
        raise ValueError(f"invalid race_id: {race_id} (expected 12 digits)")
    y, m, d = int(race_id[:4]), int(race_id[4:6]), int(race_id[6:8])
    course_code = race_id[8:10]
    return {
        "date": f"{y:04d}-{m:02d}-{d:02d}",
        "year": y,
        "course_code": course_code,
        "course": course_code_to_name(course_code),
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


# --------------------------------------------------------------------------- #
# LLM 向けクエリ CLI
# --------------------------------------------------------------------------- #
_HISTORY_SQL = """
SELECT ra.date, ra.course, ra.distance, ra.surface, ra.grade, ra.race_name,
       ra.track_condition, ra.field_size, ra.pace_class,
       ra.pace_front_3f, ra.pace_last_3f,
       re.finish_position, re.popularity, re.win_odds, re.passing_order,
       re.last_3f, re.last_3f_rank, re.horse_weight, re.horse_weight_diff,
       re.jockey, re.weight_carry, re.note
FROM results re JOIN races ra ON ra.race_id = re.race_id
WHERE re.horse_id = ?
ORDER BY ra.date DESC
LIMIT ?
"""


def _fmt(v, suffix: str = "") -> str:
    return f"{v}{suffix}" if v is not None else "-"


def _history_rows(conn, horse_id: str, limit: int) -> list[str]:
    """過去走を 1 行/走の Markdown 表行に整形。"""
    out = []
    for r in conn.execute(_HISTORY_SQL, (horse_id, limit)):
        pace = r["pace_class"] or (
            f"{r['pace_front_3f']}-{r['pace_last_3f']}"
            if r["pace_front_3f"] and r["pace_last_3f"] else "-"
        )
        fin = _fmt(r["finish_position"]) if r["finish_position"] else (r["note"] or "-")
        wd = r["horse_weight_diff"]
        weight = f"{r['horse_weight']}({wd:+d})" if r["horse_weight"] is not None and wd is not None else _fmt(r["horse_weight"])
        out.append(
            f"| {r['date']} | {r['course']}{r['distance']}{r['surface'][:1] if r['surface'] else ''}"
            f" {_fmt(r['grade'])} | {_fmt(r['track_condition'])} | {fin}/{_fmt(r['field_size'])}"
            f" | {_fmt(r['popularity'])}人 | {_fmt(r['passing_order'])} | {_fmt(r['last_3f'])}"
            f"({_fmt(r['last_3f_rank'])}位) | {pace} | {weight} | {_fmt(r['jockey'])} |"
        )
    return out


_HISTORY_HEADER = (
    "| 日付 | 条件 | 馬場 | 着/頭 | 人気 | 通過 | 上り(順) | ペース | 馬体重 | 騎手 |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def cmd_card(race_id: str, n_history: int = 5) -> str:
    """レースカード: races + entries + 各馬の直近 n 走（ペース文脈付き）。"""
    lines: list[str] = []
    with connect() as conn:
        race = conn.execute(
            "SELECT * FROM races WHERE race_id=?", (race_id,)
        ).fetchone()
        if race:
            head = (
                f"# {race['race_name'] or race_id}"
                f"（{race['course']} {race['distance']}m {race['surface']},"
                f" {race['grade'] or race['race_class'] or '-'}）"
            )
            meta = (
                f"日付: {race['date']}（発走 {race['post_time'] or '不明'}）"
                f" / 頭数 {race['field_size'] or '不明'}"
                f" / 馬場 {race['track_condition'] or '未確定'}"
                f" / 天候 {race['weather'] or '未確定'}"
            )
            lines += [head, meta, ""]
        else:
            lines += [f"# {race_id}（races 未取得。fetch_races.py を先に実行）", ""]

        entries = conn.execute(
            """SELECT e.*, h.sire, h.broodmare_sire FROM entries e
               LEFT JOIN horses h ON h.horse_id = e.horse_id
               WHERE e.race_id=? ORDER BY e.post_position""",
            (race_id,),
        ).fetchall()
        if not entries:
            lines.append("（entries 未取得 — `python3 scripts/fetch_races.py "
                         f"{race_id}` を先に実行）")
            return "\n".join(lines)

        lines += [
            "## 出走表",
            "| 馬番 | 枠 | 馬名 | 性齢 | 斤量 | 騎手 | 厩舎 | 父 | 母父 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for e in entries:
            lines.append(
                f"| {_fmt(e['post_position'])} | {_fmt(e['gate'])} | {e['horse_name']}"
                f" | {_fmt(e['sex'])}{_fmt(e['age'])} | {_fmt(e['weight_carry'])}"
                f" | {_fmt(e['jockey'])} | {_fmt(e['trainer'])} | {_fmt(e['sire'])}"
                f" | {_fmt(e['broodmare_sire'])} |"
            )
        lines.append("")

        lines.append(f"## 各馬の直近{n_history}走")
        for e in entries:
            lines += ["", f"### {e['post_position']} {e['horse_name']}（{e['horse_id']}）"]
            rows = _history_rows(conn, e["horse_id"], n_history)
            if rows:
                lines += [_HISTORY_HEADER, *rows]
            else:
                lines.append("（戦績未取得 — `python3 scripts/fetch_results.py "
                             f"{e['horse_id']}` で取得）")
    return "\n".join(lines)


def cmd_history(horse_id: str, limit: int = 20) -> str:
    with connect() as conn:
        h = conn.execute("SELECT * FROM horses WHERE horse_id=?", (horse_id,)).fetchone()
        name = h["name"] if h else horse_id
        lines = [f"# {name}（{horse_id}）"]
        if h:
            lines.append(f"父 {h['sire']} / 母父 {h['broodmare_sire']} / 生年月日 {h['birthday']}")
        lines += ["", _HISTORY_HEADER]
        rows = _history_rows(conn, horse_id, limit)
        lines += rows if rows else ["（戦績未取得）"]
    return "\n".join(lines)


def cmd_sire_stats(sire_id: str) -> str:
    with connect() as conn:
        rows = conn.execute(
            """SELECT * FROM pedigree_stats WHERE sire_id=?
               ORDER BY surface, course, distance, track_condition""",
            (sire_id,),
        ).fetchall()
    if not rows:
        return (f"pedigree_stats に {sire_id} なし"
                "（fetch_pedigree.py --sire-stats で集計を先に実行）")
    lines = [
        f"# 産駒成績: {rows[0]['sire_name'] or sire_id}",
        "",
        "| コース | 距離 | 馬場 | 出走 | 勝-2-3 | 勝率 | 連対率 | 複勝率 | 頭数 | 注意 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        warn = "小標本" if r["starts"] < 5 else ""
        lines.append(
            f"| {r['course']} | {r['distance']} | {r['track_condition'] or '全'}"
            f" | {r['starts']} | {r['wins']}-{r['seconds']}-{r['thirds']}"
            f" | {r['win_rate']:.0%} | {r['place_rate']:.0%} | {r['show_rate']:.0%}"
            f" | {_fmt(r['n_horses'])} | {warn} |"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# schema-doc 生成（docs/db-schema.md の正。CI で diff チェック）
# --------------------------------------------------------------------------- #
_VERIFIED_QUERIES = """\
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
"""


def cmd_schema_doc() -> str:
    lines = [
        "# DB スキーマ（自動生成）",
        "",
        "> **このファイルは編集禁止。** `python3 scripts/db.py schema-doc > docs/db-schema.md`"
        " で再生成する（CI が drift を検出）。スキーマの定義は `scripts/db.py` の SCHEMA。",
        "",
    ]
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        for t in tables:
            lines += [f"## {t}", "", "| カラム | 型 | PK |", "|---|---|---|"]
            for c in conn.execute(f"PRAGMA table_info({t})"):
                lines.append(f"| {c[1]} | {c[2]} | {'✓' if c[5] else ''} |")
            lines.append("")
    lines.append(_VERIFIED_QUERIES)
    return "\n".join(lines)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("init")
    sub.add_parser("schema-doc")
    p = sub.add_parser("card")
    p.add_argument("race_id")
    p.add_argument("--history", type=int, default=5)
    p = sub.add_parser("history")
    p.add_argument("horse_id")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("sire-stats")
    p.add_argument("sire_id")
    args = ap.parse_args()

    if args.cmd in (None, "init"):
        init_db()
        print(f"Initialized {DB_PATH}")
    elif args.cmd == "schema-doc":
        print(cmd_schema_doc())
    elif args.cmd == "card":
        init_db()
        print(cmd_card(args.race_id, args.history))
    elif args.cmd == "history":
        init_db()
        print(cmd_history(args.horse_id, args.limit))
    elif args.cmd == "sire-stats":
        init_db()
        print(cmd_sire_stats(args.sire_id))


if __name__ == "__main__":
    main()
