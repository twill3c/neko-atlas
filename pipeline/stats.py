"""F-10 — 語種・文長・句読点・品詞・文末表現の集計。

**すべて地の文 / 会話文 別に算出する**。全体値は両者の合成として導出し、
合成が直接計算と一致することを検算する(T-212)。
どの辞書による集計かを必ず添える。
"""
from __future__ import annotations

import collections
import statistics
from dataclasses import dataclass

from .morph import Token

SENT_END = "。？！"
PUNCT = "、，"
#: 文末表現として拾う助動詞・語尾の語彙素
BUNMATSU = ("だ", "である", "です", "ます", "た", "ない", "らしい", "だろう", "さ", "ね", "よ", "か")


@dataclass
class Sentence:
    text: str
    tokens: list[Token]


def split_sentences(text: str, tokens: list[Token]) -> list[Sentence]:
    """句点で文に切る。トークン列も同じ境界で分ける(文字数の総和は保存される)。"""
    sentences: list[Sentence] = []
    buf_text: list[str] = []
    buf_tok: list[Token] = []
    for t in tokens:
        buf_tok.append(t)
        buf_text.append(t.surface)
        if t.surface and t.surface[-1] in SENT_END:
            sentences.append(Sentence("".join(buf_text), buf_tok))
            buf_text, buf_tok = [], []
    if buf_tok:
        sentences.append(Sentence("".join(buf_text), buf_tok))
    return sentences


def _ratios(counter: collections.Counter) -> dict:
    total = sum(counter.values())
    if not total:
        return {}
    return {k: round(v / total, 5) for k, v in counter.most_common()}


def summarize(tokens: list[Token], text: str) -> dict:
    """1 つの声(地の文 or 会話文)の集計。件数と比率の両方を残す。"""
    sentences = split_sentences(text, tokens)
    lengths = [len(s.text) for s in sentences if s.text.strip()]

    goshu = collections.Counter(t.goshu for t in tokens if t.goshu)
    pos1 = collections.Counter(t.pos1 for t in tokens if t.pos1)
    bigrams = collections.Counter(
        (a.pos1, b.pos1) for a, b in zip(tokens, tokens[1:]) if a.pos1 and b.pos1
    )

    bunmatsu = collections.Counter()
    for s in sentences:
        content = [t for t in s.tokens if t.pos1 not in ("補助記号", "空白")]
        if content:
            last = content[-1]
            key = last.lemma if last.lemma in BUNMATSU else f"{last.pos1}:{last.lemma}"
            bunmatsu[key] += 1

    chars = len(text)
    return {
        "chars": chars,
        "tokens": len(tokens),
        "sentences": len(lengths),
        "sentence_len": {
            "mean": round(statistics.fmean(lengths), 2) if lengths else 0.0,
            "median": statistics.median(lengths) if lengths else 0,
            "p90": sorted(lengths)[int(len(lengths) * 0.9)] if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "histogram": dict(
                sorted(collections.Counter(min(l // 10 * 10, 200) for l in lengths).items())
            ),
        },
        "punct_per_100_chars": round(
            100 * sum(text.count(p) for p in PUNCT) / chars, 3
        ) if chars else 0.0,
        "goshu_counts": dict(goshu.most_common()),
        "goshu_ratio": _ratios(goshu),
        "pos1_counts": dict(pos1.most_common()),
        "pos1_ratio": _ratios(pos1),
        "pos_bigram_top": [
            {"pair": f"{a}→{b}", "n": n} for (a, b), n in bigrams.most_common(20)
        ],
        "bunmatsu_top": [{"form": k, "n": n} for k, n in bunmatsu.most_common(15)],
    }


def check_composition(overall: dict, parts: list[dict]) -> dict:
    """全体値が地の文 + 会話文 の合成と一致することを検算する(T-212)。"""
    def total(key: str) -> int:
        return sum(p[key] for p in parts)

    goshu_sum: collections.Counter = collections.Counter()
    for p in parts:
        goshu_sum.update(p["goshu_counts"])

    return {
        "chars_match": overall["chars"] == total("chars"),
        "tokens_match": overall["tokens"] == total("tokens"),
        "goshu_match": dict(goshu_sum) == overall["goshu_counts"],
    }
