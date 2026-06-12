"""出走表（不変部分）を取得して SQLite に保存。

データ源: keibalab.jp
  - 発走前（レース日が今日以降）: /db/race/<id>/umabashira.html（馬柱）
  - 確定後（レース日が過去）   : /db/race/<id>/raceresult.html のロスター
    （結果ページが未確定なら馬柱にフォールバック）

取得対象は **不変データのみ**:
  races:   コース・距離・グレード・発走時刻・確定馬場/天気（レース後のみ）
  entries: 馬番・枠・斤量・騎手・厩舎・性齢

取得しない（揮発、macro-scout が WebFetch する）:
  事前オッズ・人気 / 事前馬体重 / 馬場・天候の予想 / 調教気配・直前の乗り替わり

使用例（対象は都度プロンプト/引数で指定）:
  python3 scripts/fetch_races.py 202605030811
  python3 scripts/fetch_races.py 202605030811 202602210511   # 複数可
  python3 scripts/fetch_races.py 202605030811 --force

終了コード: 1件でも取得失敗があれば 1（CI でサイレント失敗させない）。
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import connect, init_db, parse_race_id, upsert_race  # noqa: E402
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


def _fetch_card_data(race_id: str, force: bool) -> dict:
    """発走前後でソースを使い分けて {'race','runners'} を返す。"""
    is_past = parse_race_id(race_id)["date"] < date.today().isoformat()
    if is_past:
        try:
            return keibalab.fetch_race_result(race_id, force=force)
        except keibalab.ContentNotReadyError:
            # 当日未確定など。馬柱にフォールバック
            return keibalab.fetch_race_card(race_id, force=force)
    return keibalab.fetch_race_card(race_id, force=force)


def fetch_one(race_id: str, force: bool) -> int:
    with connect() as conn:
        if not force and _done_today(conn, race_id):
            print(f"  [skip] {race_id} (出走表取得済み)")
            return 0

    data = _fetch_card_data(race_id, force)
    runners = data.get("runners", [])
    if not runners:
        raise keibalab.ParseError(f"{race_id}: 出走馬が1頭も取得できなかった")

    race = data["race"]
    now = _now()
    with connect() as conn:
        if keibalab.is_jra_race_id(race_id):
            upsert_race(conn, {**race, "fetched_at": now}, authoritative=True)
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

    failures = 0
    total = 0
    for rid in args.race_ids:
        try:
            total += fetch_one(rid, args.force)
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"  [err]  {rid}: {e}")
    print(f"完了: {len(args.race_ids)} レース / 延べ {total} 頭 / 失敗 {failures}")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
