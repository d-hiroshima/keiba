"""競馬ラボ (keibalab.jp/db) スクレイピングクライアント。

データ源として keibalab を使う際の HTTP 取得・キャッシュ・HTML パースを集約する。
fetch_pedigree.py / fetch_results.py / fetch_races.py から共用する。

取得方針（CLAUDE.md「データ取り扱い方針」/ memory: data-source-decision に準拠）:
  - 取得元: keibalab.jp（無料・/db/ は robots 許可・race_id は日付ベース）
  - 礼儀: ブラウザ相当 UA を送る（既定 UA だと 403）。連続取得は最低 _MIN_INTERVAL 秒スリープ
  - fetch-once-then-cache: 不変データは data/cache/ に HTML を保存し再取得を避ける（規約「運営を妨げる行為」回避）
  - 独自指標 α/β/Ω指数 は keibalab の IP。**保存・再配布しない**

keibalab race_id 形式（netkeiba とは別物）:
  YYYYMMDD + 場コード(2, 01-10) + R(2)   例: 202605030811 = 2026-05-03 京都 11R
"""

from __future__ import annotations

import hashlib
import re
import sys
import time
from datetime import date as _dt_date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import COURSE_CODE_MAP, parse_race_id  # noqa: E402

BASE = "https://www.keibalab.jp"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
_MIN_INTERVAL = 2.0  # 連続ライブ取得の最小間隔（秒）
_last_fetch = 0.0

# 場コード（COURSE_CODE_MAP）と parse_race_id は db.py を単一情報源として利用する。
# 「3回京都4」等の日本語場名 → 英語キー
_JP_COURSE = {
    "札幌": "sapporo", "函館": "hakodate", "福島": "fukushima", "新潟": "niigata",
    "東京": "tokyo", "中山": "nakayama", "中京": "chukyo", "京都": "kyoto",
    "阪神": "hanshin", "小倉": "kokura",
}
_GRADE_RE = re.compile(r"[(（]\s*(Ｇ?[ＧG][ⅠⅡⅢ123]|[GL][I1-3]?|Ｌ|OP|オープン|リステッド)\s*[)）]")
_GRADE_NORM = {
    "ＧⅠ": "GI", "ＧⅡ": "GII", "ＧⅢ": "GIII", "GⅠ": "GI", "GⅡ": "GII", "GⅢ": "GIII",
    "G1": "GI", "G2": "GII", "G3": "GIII", "Ｌ": "L", "L": "L",
    "OP": "OP", "オープン": "OP", "リステッド": "L",
}


class ParseError(RuntimeError):
    """HTML 構造が想定と異なり必須テーブルが見つからない（サイト改修の疑い）。"""


class ContentNotReadyError(RuntimeError):
    """ページは取得できたが内容が未確定（例: レース結果が「確定していません」）。"""


# レース結果ページの未確定マーカー。キャッシュ毒（未確定ページの永続化）防止に使う
_NOT_READY_MARKER = "確定していません"


def _looks_not_ready(url: str, html: str) -> bool:
    return "raceresult" in url and _NOT_READY_MARKER in html


