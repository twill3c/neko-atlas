"""L1 のテスト。TEST_SPEC.md の T-1xx に対応する。

期待値の出所:
- 合成フィクスチャ: 本文中に実在する記法のみを使う(出所は docs/notation_inventory.md)
- 実測: data/raw を前提とする検査は validation マーカーを付け、未取得環境では skip する
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.aozora import Accent, Note, Ruby, Text, parse_body, serialize, split_document
from pipeline.chapters import check_invariants, find_chapters, kanji_number
from pipeline.fetch_aozora import classify, fold_title, parse_author_list, parse_shoshutsu

DATA = Path("data")
RAW = DATA / "raw"
NL = "\r\n"


def _raw_card_id():
    p = DATA / "chapters.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["card_id"]


requires_raw = pytest.mark.skipif(
    not (DATA / "aozora_cards.json").exists(),
    reason="data/raw 未取得(取得は pipeline.fetch_aozora)",
)


# --- T-101 カードの確定 -------------------------------------------------------

AUTHOR_LIST_FIXTURE = (
    '<a name="sakuhin_list_1">公開中の作品</a></h2>\n<ol>\n'
    '<li><a href="../cards/000148/card789.html">吾輩は猫である</a>　（新字新仮名、作品ID：789）　</li>\n'
    '<li><a href="../cards/000148/card790.html">吾輩ハ猫デアル</a>　（旧字旧仮名、作品ID：790）　</li>\n'
    '<li><a href="../cards/000148/card2671.html">『吾輩は猫である』中篇自序</a>　（新字新仮名、作品ID：2671）　</li>\n'
    '<li><a href="../cards/000148/card4683.html">猫の広告文</a>　（新字旧仮名、作品ID：4683）　</li>\n'
    "</ol>\n"
    '<a name="sakuhin_list_2">作業中の作品</a>'
)


@pytest.mark.unit
def test_t101_author_list_parsed_as_set():
    """作家ページの li が全件パースされ、題名・文字づかい・作品 ID が揃う。"""
    works = parse_author_list(AUTHOR_LIST_FIXTURE)
    # フィクスチャの前提を検算する: 4 件すべてが異なるカード ID を持つ
    assert len({w["card_id"] for w in works}) == len(works) == 4
    assert {w["title"] for w in works} == {
        "吾輩は猫である",
        "吾輩ハ猫デアル",
        "『吾輩は猫である』中篇自序",
        "猫の広告文",
    }
    assert all(w["kanazukai"] and w["work_id"] for w in works)


@pytest.mark.unit
def test_t101_classification_is_title_based_not_id_based():
    """本文の同定は題名の畳み込みで行う。カード ID を直書きしない(HC-016)。"""
    assert fold_title("吾輩ハ猫デアル") == fold_title("吾輩は猫である")
    assert classify("吾輩は猫である")[0] == "honbun"
    assert classify("吾輩ハ猫デアル")[0] == "honbun"
    assert classify("『吾輩は猫である』上篇自序")[0] == "paratext"
    assert classify("猫の広告文")[0] == "other"
    for t in ("吾輩は猫である", "『吾輩は猫である』上篇自序", "猫の広告文"):
        assert classify(t)[1], "すべての分類に理由を残すこと"


@pytest.mark.unit
def test_t101_no_hardcoded_card_id_in_source():
    """パイプラインのソースに本文カード ID を定数で埋め込まない。"""
    src = Path("pipeline/fetch_aozora.py").read_text(encoding="utf-8")
    body = src.split("if __name__", 1)[0]
    # 実測値をコメントに残すのは AGENTS.md が認める書き方。コードとして持っていないことを見る
    code = "".join(l.split("#", 1)[0] for l in body.splitlines())
    assert "789" not in code and "790" not in code


@requires_raw
@pytest.mark.validation
def test_t101_inventory_covers_author_list():
    """在庫が作家ページの公開中作品と集合として一致する。件数は定数で書かない。"""
    cards = json.loads((DATA / "aozora_cards.json").read_text(encoding="utf-8"))
    inv = cards["inventory"]
    assert len(inv) == cards["author_list"]["count"]
    assert len({w["card_id"] for w in inv}) == len(inv)
    assert all(w["role"] in {"honbun", "paratext", "other"} and w["reason"] for w in inv)
    assert any(w["role"] == "honbun" for w in inv)


# --- T-102 / T-103 provenance とキャッシュ ------------------------------------


@requires_raw
@pytest.mark.validation
def test_t102_provenance_complete():
    cards = json.loads((DATA / "aozora_cards.json").read_text(encoding="utf-8"))
    assert {"url", "fetched_at", "sha256"} <= cards["author_list"]["provenance"].keys()
    for w in cards["inventory"]:
        if w["role"] != "honbun":
            continue
        assert {"url", "fetched_at", "sha256"} <= w["card_provenance"].keys()
        t = w["text"]
        if t.get("source") == "zip":
            assert t["text_kind"] in {"ruby", "noruby"}
            assert {"url", "fetched_at", "sha256"} <= t["provenance"].keys()
            assert Path(t["path"]).exists()
        else:
            assert t.get("note"), "zip が無いカードは理由を残すこと"


@requires_raw
@pytest.mark.validation
def test_t103_rerun_issues_no_http():
    """再実行でキャッシュが効き、HTTP が 1 本も出ない(N-02)。"""
    import pipeline.http as http
    from pipeline import fetch_aozora

    before = http.http_requests
    fetch_aozora.main()
    assert http.http_requests == before


# --- T-111 記法パース ---------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "src, kinds",
    [
        ("吾輩《わがはい》は猫である。", [Ruby, Text]),
        ("一番｜獰悪《どうあく》な", [Text, Ruby, Text]),
        ("［＃８字下げ］一［＃「一」は中見出し］", [Note, Text, Note]),
        ("〔Quid aliud est〕", [Accent]),
        ("※［＃「言＋墟のつくり」、第4水準2-88-74］《いつ》", [Ruby]),
    ],
)
def test_t111_node_kinds(src, kinds):
    nodes = parse_body(src)
    assert [type(n) for n in nodes] == kinds
    assert serialize(nodes) == src


@pytest.mark.unit
def test_t111_ruby_base_rules():
    """ベース決定: 同一字種を遡る / ｜ があればそれに従う / 外字注記を取り込む。"""
    (r,) = [n for n in parse_body("見当《けんとう》") if isinstance(n, Ruby)]
    assert (r.base_raw, r.reading, r.bar) == ("見当", "けんとう", False)

    (r,) = [n for n in parse_body("この書生の掌の裏《うち》") if isinstance(n, Ruby)]
    assert r.base_raw == "裏", "字種が変わる位置でベースが止まること"

    (r,) = [n for n in parse_body("一｜疋《ぴき》") if isinstance(n, Ruby)]
    assert (r.base_raw, r.bar) == ("疋", True)

    (r,) = [
        n
        for n in parse_body("御※［＃「飮のへん＋善」、第4水準2-92-68］《ごぜん》")
        if isinstance(n, Ruby)
    ]
    assert "［＃" in r.base_raw and r.reading == "ごぜん"


@pytest.mark.unit
def test_t111_note_containing_brackets_is_one_node():
    """注記の中の 「」 を本文の会話と取り違えない(T-202 の前提)。"""
    src = "「なります［＃「なります」」は底本では「なります、」］"
    nodes = parse_body(src)
    notes = [n for n in nodes if isinstance(n, Note)]
    assert len(notes) == 1
    assert serialize(nodes) == src
    assert src.count("「") == 3, "素の計数では 3 個に見える(この前提が壊れたらケースが無意味)"
    plain = "".join(n.s for n in nodes if isinstance(n, Text))
    assert plain.count("「") == 1


# --- T-112 往復検査(O-1) -----------------------------------------------------


@pytest.mark.unit
def test_t112_roundtrip_synthetic():
    doc_text = NL.join(
        [
            "題名",
            "著者",
            "",
            "-" * 55,
            "【テキスト中に現れる記号について】",
            "",
            "《》：ルビ",
            "-" * 55,
            "",
            "［＃８字下げ］一［＃「一」は中見出し］",
            "",
            "　吾輩《わがはい》は猫である。一｜疋《ぴき》の※［＃「言＋墟のつくり」、第4水準2-88-74］《いつ》。",
            "",
            "",
            "",
            "底本：「テスト」",
            "入力：テスト",
        ]
    )
    doc = split_document(doc_text)
    assert doc.title == "題名" and doc.author == "著者"
    assert doc.render() == doc_text
    assert doc.header_raw + doc.body_raw + doc.footer_raw == doc_text


@requires_raw
@pytest.mark.validation
def test_t112_roundtrip_measured():
    """実測本文の往復一致率 100%。1 文字でも差があれば fail(品質基準)。"""
    cid = _raw_card_id()
    assert cid, "data/chapters.json が無い(pipeline.build_l1 未実行)"
    original = (RAW / f"{cid}.txt").read_bytes().decode("utf-8")
    doc = split_document(original)
    assert doc.render() == original
    # 退化していないこと: 本文が 1 ノードに潰れていない
    assert sum(1 for n in doc.nodes if isinstance(n, Ruby)) == doc.body_raw.count("《")
    assert sum(1 for n in doc.nodes if isinstance(n, Ruby) and n.bar) == doc.body_raw.count("｜")


# --- T-121 章分割 -------------------------------------------------------------


@pytest.mark.unit
def test_t121_kanji_number():
    assert [kanji_number(s) for s in ("一", "九", "十", "十一")] == [1, 9, 10, 11]
    assert kanji_number("甲") is None


@requires_raw
@pytest.mark.validation
def test_t121_chapter_invariants():
    """章別文字数の総和 == 本文長。章数は定数で書かず不変量で縛る。"""
    cid = _raw_card_id()
    doc = split_document((RAW / f"{cid}.txt").read_bytes().decode("utf-8"))
    chapters, prologue = find_chapters(doc)
    inv = check_invariants(doc, chapters, prologue)
    assert inv["covers_body"], inv
    assert inv["contiguous"], inv
    assert inv["numbers_sequential"], inv
    assert inv["chapter_count"] >= 1
    stored = json.loads((DATA / "chapters.json").read_text(encoding="utf-8"))
    assert stored["invariants"] == inv, "成果物と再計算が一致すること"


# --- T-122 連載回 -------------------------------------------------------------


@pytest.mark.unit
def test_t122_parse_shoshutsu_carries_year():
    issues = parse_shoshutsu("「ホトトギス」1905（明治38）年1月、2月、1906（明治39）年8月")
    assert [(i["year"], i["month"]) for i in issues] == [(1905, 1), (1905, 2), (1906, 8)]
    assert {i["media"] for i in issues} == {"ホトトギス"}


@requires_raw
@pytest.mark.validation
def test_t122_two_sources_reconciled():
    """初出は 2 出所から取り、食い違いは潰さず記録する。"""
    serial = json.loads((DATA / "serial.json").read_text(encoding="utf-8"))
    assert serial["card_issues"] and serial["footer_issues"]
    assert serial["agree"], serial
    if not serial["one_to_one"]:
        assert serial["chapter_to_issue"] is None
        assert "needs_review" in serial["chapter_to_issue_status"]


# --- 記法インベントリ ---------------------------------------------------------


@requires_raw
@pytest.mark.validation
def test_inventory_is_generated_not_handwritten():
    p = Path("docs/notation_inventory.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "このファイルは実測の出力であり、手で書かない" in text
    assert f"data/raw/{_raw_card_id()}.txt" in text
