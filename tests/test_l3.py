"""L3 のテスト。TEST_SPEC.md の T-3xx に対応する。

期待値の出所:
- 合成フィクスチャ: 本文に実在する言表節の型のみ
- 実測: data/ を前提とする検査は validation マーカー
- gold: 評価専用。**規則の導出・調整に使わない**(T-305)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.attribute import (
    apply_alternation,
    attribute,
    build_alias_table,
    summarize,
)
from pipeline.persons import CANDIDATES, WINDOW, build as build_persons, find_evidence
from pipeline.persons import to_json as persons_to_json

DATA = Path("data")

requires_l3 = pytest.mark.skipif(
    not (DATA / "attribution.json").exists(), reason="L3 成果物が無い(pipeline.build_l3 未実行)"
)


class FakeSeg:
    def __init__(self, kind, text, start=0):
        self.kind = kind
        self.text = text
        self.start = start
        self.end = start + len(text)
        self.chars = len(text)


class FakeChapter:
    index, start, end = 1, 0, 10**9


def run(segs):
    table = [("主人", "kushami"), ("迷亭", "meitei"), ("寒月", "kangetsu")]
    table.sort(key=lambda kv: -len(kv[0]))
    return attribute(segs, [FakeChapter()], table)


# --- T-301 異名統合の根拠 -----------------------------------------------------


@pytest.mark.unit
def test_t301_no_merge_without_evidence():
    """本文に根拠が無ければ異名を統合しない。"""
    flat = "主人は云った。迷亭も云った。"  # 苦沙弥 も 珍野 も現れない
    persons = {p.id: p for p in build_persons(flat)}
    assert persons["kushami"].aliases == ["主人"]
    assert "苦沙弥" in persons["kushami"].rejected


@pytest.mark.unit
def test_t301_adjacency_is_strongest_evidence():
    """連結形(例「水島寒月」)が取れれば統合し、根拠を記録する。"""
    ev = find_evidence("並んで水島寒月という名刺がある", "寒月", "水島")
    assert ev and ev[0].kind == "adjacency"
    assert "水島寒月" in ev[0].snippet


@pytest.mark.unit
def test_t301_substring_is_not_an_alias():
    """部分文字列の関係にある対は異名ではない(窓に両方入るのが自明で根拠にならない)。"""
    flat = "東風君と東風子が来た。東風は詩人である。"
    p = next(x for x in build_persons(flat) if x.id == "tofu")
    assert "東風" in p.aliases
    assert all("子" != a for a in p.aliases)


@requires_l3
@pytest.mark.validation
def test_t301_every_merged_alias_has_evidence():
    """統合された全異名に、種別・オフセット・引用つきの根拠がある。"""
    pj = json.loads((DATA / "persons.json").read_text(encoding="utf-8"))
    for p in pj["persons"]:
        for alias in p["aliases"][1:]:
            assert alias in p["evidence"], f"{p['id']}: {alias} に根拠が無い"
            d = p["evidence"][alias]
            assert d["via"] in p["aliases"]
            for hit in d["hits"]:
                assert hit["kind"] in {"adjacency", "naming", "window"}
                assert isinstance(hit["offset"], int) and hit["snippet"]


@requires_l3
@pytest.mark.validation
def test_t301_unresolved_names_are_kept_separate():
    """根拠が取れなかった呼称は、短い異名に吸収させず未解決実体として立てる。"""
    pj = json.loads((DATA / "persons.json").read_text(encoding="utf-8"))
    ids = {p["id"] for p in pj["persons"]}
    for u in pj["unresolved"]:
        assert u["needs_review"] is True
        assert u["candidate_of"] in ids and u["reason"]
        # 未解決の呼称が、どの人物の異名にも混入していないこと
        for p in pj["persons"]:
            assert u["canonical"] not in p["aliases"]


# --- T-302 帰属根拠 -----------------------------------------------------------


@pytest.mark.unit
def test_t302_every_attribution_carries_a_rule_id():
    segs = [
        FakeSeg("jinomon", "　しばらくして"),
        FakeSeg("kaiwa", "「そうさ」"),
        FakeSeg("jinomon", "と主人は答えた。\r\n"),
    ]
    (a,) = run(segs)
    assert (a.speaker, a.rule_id) == ("kushami", "R1")
    assert a.evidence and "主人" in a.evidence


@pytest.mark.unit
def test_t302_r1b_fires_without_speech_verb():
    """引用の「と」自体が言表の標識。言表動詞が無くても帰属し、規則を区別する。"""
    segs = [
        FakeSeg("kaiwa", "「なるほど」"),
        FakeSeg("jinomon", "と主人は無暗に感心している。\r\n"),
    ]
    (a,) = run(segs)
    assert (a.speaker, a.rule_id) == ("kushami", "R1b")


# --- T-303 帰属不能の保持(F-13)----------------------------------------------


@pytest.mark.unit
def test_t303_unattributable_stays_null():
    """地の文が無い連続発話は null のまま。直前話者で埋めない。"""
    segs = [
        FakeSeg("kaiwa", "「そうさ」"),
        FakeSeg("jinomon", "と主人は答えた。\r\n"),
        FakeSeg("kaiwa", "「本当かい」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「本当だ」"),
        FakeSeg("jinomon", "\r\n"),
    ]
    atts = run(segs)
    assert [a.speaker for a in atts] == ["kushami", None, None]


@pytest.mark.unit
def test_t303_multiple_candidates_are_not_narrowed():
    """候補が複数出たら帰属しない。候補は記録する。"""
    segs = [
        FakeSeg("kaiwa", "「そうかい」"),
        FakeSeg("jinomon", "と主人が聞くと迷亭は笑った。\r\n"),
    ]
    (a,) = run(segs)
    assert a.speaker is None and a.rule_id is None
    assert set(a.candidates) == {"kushami", "meitei"}


@pytest.mark.unit
def test_t303_alternation_needs_two_known_and_two_speakers():
    """R4 は既知 2 件かつ話者ちょうど 2 人のときだけ発火する。"""
    # R2 は句点で切れない前置節にしか掛からない(_tail_clause の設計)。
    # 「主人が口を切って」のように引用へ流れ込む形にする
    segs = [
        FakeSeg("jinomon", "　しばらくして主人が口を切って"),
        FakeSeg("kaiwa", "「甲」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「乙」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「丙」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「丁」"),
        FakeSeg("jinomon", "と迷亭は云った。\r\n"),
    ]
    atts = run(segs)
    # 前提の検算: 既知は 2 件・2 人でなければこのケースは無意味
    known = [(k, a.speaker) for k, a in enumerate(atts) if a.speaker]
    assert len(known) == 2 and len({s for _, s in known}) == 2, known
    filled = apply_alternation(segs, atts)
    assert filled == 2
    assert [a.speaker for a in atts] == ["kushami", "meitei", "kushami", "meitei"]
    assert {a.rule_id for a in atts if a.rule_id == "R4"} == {"R4"}


@pytest.mark.unit
def test_t303_alternation_refuses_three_speakers():
    """3 人以上いる塊には触らない(推定で 2 人に絞らない)。"""
    segs = [
        FakeSeg("jinomon", "　主人が云う。"),
        FakeSeg("kaiwa", "「甲」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「乙」"),
        FakeSeg("jinomon", "と寒月が云った。"),
        FakeSeg("kaiwa", "「丙」"),
        FakeSeg("jinomon", "\r\n"),
        FakeSeg("kaiwa", "「丁」"),
        FakeSeg("jinomon", "と迷亭は云った。\r\n"),
    ]
    atts = run(segs)
    before = [a.speaker for a in atts]
    apply_alternation(segs, atts)
    assert [a.speaker for a in atts] == before


@requires_l3
@pytest.mark.validation
def test_t303_measured_nulls_are_preserved():
    """実測でも null が既定話者で埋められていない。"""
    d = json.loads((DATA / "attribution.json").read_text(encoding="utf-8"))
    atts = d["attributions"]
    assert any(a["speaker"] is None for a in atts), "全件帰属は F-13 違反の兆候"
    for a in atts:
        assert (a["speaker"] is None) == (a["rule_id"] is None)
        if a["speaker"]:
            assert a["evidence"], "帰属には根拠が要る"
        if a["candidates"]:
            assert a["speaker"] is None, "候補が複数なら帰属しない"
    assert d["summary"]["attributed"] == sum(1 for a in atts if a["speaker"])


# --- T-304 gold に対する精度(O-3)--------------------------------------------


@requires_l3
@pytest.mark.validation
def test_t304_calibration_is_recorded():
    """適合率・再現率・帰属率が算出され、成果物に記録されている。

    採用水準は L3 の較正後に SPEC §4 へ追記済み。ここではその水準を検査する。
    """
    doc = (Path("docs") / "attribution_calibration.md").read_text(encoding="utf-8")
    assert "適合率" in doc and "再現率" in doc

    from pipeline.build_l3 import build

    r = build()
    ev = r["eval"]
    assert ev is not None
    # L3 実測 2026-08-25: 適合率 0.900 / 再現率 0.155 / 帰属率 0.165。
    # SPEC §4 の採用水準は「適合率 0.85 以上」。再現率には水準を置かず、
    # 縮退条件(T-602)の判定材料とする
    assert ev["precision"] >= 0.85, ev
    assert ev["over_attributed_on_unknown"] <= 2, ev


@requires_l3
@pytest.mark.validation
def test_t305_gold_is_evaluation_only():
    """gold が評価専用であることを、成果物の記載と規則の独立性で担保する。"""
    gold = json.loads((DATA / "speaker_gold.json").read_text(encoding="utf-8"))
    assert "評価専用" in gold["policy"]
    assert gold["size"] == len(gold["labels"]) == 300
    assert gold["seed"] == 20260825
    # 規則の実装が gold ファイルを参照していないこと
    for mod in ("pipeline/attribute.py", "pipeline/persons.py"):
        src = Path(mod).read_text(encoding="utf-8")
        assert "speaker_gold" not in src, f"{mod} が gold を参照している"


@requires_l3
@pytest.mark.validation
def test_t304_vocabulary_ceiling_is_reported():
    """統制語彙の外の話者の件数が報告され、限界が隠されていない。"""
    doc = (Path("docs") / "attribution_calibration.md").read_text(encoding="utf-8")
    assert "統制語彙の限界" in doc
    assert "この観察をもとに規則を直すことはしない" in doc


# --- 人物候補表の健全性 -------------------------------------------------------


@pytest.mark.unit
def test_candidates_have_unique_ids_and_window_is_documented():
    ids = [c["id"] for c in CANDIDATES]
    assert len(ids) == len(set(ids))
    assert all(c["aliases"] and c["display"] and c["kind"] for c in CANDIDATES)
    assert WINDOW > 0


@pytest.mark.unit
def test_alias_table_prefers_longest_match():
    """長一致優先。短い異名が長い呼称を食わない。"""
    pj = persons_to_json(build_persons("鼻子と金田夫人と金田君が来た。"))
    table = build_alias_table(pj)
    lengths = [len(a) for a, _ in table]
    assert lengths == sorted(lengths, reverse=True)


@requires_l3
@pytest.mark.validation
def test_summary_matches_attributions():
    d = json.loads((DATA / "attribution.json").read_text(encoding="utf-8"))
    atts = d["attributions"]
    from pipeline.attribute import Attribution

    recomputed = summarize([Attribution(**a) for a in atts])
    for k in ("utterances", "attributed", "unattributed", "ambiguous", "by_rule"):
        assert recomputed[k] == d["summary"][k], k
