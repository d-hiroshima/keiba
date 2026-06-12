"""keibalab パーサの回帰テスト（合成フィクスチャ使用、ネットワーク非依存）。

keibalab の HTML 構造が変わった時に「静かに全 NULL になる」のを防ぐ最後の砦。
フィクスチャは実ページの構造のみ再現した架空データ（docs/data-policy.md）。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def patch_html(monkeypatch, fixture_html):
    """keibalab.get_html を差し替えて指定フィクスチャを返す。"""
    import keibalab

    def _patch(name: str):
        monkeypatch.setattr(
            keibalab, "get_html", lambda url, *a, **kw: fixture_html(name)
        )

    return _patch


def test_fetch_race_result_full(patch_html):
    import keibalab

    patch_html("raceresult.html")
    data = keibalab.fetch_race_result("202606010511")
    race = data["race"]
    assert race["race_name"] == "テスト記念"
    assert race["grade"] == "GIII"
    assert race["surface"] == "turf" and race["distance"] == 1600
    assert race["weather"] == "晴" and race["track_condition"] == "良"
    assert race["race_class"] == "4歳以上オープン"
    assert race["field_size"] == 3
    assert race["post_time"] == "15:40"
    assert race["course_no"] == 3 and race["day_no"] == 2
    assert race["pace_front_3f"] == 35.0
    assert race["pace_last_3f"] == 33.7
    assert race["lap_times"].startswith("12.5-11-11.5")

    runners = data["runners"]
    assert len(runners) == 3
    r1 = runners[0]
    assert r1["horse_id"] == "2099000001"
    assert r1["finish_position"] == 1
    assert r1["popularity"] == 2
    assert r1["win_odds"] == 4.5
    assert r1["horse_weight"] == 500 and r1["horse_weight_diff"] == 2
    assert r1["jockey"] == "架空一郎"
    assert r1["passing_order"] == "3-3"
    r2 = runners[1]
    assert r2["horse_weight"] == 456 and r2["horse_weight_diff"] == -4


def test_fetch_race_result_payouts(patch_html):
    import keibalab

    patch_html("raceresult.html")
    payouts = keibalab.fetch_race_result("202606010511")["payouts"]
    by_type = {}
    for p in payouts:
        by_type.setdefault(p["bet_type"], []).append(p)
    assert {p["combination"]: p["payout_yen"] for p in by_type["win"]} == {"1": 450}
    assert len(by_type["place"]) == 2
    assert len(by_type["wide"]) == 3
    assert {p["combination"] for p in by_type["wide"]} == {"1-2", "1-3", "2-3"}
    assert by_type["sanrenpuku"][0].items() >= {"combination": "1-2-3", "payout_yen": 1200}.items()
    assert by_type["sanrentan"][0]["payout_yen"] == 3500


def test_fetch_race_result_not_ready(monkeypatch):
    import keibalab

    monkeypatch.setattr(
        keibalab, "get_html",
        lambda url, *a, **kw: "<html><body>レース結果は確定していません</body></html>",
    )
    with pytest.raises(keibalab.ContentNotReadyError):
        keibalab.fetch_race_result("202606010511")


def test_fetch_race_result_structure_change_raises(monkeypatch):
    import keibalab

    monkeypatch.setattr(
        keibalab, "get_html",
        lambda url, *a, **kw: "<html><body><p>無関係なページ</p></body></html>",
    )
    with pytest.raises(keibalab.ParseError):
        keibalab.fetch_race_result("202606010511")


def test_fetch_race_card(patch_html):
    import keibalab

    patch_html("umabashira.html")
    data = keibalab.fetch_race_card("202606010511")
    race = data["race"]
    assert race["race_name"] == "テスト記念"
    assert race["surface"] == "turf" and race["distance"] == 1600
    assert race["post_time"] == "15:40"
    # 馬柱の天候・馬場は発走前の暫定値なので返さない（揮発データ方針）
    assert race.get("weather") is None and race.get("track_condition") is None

    runners = data["runners"]
    assert [r["post_position"] for r in runners] == [1, 2, 3]
    alpha = runners[0]
    assert alpha["horse_id"] == "2099000001"
    assert alpha["horse_name"] == "アルファテスト"
    assert alpha["gate"] == 1
    assert alpha["sex"] == "牡" and alpha["age"] == 4
    assert alpha["weight_carry"] == 58.0
    assert alpha["jockey"] == "架空一郎"
    assert alpha["trainer"] == "架空調"  # 「美 」プレフィクス除去
    beta = runners[1]
    assert beta["sex"] == "牝" and beta["age"] == 5 and beta["weight_carry"] == 56.0


def test_fetch_horse_profile_pedigree_career(patch_html):
    import keibalab

    patch_html("horse.html")
    data = keibalab.fetch_horse("2099000001")
    assert data["name"] == "アルファテスト"
    prof = data["profile"]
    assert prof["birthday"] == "2022-04-01" and prof["sex"] == "牡"
    ped = data["pedigree"]
    assert ped["sire"] == "架空サイアー" and ped["sire_id"] == "90000001"
    assert ped["grandsire"] == "架空グランドサイアー"
    assert ped["dam"] == "架空ダム"
    assert ped["broodmare_sire"] == "架空ブルードメアサイアー"

    career = data["career"]
    assert len(career) == 2
    c1 = career[0]
    assert c1["race_id"] == "202606010511"
    assert c1["finish_position"] == 1
    assert c1["popularity"] == 2
    assert c1["field_size"] == 3
    assert (c1["pace_front_3f"], c1["pace_last_3f"], c1["pace_class"]) == (35.0, 34.2, "M")
    assert c1["horse_weight"] == 500 and c1["horse_weight_diff"] == 2
    assert c1["passing_order"] == "3-3"
    assert c1["jockey"] == "架空一郎"
    c2 = career[1]
    assert c2["surface"] == "dirt" and c2["track_condition"] == "稍重"
    assert c2["pace_class"] == "H"
    assert c2["horse_weight_diff"] == -2


def test_looks_not_ready_scoped_to_raceresult():
    import keibalab

    marker_html = "x確定していませんx"
    assert keibalab._looks_not_ready("https://x/db/race/1/raceresult.html", marker_html)
    # 馬ページ等では誤検知させない
    assert not keibalab._looks_not_ready("https://x/db/horse/123/", marker_html)
