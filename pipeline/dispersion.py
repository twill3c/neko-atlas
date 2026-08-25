"""F-20 — 語彙分散。

筋を持たない作品なので感情価曲線は効かない。代わりに「どの語がどこに固まって出るか」が
そのまま構成図になる。**主題語は手で選ばない** — 分布の偏りで選ぶ。

偏りの指標は Juilland の D:
    D = 1 - (章別相対頻度の標準偏差 / 平均) / sqrt(章数 - 1)
D が 1 に近いほど均等、0 に近いほど一箇所に固まる。**小さいものが挿話の目印**になる。

位置の規律(L5 で 2 つ踏んだ):
- **形態素の表層長を足し上げて位置を出さない。** MeCab は空白・改行をトークンとして
  返さないので、後方ほど累積的にずれる(実測 2,376 字)。本文へ前方探索で整列させる
- **シャードの `chapter` を章の帰属に使わない。** 地の文セグメントは章見出しをまたぐので、
  またいだ分がすべて手前の章に付く。章は**トークンの本文オフセット**から決める
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path

MIN_FREQ = 30          # これ未満は偏りの推定が不安定
TOP_CONCENTRATED = 24  # 分散プロットに載せる語数
KEEP_POS1 = ("名詞", "動詞", "形容詞")
MAX_SKIP = 64          # 整列の前方探索で許す飛び幅


def juilland_d(per_chapter: list[float]) -> float:
    """章別の相対頻度から D を出す。均等なら 1、一章に集中すると 0 に近づく。"""
    n = len(per_chapter)
    if n < 2:
        return 1.0
    mean = sum(per_chapter) / n
    if mean == 0:
        return 0.0
    var = sum((x - mean) ** 2 for x in per_chapter) / n
    cv = math.sqrt(var) / mean
    return max(0.0, 1.0 - cv / math.sqrt(n - 1))


def plain_map(data_dir: Path) -> tuple[str, list[int]]:
    """可読テキストと、その 1 文字ごとの body_raw 上のオフセット。"""
    from .aozora import split_document
    from .voices import GAIJI, classify_chars

    card_id = json.loads((data_dir / "chapters.json").read_text(encoding="utf-8"))["card_id"]
    doc = split_document((data_dir / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8"))
    labels, _ = classify_chars(doc)
    text, offs = [], []
    for i, lab in enumerate(labels):
        if lab in ("note", "ruby", "bar"):
            continue
        ch = doc.body_raw[i]
        text.append(GAIJI if ch == "※" else ch)
        offs.append(i)
    return "".join(text), offs


def token_stream(data_dir: Path, dict_name: str = "gendai") -> dict:
    """形態素を本文の文字位置に整列させた 1 本の列を作る。

    戻り値の `tokens` は (lemma, pos1, body_offset) の並び。
    整列が本文を最後まで消費したことを `consumed_ratio` で検算できる(HC-024)。
    """
    text, offs = plain_map(data_dir)
    out: list[tuple[str, str, int]] = []
    cursor = 0
    unmatched = 0
    total = 0
    for path in sorted((data_dir / "morph" / dict_name).glob("ch*.json")):
        d = json.loads(path.read_text(encoding="utf-8"))
        cols = {c: i for i, c in enumerate(d["cols"])}
        for row in d["rows"]:
            surface = row[cols["s"]]
            total += 1
            if not surface:
                continue
            found = text.find(surface, cursor)
            if found < 0 or found - cursor > MAX_SKIP:
                unmatched += 1
                continue
            out.append((row[cols["lemma"]] or surface, row[cols["pos1"]], offs[found]))
            cursor = found + len(surface)
    return {
        "tokens": out,
        "plain_chars": len(text),
        "cursor_end": cursor,
        "consumed_ratio": round(cursor / max(1, len(text)), 5),
        "total_rows": total,
        "unmatched": unmatched,
    }


def chapter_index(chapters: list[dict]):
    bounds = [(c["start"], c["end"], c["index"]) for c in chapters]

    def of(off: int) -> int:
        for s, e, i in bounds:
            if s <= off < e:
                return i
        return bounds[-1][2]

    return of


def collect(stream: dict, chapters: list[dict]) -> dict:
    """章別の語頻度と章の総語数。章は**本文オフセット**から決める。"""
    of = chapter_index(chapters)
    freq: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    totals: collections.Counter = collections.Counter()
    for lemma, pos1, off in stream["tokens"]:
        if pos1 not in KEEP_POS1:
            continue
        ch = of(off)
        freq[lemma][ch] += 1
        totals[ch] += 1
    return {"freq": freq, "totals": dict(totals)}


def rank_concentrated(collected: dict, chapters: list[dict], min_freq: int = MIN_FREQ,
                      top: int = TOP_CONCENTRATED) -> list[dict]:
    """D の小さい順(= 固まって出る順)に語を並べる。"""
    freq, totals = collected["freq"], collected["totals"]
    indices = [c["index"] for c in chapters]
    out = []
    for lemma, counts in freq.items():
        total = sum(counts.values())
        if total < min_freq:
            continue
        rel = [counts.get(i, 0) / max(1, totals.get(i, 1)) for i in indices]
        peak = max(indices, key=lambda i: (counts.get(i, 0), -i))
        out.append(
            {
                "lemma": lemma,
                "total": total,
                "d": round(juilland_d(rel), 4),
                "peak_chapter": peak,
                "peak_share": round(counts.get(peak, 0) / total, 3),
                "by_chapter": {str(i): counts.get(i, 0) for i in indices},
            }
        )
    out.sort(key=lambda r: (r["d"], -r["total"], r["lemma"]))
    return out[:top]


def occurrences(stream: dict, lemmas: set[str]) -> dict[str, list[int]]:
    """語ごとの出現位置(本文オフセット)。collect と同じ列から取るので必ず整合する。"""
    hits: dict[str, list[int]] = {l: [] for l in lemmas}
    for lemma, _pos1, off in stream["tokens"]:
        if lemma in hits:
            hits[lemma].append(off)
    return hits
