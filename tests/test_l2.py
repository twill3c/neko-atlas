"""L2 のテスト。TEST_SPEC.md の T-2xx に対応する。

期待値の出所:
- 合成フィクスチャ: 本文中に実在する構造のみ(段落またぎ会話・注記内の鉤括弧・『』の入れ子)
- 実測: data/ を前提とする検査は validation マーカー。辞書を要する検査は辞書の有無で skip
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from pipeline.aozora import split_document
from pipeline.stats import check_composition, split_sentences, summarize
from pipeline.voices import CLASSES, GAIJI, check_direct_sum, classify_chars, split_voices

DATA = Path("data")
NL = "\r\n"

requires_l2 = pytest.mark.skipif(
    not (DATA / "voices.json").exists(), reason="L2 成果物が無い(pipeline.build_l2 未実行)"
)
requires_dict = pytest.mark.skipif(
    not Path(".dict/kindai-bungo/sys.dic").exists(), reason="近代文語 UniDic 未設置"
)


def make_doc(body_lines: list[str]):
    text = NL.join(
        ["題名", "著者", "", "-" * 55, "【テキスト中に現れる記号について】", "", "-" * 55, ""]
        + body_lines
        + ["", "", "", "底本：「テスト」"]
    )
    return split_document(text)


# --- T-201 直和 ---------------------------------------------------------------


@pytest.mark.unit
def test_t201_direct_sum_synthetic():
    """5 区分(地の文/会話文/注記/ルビ/｜)の総和が本文長に一致する。"""
    doc = make_doc(
        [
            "　主人《しゅじん》は「そうさ」と云った。",
            "　一｜疋《ぴき》の※［＃「言＋墟のつくり」、第4水準2-88-74］《いつ》。",
        ]
    )
    r = split_voices(doc)
    c = check_direct_sum(r)
    # フィクスチャの前提を検算する: 5 区分すべてが実際に出現している
    assert all(c["counts"][k] > 0 for k in CLASSES), c["counts"]
    assert c["covers_body"], c
    assert c["sum"] == len(doc.body_raw)
    assert c["segments_cover_content"] and c["segment_label_mismatch"] == 0
    assert c["unclosed_count"] == 0


@pytest.mark.unit
def test_t201_every_char_labelled_exactly_once():
    """ラベル配列が本文と同じ長さで、未分類が無い。"""
    doc = make_doc(["　吾輩《わがはい》は「猫」である。"])
    labels, content = classify_chars(doc)
    assert len(labels) == len(doc.body_raw)
    assert all(labels)
    assert len(content) == sum(1 for label in labels if label == "content")


# --- T-202 鉤括弧の対応 -------------------------------------------------------


@pytest.mark.unit
def test_t202_note_brackets_do_not_open_quotes():
    """注記の中の 「」 が会話を開いてしまわない(L1 の T-111 と対になる検査)。"""
    doc = make_doc(["　なります［＃「なります」」は底本では「なります、」］と云う。"])
    r = split_voices(doc)
    assert r["unclosed"] == []
    assert r["counts"]["kaiwa"] == 0, "注記だけの行に会話文は存在しない"
    # 前提の検算に手書きの定数を置かない(HC-023)。素の計数と、注記を除いた計数を
    # 別経路で導いて突き合わせる — 前者が多いことがこのケースの成立条件
    from pipeline.aozora import NOTE_RE

    naive = doc.body_raw.count("「")
    stripped = NOTE_RE.sub("", doc.body_raw).count("「")
    assert naive > stripped == 0, (naive, stripped)


@pytest.mark.unit
def test_t202_unclosed_is_reported_not_swallowed():
    """閉じない鉤括弧は例外として列挙され、黙って捨てられない。"""
    doc = make_doc(["　彼は「そうさと云った。"])
    r = split_voices(doc)
    assert [u["kind"] for u in r["unclosed"]] == ["open_without_close"]
    assert check_direct_sum(r)["covers_body"], "未対応があっても直和は保たれる"


@pytest.mark.unit
def test_t202_multiline_utterance_spans_paragraphs():
    """会話が段落をまたぐ場合、行単位で閉じさせない(実測 1 例あり)。"""
    doc = make_doc(["　彼は云った。「前半、", "　後半である」と。"])
    r = split_voices(doc)
    assert r["unclosed"] == []
    assert r["multiline_utterances"] == 1
    kaiwa = [s for s in r["segments"] if s.kind == "kaiwa"]
    assert len(kaiwa) == 1 and NL in doc.body_raw[kaiwa[0].start : kaiwa[0].end]


# --- T-203 入れ子と地の文中の引用 ---------------------------------------------


@pytest.mark.unit
def test_t203_inner_quote_kinds_are_distinguished():
    """『』 は 「」 の内側なら nested、地の文なら inline_quote として型で区別する。"""
    doc = make_doc(["　彼は「『猫』を読む」と云った。", "　地の文の『引用』もある。"])
    r = split_voices(doc)
    kinds = collections.Counter(q["kind"] for q in r["inner_quotes"])
    assert kinds == {"nested": 1, "inline_quote": 1}
    assert r["unclosed"] == []


@pytest.mark.unit
def test_t203_gaiji_counts_as_one_char():
    """外字(※ + 注記)は可読テキストで 1 文字に畳む。"""
    doc = make_doc(["　※［＃「言＋墟のつくり」、第4水準2-88-74］である。"])
    r = split_voices(doc)
    text = "".join(s.text for s in r["segments"])
    assert text.count(GAIJI) == 1
    assert "［＃" not in text


@requires_l2
@pytest.mark.validation
def test_t201_measured_direct_sum():
    """実測本文で O-2 が成立する。率や近似ではなく厳密一致を要求する。"""
    v = json.loads((DATA / "voices.json").read_text(encoding="utf-8"))
    c = v["check"]
    assert c["covers_body"], c
    assert c["sum"] == v["body_chars"]
    assert c["segments_cover_content"] and c["segment_label_mismatch"] == 0
    assert c["unclosed_count"] == 0, v["unclosed"]
    assert sum(v["counts"].values()) == v["body_chars"]


@requires_l2
@pytest.mark.validation
def test_t202_measured_quote_balance():
    """発話数が段落まわりの構造と整合する。"""
    v = json.loads((DATA / "voices.json").read_text(encoding="utf-8"))
    assert v["utterances"], "発話が 1 件も無いのは分離の失敗"
    kaiwa_segments = [s for s in v["segments"] if s["kind"] == "kaiwa"]
    assert len(kaiwa_segments) == len(v["utterances"])
    for u in v["utterances"]:
        assert u["end"] > u["start"]


# --- T-211 二辞書照合(O-5) ---------------------------------------------------


@requires_dict
@pytest.mark.integration
def test_t211_goshu_column_detected_not_assumed():
    """語種の列位置は辞書ごとに実測で特定する(素性数が違うため位置を仮定しない)。"""
    from pipeline.morph import load_analyzers

    analyzers = load_analyzers()
    assert len(analyzers) == 2
    for a in analyzers:
        toks = a.tokenize("吾輩は猫である。ビールを飲む。")
        assert any(t.goshu for t in toks), f"{a.spec.name}: 語種が取れていない"
        assert {t.goshu for t in toks} <= {"和", "漢", "外", "混", "固", "記号", "不明", "他", ""}


@requires_dict
@pytest.mark.integration
def test_t211_diff_is_enumerated_not_thresholded():
    """差分は全件返る。件数に閾値を課さない。"""
    from pipeline.morph import diff_segmentation, load_analyzers

    gen, kin = load_analyzers()
    text = "吾輩はここで始めて人間というものを見た。"
    d = diff_segmentation(text, gen.tokenize(text), kin.tokenize(text))
    # 差分があってもなくても、返り値は区間のリストで、各区間に両辞書の結果が入る
    for item in d:
        assert item["gendai"] and item["kindai"]
        assert "".join(x["s"] for x in item["gendai"]) == item["text"]
        assert "".join(x["s"] for x in item["kindai"]) == item["text"]


@requires_l2
@pytest.mark.validation
def test_t211_all_diffs_recorded():
    """差分が jsonl に全件あり、docs 側は件数を偽らない。"""
    path = DATA / "dict_diff.jsonl"
    assert path.exists()
    n = sum(1 for _ in path.open(encoding="utf-8"))
    doc = (Path("docs") / "dict_diff.md").read_text(encoding="utf-8")
    assert f"{n:,} 件" in doc, "要約の件数が jsonl の実件数と一致すること"
    assert "閾値は課さない" in doc


# --- T-212 / T-213 集計 -------------------------------------------------------


@pytest.mark.unit
def test_t212_composition_is_verified_by_arithmetic():
    """全体 = 地の文 + 会話文 の合成が成り立つことを検算する。"""
    from pipeline.morph import Token

    def tok(s, pos, goshu):
        return Token(s, pos, "", s, goshu, "")

    a = [tok("猫", "名詞", "和"), tok("。", "補助記号", "記号")]
    b = [tok("犬", "名詞", "和"), tok("だ", "助動詞", "和"), tok("。", "補助記号", "記号")]
    pa, pb = summarize(a, "猫。"), summarize(b, "犬だ。")
    overall = summarize(a + b, "猫。犬だ。")
    check = check_composition(overall, [pa, pb])
    assert all(check.values()), check


@pytest.mark.unit
def test_t212_sentence_split_preserves_chars():
    """文分割で文字が失われない(トークン列の総和が保存される)。"""
    from pipeline.morph import Token

    toks = [Token(s, "名詞", "", s, "和", "") for s in ["吾輩", "。", "猫", "だ", "。", "尾"]]
    sents = split_sentences("吾輩。猫だ。尾", toks)
    assert "".join(s.text for s in sents) == "吾輩。猫だ。尾"
    assert sum(len(s.tokens) for s in sents) == len(toks)


@requires_l2
@pytest.mark.validation
def test_t213_stats_are_per_voice_and_per_dict():
    """集計が辞書別・声別に揃い、合成検算が通る。どの辞書かが常に明示される。"""
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    assert set(stats) == {"gendai", "kindai"}
    for name, s in stats.items():
        assert s["dict"] and s["license"], "辞書名とライセンスを必ず添える"
        assert set(s["by_voice"]) == {"jinomon", "kaiwa"}
        assert all(s["composition_check"].values()), (name, s["composition_check"])
        for kind, v in s["by_voice"].items():
            assert v["chars"] > 0 and v["tokens"] > 0
            assert v["goshu_ratio"], "語種比率が空"
            assert abs(sum(v["goshu_ratio"].values()) - 1.0) < 1e-3
        assert s["by_chapter"], "章別集計が無い"


@requires_l2
@pytest.mark.validation
def test_t213_goshu_vocabulary_is_controlled():
    """語種の値が統制語彙に収まる。未知の値が黙って混ざらない。"""
    allowed = {"和", "漢", "外", "混", "固", "記号", "不明", "他"}
    stats = json.loads((DATA / "stats.json").read_text(encoding="utf-8"))
    for name, s in stats.items():
        for kind, v in s["by_voice"].items():
            unknown = set(v["goshu_counts"]) - allowed
            assert not unknown, f"{name}/{kind}: 未知の語種 {unknown}"