# --------------------------------------------------------------------------- #
# HTTP + キャッシュ
# --------------------------------------------------------------------------- #
def _cache_path(url: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.html"


def get_html(url: str, max_age_hours: float = 24.0, force: bool = False) -> str:
    """URL を取得。キャッシュが新しければ再利用。force でキャッシュ無視。

    未確定ページ（結果が「確定していません」）はキャッシュしない／既存キャッシュが
    未確定ならキャッシュ扱いせず再取得する（未確定 HTML の 24h 永続化事故の防止）。
    """
    global _last_fetch
    cp = _cache_path(url)
    if not force and cp.exists():
        age_h = (time.time() - cp.stat().st_mtime) / 3600.0
        if age_h <= max_age_hours:
            cached = cp.read_text(encoding="utf-8")
            if not _looks_not_ready(url, cached):
                return cached

    # 礼儀: 連続ライブ取得の間隔を空ける
    wait = _MIN_INTERVAL - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
    _last_fetch = time.time()
    resp.raise_for_status()
    # keibalab は UTF-8 固定。apparent_encoding は誤判定して文字化けキャッシュを
    # 作ることがある（latin-1 と誤認した実績あり）ため使わない
    resp.encoding = "utf-8"
    html = resp.text
    if _looks_not_ready(url, html):
        # 未確定ページは保存しない（次回も必ずライブで再確認させる）
        return html
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp.write_text(html, encoding="utf-8")
    return html


# --------------------------------------------------------------------------- #
# race_id ヘルパ（keibalab 日付ベース、parse_race_id は db.py から import）
# --------------------------------------------------------------------------- #
def is_jra_race_id(race_id: str) -> bool:
    """中央(JRA)レースか（場コード 01-10）。地方/海外は False。"""
    return (
        len(race_id) == 12 and race_id.isdigit() and race_id[8:10] in COURSE_CODE_MAP
    )


# --------------------------------------------------------------------------- #
# 低レベルパース補助
# --------------------------------------------------------------------------- #
def _id_from_href(href: str, kind: str) -> str | None:
    m = re.search(rf"/db/{kind}/([0-9A-Za-z]+)/", href or "")
    return m.group(1) if m else None


def _clean_name(text: str) -> str:
    """血統馬名から「(◯◯系)2012年度産...」等の注釈を除去。"""
    text = text.replace("\n", "").replace("\t", "").strip()
    for paren in ("(", "（"):
        i = text.find(paren)
        if i > 0:
            text = text[:i]
    return text.strip()


def _clean_race_name(text: str) -> str:
    """レース名セルから末尾のグレード表記 (ＧⅠ) 等のみ除去。馬名用 _clean_name と違い
    レース名中の全角括弧（例: 天皇賞（春））は残す。"""
    text = (text or "").replace("\n", "").replace("\t", "").strip()
    return _GRADE_RE.sub("", text).strip()


def _norm_grade(raw: str) -> str | None:
    m = _GRADE_RE.search(raw or "")
    if not m:
        return None
    token = m.group(1).replace("Ｇ", "G")
    return _GRADE_NORM.get(token) or _GRADE_NORM.get(m.group(1))


def _surface_distance(text: str) -> tuple[str | None, int | None]:
    """'芝3200' / 'ダ1200' / '障3000' → ('turf'|'dirt'|'jump', 3200)."""
    text = (text or "").strip()
    surface = None
    if text.startswith("芝"):
        surface = "turf"
    elif text.startswith(("ダ", "ダート")):
        surface = "dirt"
    elif text.startswith(("障", "障害")):
        surface = "jump"
    m = re.search(r"(\d{3,4})", text)
    return surface, (int(m.group(1)) if m else None)


def _parse_kaisai(text: str) -> tuple[int | None, str | None, int | None]:
    """'3回京都4' → (course_no=3, course='kyoto', day_no=4)."""
    m = re.match(r"\s*(\d+)\s*回\s*(\D+?)\s*(\d+)\s*$", (text or "").strip())
    if not m:
        return None, None, None
    return int(m.group(1)), _JP_COURSE.get(m.group(2).strip()), int(m.group(3))


def _find_table_by_header(soup, required: list[str]):
    """ヘッダ行に required の語をすべて含む最初の table を返す。"""
    for t in soup.find_all("table"):
        first = t.find("tr")
        if not first:
            continue
        cells = [c.get_text(strip=True) for c in first.find_all(["th", "td"])]
        if all(any(req == c for c in cells) for req in required):
            return t
    return None


def _header_index(table) -> dict:
    first = table.find("tr")
    return {
        c.get_text(strip=True): i
        for i, c in enumerate(first.find_all(["th", "td"]))
    }


def _finish_position(text: str) -> tuple[int | None, str | None]:
    """着順セル → (finish_position, note)。中止/取消/除外/失格/降着は note。"""
    text = (text or "").strip()
    if text.isdigit():
        return int(text), None
    for kw in ("中止", "取消", "除外", "失格", "降着", "降", "再"):
        if kw in text:
            return None, text
    return None, (text or None)


# --------------------------------------------------------------------------- #
# 馬ページ: プロフィール + 血統 + 全戦績
# --------------------------------------------------------------------------- #
def fetch_horse(horse_id: str, max_age_hours: float = 12.0, force: bool = False) -> dict:
    """/db/horse/<id>/ を取得しパース。

    returns {
      'horse_id', 'profile': {...}, 'pedigree': {...}, 'career': [ {...}, ... ]
    }
    """
    html = get_html(f"{BASE}/db/horse/{horse_id}/", max_age_hours, force)
    soup = BeautifulSoup(html, "lxml")
    return {
        "horse_id": horse_id,
        "name": _horse_name(soup),
        "profile": _parse_profile(soup),
        "pedigree": _parse_pedigree(soup),
        "career": _parse_career(soup),
    }


def _horse_name(soup) -> str | None:
    t = soup.find("title")
    if not t:
        return None
    # 'ヴェルテンベルク - Wurttemberg - 競走馬データベース | 競馬ラボ'
    return t.get_text(strip=True).split(" - ")[0].strip() or None


def _parse_profile(soup) -> dict:
    """ProfileTable から 生年月日/性別/毛色/調教師/馬主/生産者 を抽出。"""
    out: dict = {}
    table = soup.find("table", class_="ProfileTable") or soup.find("table")
    if not table:
        return out
    kv = {}
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) >= 2:
            kv[cells[0]] = cells[1]
    birth = kv.get("生年月日", "")
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", birth)
    if m:
        out["birthday"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    msex = re.search(r"[（(]([牡牝セ])", birth)
    if msex:
        out["sex"] = msex.group(1)
    out["color"] = kv.get("毛色") or None
    out["trainer"] = (kv.get("調教師") or "").split("(")[0].strip() or None
    out["owner"] = kv.get("馬主") or None
    breeder = kv.get("生産者/産地") or kv.get("生産者") or ""
    out["breeder"] = breeder.split("/")[0].strip() or None
    return out


def _parse_pedigree(soup) -> dict:
    """HorseBloodTable(3代) の /db/breed/ アンカー順から父・父父・母・母父を抽出。

    row-major 14 アンカー: [父,父父,父父父,父父母,父母,父母父,父母母,
                           母,母父,母父父,母父母,母母,母母父,母母母]
    """
    table = soup.find("table", class_="HorseBloodTable")
    out: dict = {}
    if not table:
        return out
    anchors = table.find_all("a", href=re.compile(r"/db/breed/"))
    parsed = [
        {"name": _clean_name(a.get_text()), "id": _id_from_href(a.get("href"), "breed")}
        for a in anchors
    ]

    def at(i: int) -> dict:
        return parsed[i] if 0 <= i < len(parsed) else {"name": None, "id": None}

    if len(parsed) >= 9:  # 3代血統表（14アンカー想定）の固定位置
        sire, grandsire, dam, bms = at(0), at(1), at(7), at(8)
    else:  # 想定外レイアウト: 取れる範囲のベストエフォート
        sire, grandsire, dam, bms = at(0), at(1), {"name": None, "id": None}, {"name": None, "id": None}
    out.update(
        sire=sire["name"], sire_id=sire["id"],
        grandsire=grandsire["name"],
        dam=dam["name"], dam_id=dam["id"],
        broodmare_sire=bms["name"], broodmare_sire_id=bms["id"],
        _anchor_count=len(parsed),
    )
    return out


def _parse_career(soup) -> list[dict]:
    """戦績テーブルを results/races 用の dict 配列に。"""
    table = _find_table_by_header(soup, ["年月日", "着", "レース"])
    if not table:
        return []
    idx = _header_index(table)
    rows = table.find_all("tr")[1:]
    out: list[dict] = []
    for tr in rows:
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < len(idx):
            continue

        def cell(name: str):
            i = idx.get(name)
            return cells[i] if i is not None and i < len(cells) else None

        race_cell = cell("レース")
        race_link = race_cell.find("a", href=re.compile(r"/db/race/")) if race_cell else None
        race_id = _id_from_href(race_link.get("href"), "race") if race_link else None
        if not race_id:
            continue

        fp, note = _finish_position(cell("着").get_text(strip=True) if cell("着") else "")
        surface, distance = _surface_distance(cell("コース").get_text(strip=True) if cell("コース") else "")
        course_no, course, day_no = _parse_kaisai(cell("場").get_text(strip=True) if cell("場") else "")
        passing = None
        pcell = cell("通過順位")
        if pcell:
            nums = [td.get_text(strip=True) for td in pcell.find_all("td")]
            nums = [n for n in nums if n]
            passing = "-".join(nums) if nums else (pcell.get_text(strip=True) or None)

        def txt(name: str):
            c = cell(name)
            return c.get_text(strip=True) if c else None

        last3f = txt("上り")
        pace_front, pace_last, pace_class = _parse_pace(txt("ペース"))
        horse_weight, horse_weight_diff = _parse_weight(txt("馬体重"))
        out.append({
            "race_id": race_id,
            "date": _to_iso_date(txt("年月日")),
            "course": course,
            "course_no": course_no,
            "day_no": day_no,
            "race_name": _clean_race_name(race_cell.get_text(strip=True)) if race_cell else None,
            "grade": _norm_grade(race_cell.get_text(strip=True)) if race_cell else None,
            "surface": surface,
            "distance": distance,
            "weather": txt("天気"),
            "track_condition": txt("馬場"),
            "field_size": _to_int(txt("頭数")),
            "pace_front_3f": pace_front,
            "pace_last_3f": pace_last,
            "pace_class": pace_class,
            # results 用
            "finish_position": fp,
            "note": note,
            "finish_time": txt("タイム"),
            "margin": txt("着差"),
            "last_3f": _to_float(last3f),
            "passing_order": passing,
            "corner_position": passing.split("-")[-1] if passing and "-" in passing else None,
            "popularity": _to_int(txt("人気")),
            "horse_weight": horse_weight,
            "horse_weight_diff": horse_weight_diff,
            # entries 由来（自分の行のみ）
            "post_position": _to_int(txt("馬番")),
            "gate": _to_int(txt("枠番")),
            "weight_carry": _to_float(txt("斤量")),
            "jockey": txt("騎手"),
        })
    return out


# --------------------------------------------------------------------------- #
# レースヘッダ（racedatabox）共通パース
# --------------------------------------------------------------------------- #
_WEATHER_TOKENS = ("晴", "曇", "小雨", "雨", "小雪", "雪")
_TRACK_TOKENS = ("稍重", "不良", "良", "重")  # 部分一致しないよう長い語を先に


def _parse_racedatabox(soup) -> dict:
    """レースページ共通ヘッダ `div.racedatabox` から開催・条件・発走時刻を抽出。

    例: '2回東京12日目 | 東京優駿 | (ＧⅠ) | 晴 | 良 |
         3歳オープン　(国) 牡・牝 (指) 馬齢 | 芝2400m 18頭 15:40発走'
    """
    out: dict = {}
    box = soup.find("div", class_="racedatabox")
    if not box:
        return out
    parts = [p.strip() for p in box.get_text("|", strip=True).split("|") if p.strip()]
    for p in parts:
        m = re.search(r"(\d+)回(\D+?)(\d+)日目", p)
        if m and "course_no" not in out:
            out["course_no"] = int(m.group(1))
            out["day_no"] = int(m.group(3))
            out["course"] = _JP_COURSE.get(m.group(2).strip())
        if p in _WEATHER_TOKENS and "weather" not in out:
            out["weather"] = p
        if p in _TRACK_TOKENS and "track_condition" not in out:
            out["track_condition"] = p
        if re.match(r"\d歳", p) and "race_class" not in out:
            # '3歳オープン　(国) 牡・牝 (指) 馬齢' → '3歳オープン'
            out["race_class"] = re.split(r"[\s　(（]", p)[0] or None
        m = re.match(r"([芝ダ障].{0,3}?)(\d{3,4})m\s*(\d{1,2})頭\s*(\d{1,2}:\d{2})発走", p)
        if m:
            out["surface"], out["distance"] = _surface_distance(p)
            out["field_size"] = int(m.group(3))
            out["post_time"] = m.group(4)
        if _norm_grade(p) and "grade" not in out:
            out["grade"] = _norm_grade(p)
    return out


def _parse_laps(soup) -> tuple[str | None, float | None, float | None]:
    """pacetable（200m毎ラップ）→ (lap_times, 前半3F, 上がり3F)。"""
    laps: list[tuple[int, float]] = []
    for table in soup.find_all("table", class_="pacetable"):
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) >= 2:
                dist, lap = _to_int(cells[0]), _to_float(cells[1])
                if dist and lap:
                    laps.append((dist, lap))
    laps = sorted(set(laps))
    if not laps:
        return None, None, None
    values = [lap for _, lap in laps]
    lap_times = "-".join(f"{v:g}" for v in values)
    uniform = laps[0][0] == 200 and all(
        b[0] - a[0] == 200 for a, b in zip(laps, laps[1:])
    )
    if uniform and len(values) >= 6:
        return lap_times, round(sum(values[:3]), 1), round(sum(values[-3:]), 1)
    return lap_times, None, None


