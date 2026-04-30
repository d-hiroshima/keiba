"""レース結果（着順・タイム・上がり3F・通過順）を取得して SQLite に保存。

データソース第一候補は netkeiba。Phase 1 では実装スタブ。

使用例:
  python scripts/fetch_results.py 202604030611
  python scripts/fetch_results.py --watchlist
  python scripts/fetch_results.py --horses-from-race 202604030611  # 当該レースの出走馬の過去走を取得
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db  # noqa: E402

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"


def already_fetched_today(race_id: str) -> bool:
    today = date.today().isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind='result'",
            (race_id,),
        ).fetchone()
    return bool(row and row["fetched_at"].startswith(today))


def fetch_one(race_id: str, force: bool) -> int:
    """1 レース分の結果を netkeiba から取得し results テーブルに保存。

    TODO: Phase 1 で実装。
    取得 URL: https://db.netkeiba.com/race/<race_id>
    取得項目:
      - 着順、タイム、着差、通過順（4角まで）、上がり3F、上がり順位
      - 騎手・斤量（出走表になければ）
      - 取消・除外・降着の note
    """
    if not force and already_fetched_today(race_id):
        print(f"  [skip] {race_id} (今日既に取得済み)")
        return 0

    print(f"  [todo] {race_id}: 結果取得は Phase 1 で実装")

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'result', ?)",
            (race_id, datetime.now().isoformat(timespec="seconds")),
        )
    return 0


def fetch_horse_history(horse_id: str, force: bool) -> int:
    """馬の全戦績を取得して results テーブルに保存。

    TODO: Phase 1 で実装。
    取得 URL: https://db.netkeiba.com/horse/<horse_id>
    """
    print(f"  [todo] horse {horse_id}: 全戦績取得は Phase 1 で実装")
    return 0


def horses_in_race(race_id: str) -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT horse_id FROM entries WHERE race_id=?", (race_id,)
        ).fetchall()
    return [r["horse_id"] for r in rows]


def load_watchlist_races() -> list[str]:
    with WATCHLIST_PATH.open(encoding="utf-8") as f:
        wl = json.load(f)
    return list(wl.get("races", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_ids", nargs="*", help="race_id")
    ap.add_argument("--watchlist", action="store_true", help="watchlist.json を一括取得")
    ap.add_argument(
        "--horses-from-race",
        metavar="RACE_ID",
        help="指定レースの出走馬の過去走を全取得",
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()

    if args.horses_from_race:
        horses = horses_in_race(args.horses_from_race)
        if not horses:
            print(f"  [warn] {args.horses_from_race} の出走馬が DB にない（先に fetch_races.py を実行）")
            return
        for h in horses:
            try:
                fetch_horse_history(h, args.force)
            except Exception as e:  # noqa: BLE001
                print(f"  [err]  {h}: {e}")
        return

    race_ids = args.race_ids
    if args.watchlist:
        race_ids = load_watchlist_races()
    if not race_ids:
        ap.error("race_id / --watchlist / --horses-from-race のいずれかが必要")

    total = 0
    for rid in race_ids:
        try:
            total += fetch_one(rid, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {rid}: {e}")
    print(f"完了: {len(race_ids)} レース")


if __name__ == "__main__":
    main()
