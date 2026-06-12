"""レース結果・馬の戦績（着順・タイム・上がり3F・通過順・人気・馬体重）を取得して SQLite に保存。

データ源: keibalab.jp（/db/horse/<id>/ と /db/race/<id>/raceresult.html）。
レース単位取得では払戻（payouts）も保存し、上がり3F順位をローカル計算する。

使用例:
  python3 scripts/fetch_results.py 2020103060                 # 馬の全戦績（horse_id=10桁）
  python3 scripts/fetch_results.py 202605030811               # 1レースの全着順＋払戻（race_id=12桁）
  python3 scripts/fetch_results.py --horses-from-race 202605030811  # 当該レース出走馬の過去走

終了コード: 1件でも取得失敗があれば 1（CI でサイレント失敗させない）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import (  # noqa: E402
    connect,
    init_db,
    recompute_last_3f_rank,
    upsert_race,
    upsert_result,
)
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

    data = keibalab.fetch_horse(horse_id, force=force)
    career = data.get("career", [])
    if not career:
        # 未出走馬は正当にゼロ件があり得るため、エラーにせず警告に留める
        print(f"  [warn] horse {horse_id}: 戦績が取得できず（未出走の可能性。保存スキップ）")
        return 0

    saved = 0
    now = _now()
    with connect() as conn:
        for r in career:
            if not r.get("race_id"):
                continue
            # 戦績表由来は略記情報: 既存（結果ページ由来）の値を上書きしない
            upsert_race(conn, {**r, "fetched_at": now}, authoritative=False)
            upsert_result(conn, r["race_id"], horse_id, r, authoritative=False)
            saved += 1
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'result', ?)",
            (horse_id, now),
        )
    print(f"  [ok]   horse {horse_id}: {data.get('name')} {saved} 走を results に保存")
    return saved


# --------------------------------------------------------------------------- #
# 1レースの全着順（/db/race/<id>/raceresult.html）→ races + results + payouts
# --------------------------------------------------------------------------- #
def fetch_one(race_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(
            conn, race_id, "race_result",
            "SELECT COUNT(*) FROM results WHERE race_id=?", race_id,
        ):
            print(f"  [skip] {race_id} (結果取得済み)")
            return 0

    data = keibalab.fetch_race_result(race_id, force=force)
    runners = data.get("runners", [])
    if not runners:
        raise keibalab.ParseError(f"{race_id}: 出走馬が1頭も取得できなかった")

    race = data["race"]
    now = _now()
    with connect() as conn:
        upsert_race(conn, {**race, "fetched_at": now}, authoritative=True)
        for ru in runners:
            upsert_result(conn, race_id, ru["horse_id"], ru, authoritative=True)
        for p in data.get("payouts", []):
            conn.execute(
                """INSERT OR REPLACE INTO payouts
                (race_id, bet_type, combination, payout_yen) VALUES (?,?,?,?)""",
                (race_id, p["bet_type"], p["combination"], p["payout_yen"]),
            )
        recompute_last_3f_rank(conn, race_id)
        conn.execute(
            "INSERT OR REPLACE INTO fetch_log (target_id, kind, fetched_at) VALUES (?, 'race_result', ?)",
            (race_id, now),
        )
    n_pay = len(data.get("payouts", []))
    print(f"  [ok]   {race_id}: {race.get('race_name')} {len(runners)} 頭の結果と払戻 {n_pay} 件を保存")
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
    data = keibalab.fetch_race_result(race_id)
    return [ru["horse_id"] for ru in data.get("runners", [])]


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

    failures = 0
    targets = list(args.ids)
    if args.horses_from_race:
        try:
            targets.extend(horses_in_race(args.horses_from_race))
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  [err]  {args.horses_from_race}: 出走馬リスト取得失敗 {e}")
    if not targets and not failures:
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
                failures += 1
                print(f"  [err]  不明なID（10桁=horse/12桁=race）: {t}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  [err]  {t}: {e}")
    print(f"完了: レース {n_race} / 馬 {n_horse} / 失敗 {failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
