"""F-14 — gold 標本の抽出。

規律: gold は**評価専用**。規則の導出・調整の入力に使わない(T-305)。
抽出は seed 固定の一様無作為(章横断)。文脈は規則の出力を含めずに出す —
ラベル付けの際に規則の答えを見ないため。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260825
SAMPLE_SIZE = 300
BEFORE = 420   # 前文脈の文字数
AFTER = 160    # 後文脈の文字数


def sample_indices(total: int, size: int = SAMPLE_SIZE, seed: int = SEED) -> list[int]:
    rng = random.Random(seed)
    return sorted(rng.sample(range(total), min(size, total)))


def context(flat: str, flat_start: int, flat_end: int) -> dict:
    return {
        "before": flat[max(0, flat_start - BEFORE) : flat_start],
        "utterance": flat[flat_start:flat_end],
        "after": flat[flat_end : flat_end + AFTER],
    }


def build_sheet(segments, chapters, flat_offsets: dict[int, int], flat: str) -> list[dict]:
    """ラベル付け用のシートを作る。speaker 欄は空(人手で埋める)。"""
    utterances = [(i, s) for i, s in enumerate(segments) if s.kind == "kaiwa"]
    picked = sample_indices(len(utterances))
    rows = []
    for u in picked:
        i, seg = utterances[u]
        fs = flat_offsets[seg.start]
        ctx = context(flat, fs, fs + seg.chars)
        ch = next((c.index for c in chapters if c.start <= seg.start < c.end), 0)
        rows.append(
            {
                "utterance_index": u + 1,
                "segment_index": i,
                "chapter": ch,
                "body_start": seg.start,
                "context": ctx,
            }
        )
    return rows


def save_sheet(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps({"seed": SEED, "size": len(rows), "rows": rows},
                               ensure_ascii=False, indent=1), encoding="utf-8")


def evaluate(gold: dict, attributions: list) -> dict:
    """gold に対する規則の適合率・再現率・帰属率を測る。

    - 適合率 = 帰属したもののうち正しかった割合
    - 再現率 = gold で話者が決まるもののうち、正しく帰属できた割合
    - 帰属率 = 規則が何らかの話者を出した割合
    - gold 側が「不明」のものは分母から外し、その件数を別に報告する
    """
    by_index = {a.utterance_index: a for a in attributions}
    labelled = {int(k): v for k, v in gold["labels"].items()}

    # 判定不能の 2 種を分母から外す:
    #   unknown    — 本文から話者を決められない
    #   not_speech — 鉤括弧だが発話ではない(商品名・語句の引用など)
    UNDECIDABLE = (None, "", "unknown", "not_speech")
    decidable = {k: v for k, v in labelled.items() if v not in UNDECIDABLE}
    undecidable = len(labelled) - len(decidable)
    # 統制語彙の外の話者(other:...)は判定可能だが、規則が当てられる余地は無い。
    # 再現率の分母には含めたうえで、内訳を別に報告する
    out_of_vocab = sum(1 for v in decidable.values() if str(v).startswith("other:"))

    tp = fp = fn = 0
    errors = []
    for idx, truth in decidable.items():
        a = by_index.get(idx)
        pred = a.speaker if a else None
        if pred is None:
            fn += 1
        elif pred == truth:
            tp += 1
        else:
            fp += 1
            errors.append({"utterance": idx, "gold": truth, "pred": pred,
                           "rule": a.rule_id, "evidence": a.evidence})
    # gold が不明なのに規則が帰属したもの(過剰帰属)は別枠で数える
    over = sum(
        1 for k, v in labelled.items()
        if v in UNDECIDABLE and by_index.get(k) and by_index[k].speaker
    )
    predicted = tp + fp
    return {
        "gold_size": len(labelled),
        "decidable": len(decidable),
        "undecidable": undecidable,
        "out_of_vocabulary": out_of_vocab,
        "predicted": predicted,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": round(tp / predicted, 4) if predicted else None,
        "recall": round(tp / len(decidable), 4) if decidable else None,
        "attribution_rate_on_gold": round(
            sum(1 for k in labelled if by_index.get(k) and by_index[k].speaker) / len(labelled), 4
        ) if labelled else None,
        "over_attributed_on_unknown": over,
        "errors": errors,
    }
