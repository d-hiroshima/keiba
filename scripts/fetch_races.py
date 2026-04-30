"""出走表とオッズを取得して SQLite に保存。

データソース第一候補は netkeiba。Phase 1 では実装スタブ。

使用例:
  python scripts/fetch_races.py 202604030611
  python scripts/fetch_races.py --watchlist
  python scripts/fetch_races.py 202604030611 --force
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db, parse_race_id, course_code_to_name  # noqa: E402

WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "watchlist.json"


def already_fetched_today(race_id: str, kind: str = "race") -> bool:
    today = date.today().isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT fetched_at FROM fetch_log WHERE target_id=? AND kind=?",
            (race_id, kind),
        ).fetchone()
    return bool(row and row["fetched_at"].startswith(today))


def fetch_one(race_id: str, force: bool) -> int:
    """1 レース分の出走表（不変部分）を netkeiba から取得し DB に保存。

    取得対象は **不変データのみ**:
      races: コース・距離・グレード・発走時刻
      entries: 馬番・枠・斤量・騎手・厩舎・性齢

    取得しないデータ（揮発、macro-scout が WebFetch する）:
      - オッズ・人気
      - 馬体重・前走比
      - 馬場発表・天候の予報
      - 調教気配・直前の乗り替わり

    TODO: Phase 1 で実装。
    netkeiba.com の以下 URL を取得する想定:
      - 出馬表: https://race.netkeiba.com/race/shutuba.html?race_id=<race_id>
      （オッズページは取得しない）

    実装上の注意:
    - rate limit: 連続取得は 2-3 秒スリープ
    - User-Agent: 通常ブラウザ相当の UA を設定
    - robots.txt と利用規約を都度確認
    - JRA-VAN Data Lab に切り替える場合は import_jravan_csv.py を使う
    """
    if not force and already_fetched_today(race_id):
        print(f"  [skip] {race_id} (今日既に取得済み)")
        return 0

    parts = parse_race_id(race_id)
    course = course_code_to_name(parts["course_code"])

    # === ここから netkeiba スクレイピング実装（未実装）===
    # import requests
    # from bs4 import BeautifulSoup
    # url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    # res = requests.get(url, headers={"User-Agent": "Mozilla/5.0 ..."}, timeout=10)
    # soup = BeautifulSoup(res.text, "lxml")
    # ... races テーブル / entries テーブルへ INSERT
    # ====================================================

    print(f"  [todo] {race_id}: ({course}, R{parts['race_no']}) 取得処理は Phase 1 で実装")

    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'race', ?)",
            (race_id, datetime.now().isoformat(timespec="seconds")),
        )
    return 0


def load_watchlist() -> list[str]:
    with WATCHLIST_PATH.open(encoding="utf-8") as f:
        wl = json.load(f)
    return list(wl.get("races", []))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("race_ids", nargs="*", help="race_id（例: 202604030611）")
    ap.add_argument("--watchlist", action="store_true", help="watchlist.json を一括取得")
    ap.add_argument("--force", action="store_true", help="同日内でも再取得")
    args = ap.parse_args()

    init_db()

    race_ids = args.race_ids
    if args.watchlist:
        race_ids = load_watchlist()
    if not race_ids:
        ap.error("race_id または --watchlist が必要")

    total = 0
    for rid in race_ids:
        try:
            total += fetch_one(rid, args.force)
        except Exception as e:  # noqa: BLE001
            print(f"  [err]  {rid}: {e}")
    print(f"完了: {len(race_ids)} レース、{total} 行追加")


if __name__ == "__main__":
    main()
