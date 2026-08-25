"""L4 のテスト。TEST_SPEC.md の T-40x に対応する。

投影の不変量(HC-024)を中心に据える — 帯索引もリーダーのシャードも、
分類済みの本文から導いた第二の表現なので、長さの等式で本文側に結び直す。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipeline.band import JINOMON, KAIWA, NOTATION, build_spans, check_coverage

DATA = Path("data")
WEB = Path("web")

requires_l4 = pytest.mark.skipif(
    not (DATA / "band.json").exists(), reason="L4 成果物が無い(pipeline.build_l4 未実行)"
)


class FakeSeg:
    def __init__(self, kind, start, chars, text=""):
        self.kind = kind
        self.start = start
        self.end = start + chars
        self.chars = chars
        self.text = text or ("\r\n" if kind == "jinomon" and chars == 2 else "x" * chars)


class FakeAtt:
    def __init__(self, segment_index, speaker=None):
        self.segment_index = segment_index
        self.speaker = speaker


@pytest.fixture(scope="module")
def band():
    return json.loads((DATA / "band.json").read_text(encoding="utf-8"))


# --- T-402 帯索引の被覆(F-26)------------------------------------------------


@pytest.mark.unit
def test_t402_gaps_are_filled_as_notation():
    """セグメント間の隙間が kind=2 で埋まり、総和が本文長に一致する。"""
    segs = [FakeSeg("jinomon", 5, 10), FakeSeg("kaiwa", 15, 6), FakeSeg("jinomon", 21, 4)]
    spans = build_spans(segs, 30, [FakeAtt(0), FakeAtt(1, "kushami"), FakeAtt(2)])
    c = check_coverage(spans, 30)
    # 前提の検算: 先頭 5 字と末尾 5 字が隙間になるフィクスチャであること
    assert segs[0].start == 5 and segs[-1].end == 25
    assert c["covers_body"] and c["starts_at_zero"] and c["contiguous"]
    assert c["sum_lens"] == 30
    assert spans["kind"][0] == NOTATION and spans["kind"][-1] == NOTATION
    assert c["columns_equal_length"]


@pytest.mark.unit
def test_t402_run_positions_are_sequential():
    """run は会話 span でのみ非 0 で、塊内で pos が 0 から連番になる。"""
    segs = [
        FakeSeg("kaiwa", 0, 3),
        FakeSeg("jinomon", 3, 2),          # 改行だけ → 塊は続く
        FakeSeg("kaiwa", 5, 3),
        FakeSeg("jinomon", 8, 6, "　地の文。"),  # 実質のある地の文 → 塊が切れる
        FakeSeg("kaiwa", 14, 3),
    ]
    spans = build_spans(segs, 17, [FakeAtt(i) for i in range(len(segs))])
    c = check_coverage(spans, 17)
    assert c["run_positions_ok"], spans
    kaiwa = [(spans["run"][i], spans["pos"][i])
             for i in range(len(spans["kind"])) if spans["kind"][i] == KAIWA]
    assert kaiwa == [(1, 0), (1, 1), (2, 0)]
    for i, k in enumerate(spans["kind"]):
        if k != KAIWA:
            assert spans["run"][i] == 0 and spans["pos"][i] == 0


@requires_l4
@pytest.mark.validation
def test_t402_measured_coverage(band):
    c = band["coverage"]
    assert c["covers_body"], c
    assert c["sum_lens"] == band["body_chars"]
    assert c["starts_at_zero"] and c["contiguous"] and c["columns_equal_length"]
    assert c["run_positions_ok"]
    s = band["spans"]
    assert len({len(s[k]) for k in
                ("start", "lens", "plain", "kind", "run", "pos", "speaker")}) == 1
    assert c["sum_plain"] < c["sum_lens"], "可読長の総和は原文長より短い"


# --- T-403 「不明」を塗らない(F-15c)----------------------------------------


@requires_l4
@pytest.mark.validation
def test_t403_only_attributed_have_speaker(band):
    """speaker が入るのは会話 span のみ。件数が attribution と一致する。"""
    s = band["spans"]
    painted = 0
    for k, sp in zip(s["kind"], s["speaker"]):
        if sp is not None:
            assert k == KAIWA, "地の文・記法に話者が付いている"
            painted += 1
    assert painted == band["attribution"]["attributed"]
    assert painted < sum(1 for k in s["kind"] if k == KAIWA), "全件帰属は F-13 違反の兆候"


@requires_l4
@pytest.mark.validation
def test_t403_legend_states_rate_and_precision(band):
    js = (WEB / "band.js").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "不明は塗らない" in js
    assert "--unpainted" in js, "不明用の無彩色が定義されていること"
    assert "不明は塗りません" in html
    a = band["attribution"]
    assert 0 < a["rate"] < 1 and a["precision"] > 0 and a["gold_size"] == 300


# --- T-404 俯瞰の符号化 -------------------------------------------------------


@requires_l4
@pytest.mark.validation
def test_t404_overview_uses_aggregates_only(band):
    """俯瞰の描画に交互濃淡(pos の偶奇)を使っていない。"""
    js = (WEB / "band.js").read_text(encoding="utf-8")
    overview = js[js.index("function drawOverview") : js.index("function detailRows")]
    assert "pos[" not in overview, "俯瞰が塊内位置を参照している(エイリアシングの原因)"
    assert "--alt-a" not in overview and "--alt-b" not in overview
    assert "rampColor" in overview, "平均発話長のランプを使うこと"


@requires_l4
@pytest.mark.validation
def test_t404_chapter_aggregates_are_exact(band):
    """章の集計が span から再計算した値と一致する。"""
    s = band["spans"]
    for c in band["chapters"]:
        idx = [i for i, st in enumerate(s["start"]) if c["start"] <= st < c["end"]]
        kaiwa = [i for i in idx if s["kind"][i] == KAIWA]
        jino = [i for i in idx if s["kind"][i] == JINOMON]
        # 集計は**可読長**(記法を除く)。位置=原文長との使い分けを検査する
        assert sum(s["plain"][i] for i in kaiwa) == c["kaiwa_chars"]
        assert sum(s["plain"][i] for i in jino) == c["jinomon_chars"]
        assert len(kaiwa) == c["utterances"]
        assert sum(s["lens"][i] for i in idx) == c["chars"], "章の span が章長を覆う"
        assert sum(s["plain"][i] for i in idx) == c["plain_chars"]
        assert c["plain_chars"] < c["chars"], "可読長は原文長より短い(記法があるため)"


# --- T-405 / T-406 詳細の符号化 ----------------------------------------------


@requires_l4
@pytest.mark.validation
def test_t405_alternation_resets_per_run(band):
    """交互は塊の先頭で 0 に戻る(階調が塊をまたいで持ち越されない)。"""
    s = band["spans"]
    seen: dict[int, int] = {}
    for i, k in enumerate(s["kind"]):
        if k != KAIWA:
            continue
        r, p = s["run"][i], s["pos"][i]
        assert p == seen.get(r, 0), f"塊 {r} の pos が連番でない"
        seen[r] = p + 1
    assert all(v >= 1 for v in seen.values())
    assert sum(1 for v in seen.values() if v == 1) > 0, "単発の塊が存在する"


@requires_l4
@pytest.mark.validation
def test_t406_detail_resolution_shows_a_turn(band):
    """4 字/px で 1 発話が 1 px 以上になる。二相(応酬と長広舌)が描き分けられる。"""
    js = (WEB / "band.js").read_text(encoding="utf-8")
    m = re.search(r"CHARS_PER_PX\s*=\s*(\d+)", js)
    assert m, "詳細の解像度が定数で定義されていること"
    cpp = int(m.group(1))
    s = band["spans"]
    lens = sorted(s["plain"][i] for i, k in enumerate(s["kind"]) if k == KAIWA)
    median = lens[len(lens) // 2]
    assert median / cpp >= 1.0, f"中央長 {median} 字が {cpp} 字/px で 1px 未満"
    assert lens[-1] / cpp > 100, "長広舌が一枚岩として描かれる幅を持つこと"


# --- T-401 帯 ⇄ リーダーの位置一致(F-17)------------------------------------


@requires_l4
@pytest.mark.validation
def test_t401_reader_shards_preserve_offsets(band):
    """段落は原文上で重ならず、raw の総和とオフセットが整合する。"""
    from pipeline.reader import check_offsets

    total_plain = 0
    for c in band["chapters"]:
        shard = json.loads(
            (DATA / "text" / f"ch{c['index']:02d}.json").read_text(encoding="utf-8")
        )
        chk = check_offsets(shard)
        assert chk["non_overlapping"], f"第{c['label']}章の段落が重なっている"
        total_plain += chk["plain_chars"]
        for p in shard["paragraphs"]:
            end = p["start"] + sum(it[-1] for it in p["items"])
            assert c["start"] <= p["start"] < end <= c["end"], "段落が章の外へ出ている"
    # 投影の不変量: リーダーの可読文字 + 本文の改行 == セグメントの可読文字
    voices = json.loads((DATA / "voices.json").read_text(encoding="utf-8"))
    readable = voices["counts"]["jinomon"] + voices["counts"]["kaiwa"]
    card_id = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))["card_id"]
    from pipeline.aozora import split_document

    doc = split_document((DATA / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8"))
    newlines = doc.body_raw.count("\r\n")
    assert total_plain + 2 * newlines == readable, (total_plain, newlines, readable)


@requires_l4
@pytest.mark.validation
def test_t401_every_chapter_offset_lands_in_a_paragraph(band):
    """章頭・章末・境界を含む任意のオフセットが、段落か記法のどちらかに解決する。"""
    for c in band["chapters"]:
        shard = json.loads(
            (DATA / "text" / f"ch{c['index']:02d}.json").read_text(encoding="utf-8")
        )
        ranges = [
            (p["start"], p["start"] + sum(it[-1] for it in p["items"]))
            for p in shard["paragraphs"]
        ]
        assert ranges, f"第{c['label']}章に段落が無い"
        assert ranges[0][0] >= c["start"] and ranges[-1][1] <= c["end"]
        # 章の可読部分の大半が段落に覆われていること
        covered = sum(e - s for s, e in ranges)
        assert covered / c["chars"] > 0.9, (c["label"], covered, c["chars"])


# --- 配信要件 ----------------------------------------------------------------


@requires_l4
@pytest.mark.validation
def test_initial_payload_under_budget():
    """初回表示は帯索引のみ。1 MB 未満(N-04)。本文は章シャードで遅延取得。"""
    band_bytes = (WEB / "data" / "band.json").stat().st_size
    css = (WEB / "style.css").stat().st_size
    js = (WEB / "band.js").stat().st_size
    html = (WEB / "index.html").stat().st_size
    total = band_bytes + css + js + html
    assert total < 1_000_000, total
    shards = list((WEB / "data" / "text").glob("ch*.json"))
    assert len(shards) == 11
    assert all(p.stat().st_size < 400_000 for p in shards)


@requires_l4
@pytest.mark.validation
def test_static_only_no_external_calls():
    """外部 API を叩かない(N-01)。fetch はローカルの data/ のみ。"""
    for name in ("band.js", "reader.js"):
        src = (WEB / name).read_text(encoding="utf-8")
        for m in re.finditer(r"fetch\(([^)]*)\)", src):
            assert "http" not in m.group(1), m.group(0)
        assert "http://" not in src and "https://" not in src


@requires_l4
@pytest.mark.validation
def test_theme_tokens_defined_in_all_three_scopes():
    """配色トークンが素の :root / prefers-color-scheme / data-theme の三箇所に揃う。"""
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert css.count("--kaiwa-4") >= 3
    assert "prefers-color-scheme: dark" in css
    assert ':root[data-theme="dark"]' in css
    assert ':root:not([data-theme="light"])' in css


# --- リーダーの着色境界(F-16 / F-15c)---------------------------------------


@requires_l4
@pytest.mark.validation
def test_reader_items_straddle_span_boundaries(band):
    """テキスト項目は発話境界をまたぐ。**項目の先頭だけで会話/地の文を決めてはならない。**

    この件数が 0 なら、境界分割の実装は無意味なので、ケース自体が成立しない。
    """
    s = band["spans"]
    starts, lens = s["start"], s["lens"]

    def span_at(off):
        lo, hi, best = 0, len(starts) - 1, 0
        while lo <= hi:
            m = (lo + hi) // 2
            if starts[m] <= off:
                best, lo = m, m + 1
            else:
                hi = m - 1
        return best if off < starts[best] + lens[best] else -1

    straddling = 0
    for c in band["chapters"]:
        shard = json.loads(
            (DATA / "text" / f"ch{c['index']:02d}.json").read_text(encoding="utf-8")
        )
        for p in shard["paragraphs"]:
            off = p["start"]
            for it in p["items"]:
                raw = it[-1]
                if it[0] == "t" and raw > 1 and span_at(off) != span_at(off + raw - 1):
                    straddling += 1
                off += raw
    assert straddling > 0, "またぐ項目が無いなら境界分割のケースが成立しない"


@requires_l4
@pytest.mark.validation
def test_reader_splits_text_at_span_boundaries():
    """リーダーが span 境界で切りながら描いている(項目の先頭だけで判定していない)。"""
    js = (WEB / "reader.js").read_text(encoding="utf-8")
    fn = js[js.index("function renderText") : js.index("function renderParagraph")]
    assert "spanAt" in fn and "spanEnd" in fn, "span 境界で切っていない"
    assert "while" in fn, "項目内を走査していない"
    assert "項目の先頭だけで会話/地の文を決めてはならない" in js


@requires_l4
@pytest.mark.validation
def test_reader_marks_only_attributed():
    """リーダーの着色は帰属できた発話だけ(話者が無ければ塗らない)。"""
    js = (WEB / "reader.js").read_text(encoding="utf-8")
    fn = js[js.index("function markup") : js.index("/** テキスト項目")]
    assert "if (!speaker) return esc(text)" in fn, "話者が無いときに塗らないこと"
