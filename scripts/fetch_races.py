"""出走表（不変部分）を取得して SQLite に保存。

データ源: keibalab.jp（/db/race/<id>/raceresult.html の出走馬ロスター）。

取得対象は **不変データのみ**:
  races:   コース・距離・グレード・確定馬場/天気（レース後）
  entries: 馬番・枠・斤量・騎手・厩舎・性齢

取得しない（揮発、macro-scout が WebFetch する）:
  オッズ・人気 / 馬体重・前走比 / 馬場・天候の事前予報 / 調教気配・直前の乗り替わり

注意: 既走レースは raceresult.html のロスターから entries を作れる。発走前の出馬表
（未確定レース）は keibalab の別ページが必要（TODO: 出馬表ページ URL を要調査）。

使用例（対象は都度プロンプト/引数で指定）:
  python scripts/fetch_races.py 202605030811
  python scripts/fetch_races.py 202605030811 202602210511   # 複数可
  python scripts/fetch_races.py 202605030811 --force
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db, parse_race_id  # noqa: E402
import keibalab  # noqa: E402


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _done_today(conn, race_id: str) -> bool:
    """entries 行があり、かつ本日 fetch_log 済みなら True（空ログの罠を回避）。"""
    has_row = conn.execute(
        "SELECT COUNT(*) FROM entries WHERE race_id=?", (race_id,)
    ).fetchone()[0] > 0
    if not has_row:
        return False
    row = conn.execute(
        "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind='race'",
        (race_id,),
    ).fetchone()
    return bool(row and row["fetched_at"].startswith(date.today().isoformat()))


def fetch_one(race_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(conn, race_id):
            print(f"  [skip] {race_id} (出走表取得済み)")
            return 0
    try:
        data = keibalab.fetch_race_result(race_id, force=force)
    except Exception as e:  # noqa: BLE001
        print(f"  [err]  {race_id}: 取得失敗 {e}")
        return 0

    runners = data.get("runners", [])
    if not runners:
        print(
            f"  [warn] {race_id}: 出走馬が取得できず（発走前の出馬表は未対応／保存スキップ）"
        )
        return 0

    race = data["race"]
    now = _now()
    with connect() as conn:
        # races（確定値）を upsert
        if keibalab.is_jra_race_id(race_id) and race.get("surface") and race.get("distance"):
            conn.execute(
                """INSERT OR REPLACE INTO races
                (race_id, date, course, course_no, day_no, race_no, race_name, grade,
                 surface, distance, direction, weather, track_condition, post_time, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    race_id, race.get("date"), race.get("course"), race.get("course_no"),
                    race.get("day_no"), race.get("race_no") or parse_race_id(race_id)["race_no"],
                    race.get("race_name"), race.get("grade"), race.get("surface"),
                    race.get("distance"), race.get("direction"), race.get("weather"),
                    race.get("track_condition"), race.get("post_time"), now,
                ),
            )
        for ru in runners:
            conn.execute(
                """INSERT OR REPLACE INTO entries
                (race_id, horse_id, horse_name, post_position, gate, sex, age,
                 weight_carry, jockey, trainer)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    race_id, ru["horse_id"], ru.get("horse_name"), ru.get("post_position"),
                    ru.get("gate"), ru.get("sex"), ru.get("age"), ru.get("weight_carry"),
                    ru.get("jockey"), ru.get("trainer"),
                ),
            )
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'race', ?)",
            (race_id, now),
        )
    print(f"  [ok]   {race_id}: {race.get('race_name')} {len(runners)} 頭の出走表を保存")
    return len(runners)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_ids", nargs="+", help="race_id（例: 202605030811）。複数可")
    ap.add_argument("--force", action="store_true", help="同日内でも再取得")
    args = ap.parse_args()

    init_db()

    race_ids = args.race_ids
    total = 0
    for rid in race_ids:
        try:
            total += fetch_one(rid, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {rid}: {e}")
    print(f"完了: {len(race_ids)} レース / 延べ {total} 頭")


if __name__ == "__main__":
    main()
