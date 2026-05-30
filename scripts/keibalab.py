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
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import COURSE_CODE_MAP, course_code_to_name, parse_race_id  # noqa: E402

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


# --------------------------------------------------------------------------- #
# HTTP + キャッシュ
# --------------------------------------------------------------------------- #
def _cache_path(url: str) -> Path:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{h}.html"


def get_html(url: str, max_age_hours: float = 24.0, force: bool = False) -> str:
    """URL を取得。キャッシュが新しければ再利用。force でキャッシュ無視。"""
    global _last_fetch
    cp = _cache_path(url)
    if not force and cp.exists():
        age_h = (time.time() - cp.stat().st_mtime) / 3600.0
        if age_h <= max_age_hours:
            return cp.read_text(encoding="utf-8")

    # 礼儀: 連続ライブ取得の間隔を空ける
    wait = _MIN_INTERVAL - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
    _last_fetch = time.time()
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    html = resp.text
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
            # results 用
            "finish_position": fp,
            "note": note,
            "finish_time": txt("タイム"),
            "margin": txt("着差"),
            "last_3f": _to_float(last3f),
            "passing_order": passing,
            "corner_position": passing.split("-")[-1] if passing and "-" in passing else None,
            # entries 由来（自分の行のみ）
            "post_position": _to_int(txt("馬番")),
            "gate": _to_int(txt("枠番")),
            "weight_carry": _to_float(txt("斤量")),
            "jockey": txt("騎手"),
        })
    return out


# --------------------------------------------------------------------------- #
# レース結果ページ: races + 全出走馬（entries/results 用）
# --------------------------------------------------------------------------- #
def fetch_race_result(race_id: str, max_age_hours: float = 24.0, force: bool = False) -> dict:
    """/db/race/<id>/raceresult.html を取得しパース。

    returns {'race': {...}, 'runners': [ {horse_id, finish_position, ...}, ... ]}
    """
    url = f"{BASE}/db/race/{race_id}/raceresult.html"
    html = get_html(url, max_age_hours, force)
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
    # 条件（芝3200 等）を本文から推定
    cond = soup.find(string=re.compile(r"[芝ダ障]\s*\d{3,4}"))
    if cond:
        race["surface"], race["distance"] = _surface_distance(str(cond))

    runners: list[dict] = []
    table = _find_table_by_header(soup, ["着", "馬名", "騎手"])
    if table:
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
            })
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