_PAYOUT_TYPES = {
    "単勝": "win", "複勝": "place", "枠連": "wakuren", "馬連": "umaren",
    "ワイド": "wide", "馬単": "umatan", "3連複": "sanrenpuku", "3連単": "sanrentan",
}


def _parse_payouts(soup) -> list[dict]:
    """払戻テーブル → [{'bet_type','combination','payout_yen'}, ...]。

    セル構成は [券種, 組合せ, 金額] の3つ組が1行に2セット。複勝・ワイドは
    セル内改行で複数行（組合せと金額が同順で並ぶ）。
    """
    out: list[dict] = []
    for table in soup.find_all("table"):
        cells_all = [
            [c.get_text("\n", strip=True) for c in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")
        ]
        flat = [c for row in cells_all for c in row]
        if not any(c in _PAYOUT_TYPES for c in flat):
            continue
        for row in cells_all:
            for i in range(0, len(row) - 2, 3):
                bet_jp, combo_raw, yen_raw = row[i], row[i + 1], row[i + 2]
                bet = _PAYOUT_TYPES.get(bet_jp)
                if not bet:
                    continue
                combos = [c for c in combo_raw.split("\n") if c.strip()]
                yens = re.findall(r"[\d,]+(?=円)", yen_raw)
                for combo, yen in zip(combos, yens):
                    out.append({
                        "bet_type": bet,
                        "combination": combo.strip(),
                        "payout_yen": int(yen.replace(",", "")),
                    })
        if out:
            break  # 最初の払戻テーブルのみ
    return out


# --------------------------------------------------------------------------- #
# レース結果ページ: races + 全出走馬（entries/results 用）+ 払戻
# --------------------------------------------------------------------------- #
def fetch_race_result(race_id: str, max_age_hours: float = 24.0, force: bool = False) -> dict:
    """/db/race/<id>/raceresult.html を取得しパース。

    returns {'race': {...}, 'runners': [...], 'payouts': [...]}

    Raises:
        ContentNotReadyError: レース結果が未確定（発走前）
        ParseError: 結果テーブルが見つからない（サイト構造変化の疑い）
    """
    url = f"{BASE}/db/race/{race_id}/raceresult.html"
    # 確定済みレースの結果は不変 → キャッシュを実質無期限に使う（再取得を避ける）
    if parse_race_id(race_id)["date"] < _dt_date.today().isoformat():
        max_age_hours = max(max_age_hours, 24.0 * 3650)
    html = get_html(url, max_age_hours, force)
    if _looks_not_ready(url, html):
        raise ContentNotReadyError(f"{race_id}: レース結果が未確定（発走前）")
    soup = BeautifulSoup(html, "lxml")
    meta = parse_race_id(race_id)

    race = {
        "race_id": race_id,
        "date": meta["date"],
        "course": meta["course"],
        "race_no": meta["race_no"],
        "race_name": None,
        "grade": None,
        "surface": None,
        "distance": None,
    }
    title = soup.find("title")
    if title:
        race["race_name"] = title.get_text(strip=True).split("の結果")[0].strip() or None
        race["grade"] = _norm_grade(title.get_text())
    race.update({k: v for k, v in _parse_racedatabox(soup).items() if v is not None})
    if not race.get("surface"):
        # フォールバック: 本文から推定
        cond = soup.find(string=re.compile(r"[芝ダ障]\s*\d{3,4}"))
        if cond:
            race["surface"], race["distance"] = _surface_distance(str(cond))
    race["lap_times"], race["pace_front_3f"], race["pace_last_3f"] = _parse_laps(soup)

    runners: list[dict] = []
    table = _find_table_by_header(soup, ["着", "馬名", "騎手"])
    if not table:
        raise ParseError(
            f"{race_id}: 結果テーブルが見つからない（keibalab の HTML 構造変化の疑い）"
        )
    idx = _header_index(table)
    for tr in table.find_all("tr")[1:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) < 5:
            continue

        def cell(*names):
            for n in names:
                i = idx.get(n)
                if i is not None and i < len(cells):
                    return cells[i]
            return None

        name_cell = cell("馬名", "馬")
        hlink = name_cell.find("a", href=re.compile(r"/db/horse/")) if name_cell else None
        horse_id = _id_from_href(hlink.get("href"), "horse") if hlink else None
        if not horse_id:
            continue
        fp, note = _finish_position(cell("着").get_text(strip=True) if cell("着") else "")
        jcell = cell("騎手")
        tcell = cell("調教師")
        sexage = (cell("性齢").get_text(strip=True) if cell("性齢") else "") or ""
        pcell = cell("通過順")

        def txt(*names):
            c = cell(*names)
            return c.get_text(strip=True) if c else None

        # 馬体重 '522(＋2)'。α/β/Ω指数 列は保存しない（keibalab IP）
        horse_weight, horse_weight_diff = _parse_weight(txt("馬体重"))

        runners.append({
            "horse_id": horse_id,
            "horse_name": _clean_name(name_cell.get_text(strip=True)) if name_cell else None,
            "finish_position": fp,
            "note": note,
            "gate": _to_int(txt("枠")),
            "post_position": _to_int(txt("馬")),
            "sex": sexage[:1] if sexage else None,
            "age": _to_int(re.sub(r"\D", "", sexage)) if sexage else None,
            "weight_carry": _to_float(txt("斤量")),
            "jockey": (jcell.get_text(strip=True) if jcell else None),
            "trainer": (re.sub(r"^\[.*?\]", "", tcell.get_text(strip=True)) if tcell else None),
            "finish_time": txt("タイム") or None,
            "margin": txt("着差") or None,
            "last_3f": _to_float(txt("上り")),
            "passing_order": (_circled_to_dash(pcell.get_text(strip=True)) if pcell else None),
            "popularity": _to_int(txt("人")),
            "win_odds": _to_float(txt("単勝")),
            "horse_weight": horse_weight,
            "horse_weight_diff": horse_weight_diff,
        })
    return {"race": race, "runners": runners, "payouts": _parse_payouts(soup)}


# --------------------------------------------------------------------------- #
# 馬柱（umabashira）: 発走前の出馬表 → races(暫定) + entries
# --------------------------------------------------------------------------- #
def fetch_race_card(race_id: str, max_age_hours: float = 12.0, force: bool = False) -> dict:
    """/db/race/<id>/umabashira.html（馬柱）から発走前の出走表をパース。

    returns {'race': {...}, 'runners': [ {horse_id, post_position, gate, ...}, ... ]}

    注意:
      - 馬柱の天候・馬場・オッズ・馬体重は **発走前の暫定値** なので返さない
        （揮発データは macro-scout が都度取得する方針）。races へは
        コース・距離・グレード・発走時刻など不変部分のみ渡すこと。
      - keibalab 指数・予想印・各種連対率セルは keibalab の編集データなので扱わない。

    Raises:
        ParseError: 馬柱テーブルが見つからない
    """
    url = f"{BASE}/db/race/{race_id}/umabashira.html"
    html = get_html(url, max_age_hours, force)
    soup = BeautifulSoup(html, "lxml")
    meta = parse_race_id(race_id)

    box = _parse_racedatabox(soup)
    race = {
        "race_id": race_id,
        "date": meta["date"],
        "course": box.get("course") or meta["course"],
        "course_no": box.get("course_no"),
        "day_no": box.get("day_no"),
        "race_no": meta["race_no"],
        "race_name": None,
        "grade": box.get("grade"),
        "race_class": box.get("race_class"),
        "surface": box.get("surface"),
        "distance": box.get("distance"),
        "field_size": box.get("field_size"),
        "post_time": box.get("post_time"),
        # 天候・馬場は発走前の暫定値なので意図的に含めない
    }
    title = soup.find("title")
    if title:
        race["race_name"] = title.get_text(strip=True).split("の馬柱")[0].strip() or None
        race["grade"] = race["grade"] or _norm_grade(title.get_text())

    mega = soup.find("table", class_="megamoriTable")
    if not mega:
        raise ParseError(f"{race_id}: 馬柱テーブル（megamoriTable）が見つからない")

    rows = (mega.find("tbody") or mega).find_all("tr", recursive=False)
    # 最終セルがラベル（'枠番','馬番','騎手'...）。ラベル→セル列 のマップを作る
    label_cells: dict[str, list] = {}
    n_cols = None
    for tr in rows:
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 10:
            continue  # 予想印などの不揃い行はスキップ
        label = re.sub(r"\s", "", cells[-1].get_text(" ", strip=True))
        if label and label not in label_cells:
            label_cells[label] = cells[:-1]
            n_cols = n_cols or len(cells) - 1

    def col_texts(label_key: str) -> list[str | None]:
        for label, cells in label_cells.items():
            if label_key in label:
                return [c.get_text(" ", strip=True) or None for c in cells]
        return [None] * (n_cols or 0)

    name_row = None
    for label, cells in label_cells.items():
        if "馬名" in label or "馬　名" in label:
            name_row = cells
            break
    if not name_row:
        raise ParseError(f"{race_id}: 馬柱の馬名行が見つからない")

    gates = col_texts("枠番")
    numbers = col_texts("馬番")
    sexages = col_texts("性")
    kinryos = col_texts("斤量")
    jockeys = col_texts("騎手")
    trainers = col_texts("厩舎")

    runners: list[dict] = []
    for i, cell in enumerate(name_row):
        a = cell.find("a", href=re.compile(r"/db/horse/"))
        horse_id = _id_from_href(a.get("href"), "horse") if a else None
        if not horse_id:
            continue
        sexage = sexages[i] or ""
        msex = re.search(r"[牡牝セ]", sexage)
        mage = re.search(r"[牡牝セ]\s*(\d+)", sexage)
        trainer = re.sub(r"^[栗美]\s*", "", trainers[i] or "").strip() or None
        runners.append({
            "horse_id": horse_id,
            "horse_name": _clean_name(a.get_text()) or None,
            "post_position": _to_int(numbers[i]),
            "gate": _to_int(gates[i]),
            "sex": msex.group(0) if msex else None,
            "age": int(mage.group(1)) if mage else None,
            "weight_carry": _to_float(kinryos[i]),
            "jockey": jockeys[i],
            "trainer": trainer,
        })
    runners.sort(key=lambda r: r["post_position"] or 99)
    return {"race": race, "runners": runners}


# --------------------------------------------------------------------------- #
# 小物コンバータ
# --------------------------------------------------------------------------- #
_CIRCLED = {chr(0x2460 + i): str(i + 1) for i in range(20)}  # ①..⑳ → 1..20


def _circled_to_dash(text: str) -> str | None:
    """通過順セル '⑥⑤⑤③' → '6-5-5-3'。既にハイフン/空白区切りでも数字を拾う。"""
    text = (text or "").strip()
    if not text:
        return None
    out = [_CIRCLED[ch] for ch in text if ch in _CIRCLED]
    if out:
        return "-".join(out)
    nums = re.findall(r"\d+", text)
    return "-".join(nums) if nums else None


_FW_SIGNS = str.maketrans({"＋": "+", "－": "-", "−": "-", "±": "+"})


def _parse_weight(s: str | None) -> tuple[int | None, int | None]:
    """馬体重セル '522(＋2)' / '486(－2)' / '492(0)' → (522, +2)。'計不' 等は (None, None)。"""
    if not s:
        return None, None
    m = re.match(r"\s*(\d{3})\s*[(（]\s*([＋－−±+\-]?\d+)\s*[)）]", s)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2).translate(_FW_SIGNS))


def _parse_pace(s: str | None) -> tuple[float | None, float | None, str | None]:
    """戦績表ペースセル '36.0 - 35.4(M)' → (36.0, 35.4, 'M')。"""
    if not s:
        return None, None, None
    m = re.match(r"\s*(\d+\.\d)\s*-\s*(\d+\.\d)\s*\(([HMS])\)", s)
    if not m:
        return None, None, None
    return float(m.group(1)), float(m.group(2)), m.group(3)


def _to_int(s):
    if not s:
        return None
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


def _to_float(s):
    if not s:
        return None
    m = re.search(r"-?\d+\.?\d*", s)
    return float(m.group()) if m else None


def _to_iso_date(s):
    if not s:
        return None
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


if __name__ == "__main__":
    import json
    import sys

    hid = sys.argv[1] if len(sys.argv) > 1 else "2020103060"
    data = fetch_horse(hid, force="--force" in sys.argv)
    print(f"name={data['name']}")
    print("profile:", json.dumps(data["profile"], ensure_ascii=False))
    print("pedigree:", json.dumps(data["pedigree"], ensure_ascii=False))
    print(f"career: {len(data['career'])} 走")
    for r in data["career"][:3]:
        print("  ", json.dumps(r, ensure_ascii=False))
