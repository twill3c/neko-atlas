"""L5 のテスト。TEST_SPEC.md の T-50x に対応する。

中心は **標本サイズ交絡の検査**(HC-025)。距離のような統計量は単位の大きさの
関数になりうるので、比較の前に交絡の大きさを測り、等サイズ化してから解釈する。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.dispersion import juilland_d
from pipeline.stylometry import burrows_delta, select_mfw, size_confound, split_blocks

DATA = Path("data")
WEB = Path("web")

requires_l5 = pytest.mark.skipif(
    not (DATA / "chrono.json").exists(), reason="L5 成果物が無い(pipeline.build_l5 未実行)"
)


@pytest.fixture(scope="module")
def chrono():
    return json.loads((DATA / "chrono.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def haichi():
    return json.loads((DATA / "haichi.json").read_text(encoding="utf-8"))


# --- T-501 Delta の再現性 -----------------------------------------------------


@pytest.mark.unit
def test_t501_delta_is_deterministic():
    """同一入力の二回実行で距離行列が完全一致する(乱数を使わない — N-06)。"""
    units = ["a", "b", "c", "d"]
    toks = [
        ["猫", "は", "居る", "は", "猫"] * 40,
        ["犬", "が", "走る", "が", "犬"] * 40,
        ["猫", "が", "居る", "は", "犬"] * 40,
        ["猫", "は", "走る", "が", "犬"] * 40,
    ]
    a = burrows_delta(units, toks, n_mfw=8)
    b = burrows_delta(units, toks, n_mfw=8)
    assert (a.distance == b.distance).all()
    assert (a.coords == b.coords).all()
    assert a.features == b.features
    assert all(a.distance[i, i] == 0 for i in range(len(units)))
    assert (a.distance == a.distance.T).all()


@pytest.mark.unit
def test_t501_mfw_selection_is_stable_on_ties():
    """同順位は語形で決める(集合の走査順に依存しない)。"""
    toks = [["い", "あ", "う"] * 3, ["う", "い", "あ"] * 3]
    assert select_mfw(toks, 3) == ["あ", "い", "う"]


@requires_l5
@pytest.mark.validation
def test_t501_method_is_recorded(chrono):
    """MFW 件数・窓・刻み・seed・置換回数が成果物に記録されている。"""
    assert chrono["mfw"] > 0 and chrono["window"] > 0 and chrono["step"] > 0
    for v, b in chrono["blocks"].items():
        assert b["seed"] and b["permutations"] >= 1000, v
        assert b["block_size"] > 0 and b["blocks"] > 0


# --- 標本サイズ交絡(HC-025)-------------------------------------------------


@pytest.mark.unit
def test_size_confound_detects_dependence():
    """統計量が単位サイズの関数なら強い相関として出る。"""
    sizes = [100, 200, 400, 800, 1600]
    assert size_confound(sizes, [1 / s for s in sizes]) < -0.8
    assert abs(size_confound(sizes, [0.5] * 5)) < 1e-9


@pytest.mark.unit
def test_split_blocks_are_equal_sized():
    """等サイズ化は端数を捨てる — 大きさを揃えることが目的だから。"""
    blocks = split_blocks(list(range(2500)), 1000)
    assert [len(b) for b in blocks] == [1000, 1000]
    assert split_blocks(list(range(500)), 1000) == []


@requires_l5
@pytest.mark.validation
def test_naive_units_are_flagged_unusable(chrono):
    """章をそのまま単位にした版は、交絡が大きいことを明示して解釈に使わない。"""
    for v, b in chrono["naive"].items():
        assert "size_confound_r" in b and "usable" in b
        if abs(b["size_confound_r"]) > 0.5:
            assert b["usable"] is False, v
    # 実測 2026-08-25: 3 系統とも交絡が大きく、素朴版は使えない
    assert all(b["usable"] is False for b in chrono["naive"].values())


@requires_l5
@pytest.mark.validation
def test_block_units_reduce_the_confound(chrono):
    """等サイズブロックにすると交絡が下がる。下がらないなら解釈してはならない。"""
    for v, b in chrono["blocks"].items():
        assert abs(b["size_confound_r"]) <= 0.5, (v, b["size_confound_r"])
        assert abs(b["size_confound_r"]) < abs(chrono["naive"][v]["size_confound_r"]), v


@requires_l5
@pytest.mark.validation
def test_permutation_test_has_a_control(chrono):
    """章ラベルの置換検定が対照として付いている。帰無平均はほぼ 0。"""
    for v, b in chrono["blocks"].items():
        assert abs(b["null_mean"]) < 0.01, (v, b["null_mean"])
        assert b["null_sd"] > 0
        assert 0 < b["p_value"] <= 1
        for c, e in b["per_chapter"].items():
            assert 0 < e["p"] <= 1
            assert e["blocks"] >= 1
            if e["blocks"] == 1:
                assert e["within"] is None, "1 ブロックの章に章内ばらつきは無い"


# --- T-502 rolling delta ------------------------------------------------------


@requires_l5
@pytest.mark.validation
def test_t502_rolling_windows_are_equal_sized(chrono):
    """窓は等サイズ・等間隔。章境界をまたぐことを許す(それが検出対象)。"""
    r = chrono["rolling"]
    starts = [p["start"] for p in r["series"]]
    assert starts[0] == 0
    steps = {starts[i + 1] - starts[i] for i in range(len(starts) - 1)}
    assert steps == {chrono["step"]}, steps
    assert starts[-1] + chrono["window"] <= r["tokens"]
    assert r["series"][0]["from_prev"] is None
    assert all(p["from_prev"] is not None for p in r["series"][1:])
    toks = [b["token"] for b in r["chapter_bounds"]]
    assert toks[0] == 0 and toks == sorted(toks)


# --- T-503 会話混在 / 分離の差 ------------------------------------------------


@requires_l5
@pytest.mark.validation
def test_t503_mixing_voices_measures_kaiwa_ratio(chrono):
    """二声を混ぜると第一主成分が会話率と相関する。分けた版では会話率が定義できない。"""
    allb = chrono["blocks"]["all"]
    assert "pc1_vs_kaiwa_share_r" in allb
    assert abs(allb["pc1_vs_kaiwa_share_r"]) > 0.5, allb["pc1_vs_kaiwa_share_r"]
    shares = allb["kaiwa_share"]
    assert min(shares) < 0.4 < max(shares), "混在ブロックの会話率に幅があること"
    assert set(chrono["blocks"]["jinomon"]["kaiwa_share"]) == {0.0}
    assert set(chrono["blocks"]["kaiwa"]["kaiwa_share"]) == {1.0}


@requires_l5
@pytest.mark.validation
def test_t503_view_presents_the_comparison():
    js = (WEB / "futakoe.js").read_text(encoding="utf-8")
    assert "pc1_vs_kaiwa_share_r" in js
    assert "会話率を測っている" in js


# --- T-504 分散プロットの位置整合 ---------------------------------------------


@requires_l5
@pytest.mark.validation
def test_t504_occurrences_land_inside_the_body(haichi):
    """出現位置が本文の範囲に収まり、章の区間に解決する。"""
    n = haichi["body_chars"]
    chapters = haichi["chapters"]
    total = 0
    for lemma, offs in haichi["occurrences"].items():
        assert offs == sorted(offs), lemma
        for off in offs:
            assert 0 <= off < n, (lemma, off)
            assert any(c["start"] <= off < c["end"] for c in chapters), (lemma, off)
        total += len(offs)
    assert total > 1000


@requires_l5
@pytest.mark.validation
def test_t504_peak_chapter_matches_occurrences(haichi):
    """表に出す「最も濃い章」が、実際の出現位置の分布と一致する。"""
    chapters = haichi["chapters"]

    def ch_of(off):
        return next(c["index"] for c in chapters if c["start"] <= off < c["end"])

    checked = 0
    for row in haichi["concentrated"]:
        offs = haichi["occurrences"].get(row["lemma"])
        if not offs:
            continue
        counts: dict[int, int] = {}
        for off in offs:
            counts[ch_of(off)] = counts.get(ch_of(off), 0) + 1
        assert max(counts, key=counts.get) == row["peak_chapter"], row["lemma"]
        checked += 1
    assert checked >= 20


@pytest.mark.unit
def test_juilland_d_bounds():
    """均等なら 1、一箇所に集中すると 0 に近づく。"""
    assert juilland_d([1, 1, 1, 1]) == pytest.approx(1.0)
    concentrated = juilland_d([1, 0, 0, 0])
    assert 0 <= concentrated < 0.1
    assert juilland_d([2, 1, 1, 0]) > concentrated


@requires_l5
@pytest.mark.validation
def test_terms_are_not_hand_picked(haichi):
    """主題語が手選びでないこと(閾値と選び方が記録され、D の順に並ぶ)。"""
    assert "手で選ばず" in haichi["note"]
    assert haichi["min_freq"] >= 10
    ds = [r["d"] for r in haichi["concentrated"]]
    assert ds == sorted(ds), "偏りの小さい順に並んでいない"
    assert all(r["total"] >= haichi["min_freq"] for r in haichi["concentrated"])


@requires_l5
@pytest.mark.validation
def test_no_sentiment_curve_is_shipped():
    """感情価曲線は採らない(F-20 のスコープ判断)。"""
    js = (WEB / "haichi.js").read_text(encoding="utf-8")
    assert "感情価曲線は効かない" in js
    html = (WEB / "haichi.html").read_text(encoding="utf-8")
    assert "感情の起伏を追う曲線は機能しません" in html


# --- 形態素と本文の整列(HC-024)---------------------------------------------


@requires_l5
@pytest.mark.validation
def test_token_alignment_consumes_the_body(haichi):
    """整列が本文を最後まで消費し、取りこぼしが無いことが成果物に記録されている。

    表層長の足し上げでは 2,376 字ずれた(L5 実測)。位置は必ず本文の中で取り直す。
    """
    a = haichi["alignment"]
    assert a["unmatched"] == 0, a
    assert a["consumed_ratio"] >= 0.999, a
    assert a["cursor_end"] <= a["plain_chars"]
    assert a["total_rows"] > 100_000


@requires_l5
@pytest.mark.validation
def test_chapter_assignment_comes_from_offsets(haichi):
    """章の帰属が本文オフセット由来であること(シャードの章ラベルではない)。

    地の文セグメントは章見出しをまたぐので、シャードのラベルを使うとまたいだ分が
    すべて手前の章に付く。by_chapter の総和が総出現と一致することで担保する。
    """
    for row in haichi["concentrated"]:
        assert sum(row["by_chapter"].values()) == row["total"], row["lemma"]
    src = (Path("pipeline") / "dispersion.py").read_text(encoding="utf-8")
    assert "シャードの `chapter` を章の帰属に使わない" in src
    assert 'd["chapter"]' not in src
