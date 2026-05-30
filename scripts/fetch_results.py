"""レース結果・馬の戦績（着順・タイム・上がり3F・通過順）を取得して SQLite に保存。

データ源: keibalab.jp（/db/horse/<id>/ と /db/race/<id>/raceresult.html）。

使用例:
  python scripts/fetch_results.py 2020103060                 # 馬の全戦績（horse_id=10桁）
  python scripts/fetch_results.py 202605030811               # 1レースの全着順（race_id=12桁）
  python scripts/fetch_results.py --horses-from-race 202605030811  # 当該レース出走馬の過去走
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db, parse_race_id  # noqa: E402
import keibalab  # noqa: E402


# --------------------------------------------------------------------------- #
# dedup: fetch_log だけでなく実データ行の存在も確認（空ログの罠を回避）
# --------------------------------------------------------------------------- #
def _done_today(conn, target_id: str, kind: str, count_sql: str, count_arg) -> bool:
    has_row = conn.execute(count_sql, (count_arg,)).fetchone()[0] > 0
    if not has_row:
        return False
    row = conn.execute(
        "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind=?",
        (target_id, kind),
    ).fetchone()
    return bool(row and row["fetched_at"].startswith(date.today().isoformat()))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _upsert_race(conn, r: dict, authoritative: bool) -> None:
    """races テーブルへ。authoritative=True は OR REPLACE（レースページ由来の確定）、
    False は OR IGNORE（戦績由来。略称なので既存を上書きしない）。"""
    if not r.get("race_id") or not keibalab.is_jra_race_id(r["race_id"]):
        return
    if not (r.get("surface") and r.get("distance")):
        return  # NOT NULL 制約を満たせないものはスキップ
    verb = "INSERT OR REPLACE" if authoritative else "INSERT OR IGNORE"
    conn.execute(
        f"""{verb} INTO races
        (race_id, date, course, course_no, day_no, race_no, race_name, grade,
         surface, distance, direction, weather, track_condition, post_time, fetched_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            r["race_id"], r.get("date"), r.get("course"), r.get("course_no"),
            r.get("day_no"), r.get("race_no") or parse_race_id(r["race_id"])["race_no"],
            r.get("race_name"), r.get("grade"), r.get("surface"), r.get("distance"),
            r.get("direction"), r.get("weather"), r.get("track_condition"),
            r.get("post_time"), _now(),
        ),
    )


def _insert_result(conn, race_id: str, horse_id: str, r: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO results
        (race_id, horse_id, finish_position, finish_time, margin, last_3f,
         last_3f_rank, passing_order, corner_position, note)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            race_id, horse_id, r.get("finish_position"), r.get("finish_time"),
            r.get("margin"), r.get("last_3f"), r.get("last_3f_rank"),
            r.get("passing_order"), r.get("corner_position"), r.get("note"),
        ),
    )


# --------------------------------------------------------------------------- #
# 馬の全戦績（/db/horse/<id>/）→ results (+ 過去 races)
# --------------------------------------------------------------------------- #
def fetch_horse_history(horse_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(
            conn, horse_id, "result",
            "SELECT COUNT(*) FROM results WHERE horse_id=?", horse_id,
        ):
            print(f"  [skip] horse {horse_id} (戦績取得済み)")
            return 0
    try:
        data = keibalab.fetch_horse(horse_id, force=force)
    except Exception as e:  # noqa: BLE001
        print(f"  [err]  horse {horse_id}: 取得失敗 {e}")
        return 0

    career = data.get("career", [])
    if not career:
        print(f"  [warn] horse {horse_id}: 戦績が取得できず（保存スキップ）")
        return 0

    saved = 0
    with connect() as conn:
        for r in career:
            if not r.get("race_id"):
                continue
            _upsert_race(conn, r, authoritative=False)
            _insert_result(conn, r["race_id"], horse_id, r)
            saved += 1
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'result', ?)",
            (horse_id, _now()),
        )
    print(f"  [ok]   horse {horse_id}: {data.get('name')} {saved} 走を results に保存")
    return saved


# --------------------------------------------------------------------------- #
# 1レースの全着順（/db/race/<id>/raceresult.html）→ races + results
# --------------------------------------------------------------------------- #
def fetch_one(race_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(
            conn, race_id, "race_result",
            "SELECT COUNT(*) FROM results WHERE race_id=?", race_id,
        ):
            print(f"  [skip] {race_id} (結果取得済み)")
            return 0
    try:
        data = keibalab.fetch_race_result(race_id, force=force)
    except Exception as e:  # noqa: BLE001
        print(f"  [err]  {race_id}: 取得失敗 {e}")
        return 0

    runners = data.get("runners", [])
    if not runners:
        print(f"  [warn] {race_id}: 出走馬が取得できず（保存スキップ）")
        return 0

    race = data["race"]
    with connect() as conn:
        _upsert_race(conn, race, authoritative=True)
        for ru in runners:
            _insert_result(conn, race_id, ru["horse_id"], ru)
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'race_result', ?)",
            (race_id, _now()),
        )
    print(f"  [ok]   {race_id}: {race.get('race_name')} {len(runners)} 頭の結果を保存")
    return len(runners)


# --------------------------------------------------------------------------- #
def horses_in_race(race_id: str) -> list[str]:
    """entries にあればそれを、無ければレース結果ページから出走馬を取得。"""
    with connect() as conn:
        rows = conn.execute(
            "SELECT horse_id FROM entries WHERE race_id=?", (race_id,)
        ).fetchall()
    if rows:
        return [r["horse_id"] for r in rows]
    try:
        data = keibalab.fetch_race_result(race_id)
        return [ru["horse_id"] for ru in data.get("runners", [])]
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] {race_id}: 出走馬取得失敗 {e}")
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="horse_id(10桁) または race_id(12桁)。複数可")
    ap.add_argument(
        "--horses-from-race", metavar="RACE_ID",
        help="指定レースの出走馬の過去走を全取得",
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()

    targets = list(args.ids)
    if args.horses_from_race:
        targets.extend(horses_in_race(args.horses_from_race))
    if not targets:
        ap.error("horse_id / race_id / --horses-from-race のいずれかが必要")

    n_race = n_horse = 0
    for t in list(dict.fromkeys(targets)):
        try:
            if len(t) == 12:
                fetch_one(t, args.force)
                n_race += 1
            elif len(t) == 10:
                fetch_horse_history(t, args.force)
                n_horse += 1
            else:
                print(f"  [warn] 不明なID（10桁=horse/12桁=race）: {t}")
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {t}: {e}")
    print(f"完了: レース {n_race} / 馬 {n_horse}")


if __name__ == "__main__":
    main()
