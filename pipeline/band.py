"""F-26 — 応酬の帯の索引。

本文を span 列に分解する。**span の長さの総和は本文長と厳密に一致する**
(セグメント間の隙間 = 章見出し等の記法は kind=2 で明示的に埋める)。
分類から導いた投影は分類側に結び直す(HC-024)。

kind: 0 = 地の文 / 1 = 会話文 / 2 = 記法(章見出し等、セグメント外の文字)
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from .attribute import _is_gap

JINOMON, KAIWA, NOTATION = 0, 1, 2


def build_spans(segments, body_chars: int, attributions, boundaries=(), labels=None) -> dict:
    """セグメント列から span 列を作る。

    - セグメント間の隙間は kind=2 で埋める(総和が本文長に一致する)
    - **章境界で span を分割する。** 地の文セグメントは章見出しをまたいで伸びるため
      (実測 2026-08-25: 10 件・いずれも地の文)、分割しないと章別集計と俯瞰の
      座標系がずれる。会話セグメントは境界をまたがないので、塊の pos は連番のまま保たれる
    """
    speaker_of = {a.segment_index: a.speaker for a in attributions}
    cuts = sorted({b for b in boundaries if 0 < b < body_chars})

    # 可読長(記法を除いた文字数)の累積。位置は原文長でなければリーダー連携が壊れるので
    # 原文長のまま持ち、統計と描画の重みにはこちらを使う(L4 で発覚した食い違いの対策)
    if labels is None:
        cum = None
    else:
        cum = [0] * (body_chars + 1)
        for i, lab in enumerate(labels):
            cum[i + 1] = cum[i] + (1 if lab in ("jinomon", "kaiwa") else 0)

    lens: list[int] = []
    plain: list[int] = []
    kind: list[int] = []
    run: list[int] = []
    pos: list[int] = []
    speaker: list[str | None] = []
    start: list[int] = []

    def emit(s: int, e: int, k: int, r: int = 0, p: int = 0, sp=None) -> None:
        if e <= s:
            return
        # 章境界で切る。同じ span が 2 章に跨がると座標系が壊れる
        pieces = [s] + [b for b in cuts if s < b < e] + [e]
        for a, b in zip(pieces, pieces[1:]):
            start.append(a)
            lens.append(b - a)
            plain.append((cum[b] - cum[a]) if cum else (b - a))
            kind.append(k)
            run.append(r)
            pos.append(p)
            speaker.append(sp)

    run_id, pos_in_run, prev_kaiwa = 0, 0, False
    prev_end = 0
    for i, seg in enumerate(segments):
        emit(prev_end, seg.start, NOTATION)
        if seg.kind == "kaiwa":
            if not prev_kaiwa:
                run_id += 1
                pos_in_run = 0
            emit(seg.start, seg.end, KAIWA, run_id, pos_in_run, speaker_of.get(i))
            pos_in_run += 1
            prev_kaiwa = True
        else:
            emit(seg.start, seg.end, JINOMON)
            # 地の文が改行だけなら会話塊は続いている
            prev_kaiwa = prev_kaiwa and _is_gap(seg)
        prev_end = seg.end
    emit(prev_end, body_chars, NOTATION)

    return {
        "start": start,
        "lens": lens,
        "plain": plain,
        "kind": kind,
        "run": run,
        "pos": pos,
        "speaker": speaker,
    }


def check_coverage(spans: dict, body_chars: int) -> dict:
    """投影の不変量: 長さの総和 == 本文長。開始位置が隙間なく連続する。"""
    lens, start = spans["lens"], spans["start"]
    contiguous = all(start[i] + lens[i] == start[i + 1] for i in range(len(start) - 1))
    columns_equal = len({len(spans[k]) for k in
                         ("start", "lens", "plain", "kind", "run", "pos", "speaker")}) == 1
    # 会話塊: run が非 0 なのは会話 span のみ。塊内で pos が 0 から連番
    runs: dict[int, list[int]] = {}
    run_ok = True
    for k, r, p in zip(spans["kind"], spans["run"], spans["pos"]):
        if k == KAIWA:
            runs.setdefault(r, []).append(p)
        elif r != 0 or p != 0:
            run_ok = False
    for r, ps in runs.items():
        if ps != list(range(len(ps))):
            run_ok = False
    boundary_split_ok = True  # 会話 span が分割されていないこと(pos の連番で担保済み)
    return {
        "spans": len(lens),
        "sum_lens": sum(lens),
        "body_chars": body_chars,
        "covers_body": sum(lens) == body_chars,
        "sum_plain": sum(spans["plain"]),
        "starts_at_zero": bool(start) and start[0] == 0,
        "contiguous": contiguous,
        "columns_equal_length": columns_equal,
        "run_positions_ok": run_ok and boundary_split_ok,
        "runs": len(runs),
    }


def chapter_aggregates(chapters, spans: dict) -> list[dict]:
    """章ごとの帯の要約。俯瞰の凡例に出す値はすべてここで実測する。"""
    out = []
    for c in chapters:
        idx = [
            i for i, s in enumerate(spans["start"]) if c.start <= s < c.end
        ]
        kaiwa = [i for i in idx if spans["kind"][i] == KAIWA]
        jino = [i for i in idx if spans["kind"][i] == JINOMON]
        kchars = sum(spans["plain"][i] for i in kaiwa)
        jchars = sum(spans["plain"][i] for i in jino)
        run_sizes: dict[int, int] = {}
        for i in kaiwa:
            run_sizes[spans["run"][i]] = run_sizes.get(spans["run"][i], 0) + 1
        sizes = list(run_sizes.values()) or [0]
        in_run = sum(v for v in sizes if v >= 2)
        lens = sorted(spans["plain"][i] for i in kaiwa) or [0]
        attributed = sum(1 for i in kaiwa if spans["speaker"][i])
        out.append(
            {
                "index": c.index,
                "label": c.label,
                "start": c.start,
                "end": c.end,
                "chars": c.chars,
                "plain_chars": sum(spans["plain"][i] for i in idx),
                "kaiwa_chars": kchars,
                "jinomon_chars": jchars,
                "kaiwa_ratio": round(kchars / max(1, kchars + jchars), 4),
                "utterances": len(kaiwa),
                "runs": len(sizes) if run_sizes else 0,
                "run_len_mean": round(statistics.fmean(sizes), 2),
                "run_len_max": max(sizes),
                "in_run_ratio": round(in_run / max(1, len(kaiwa)), 3),
                "turns_per_1000": round(1000 * len(kaiwa) / c.chars, 2),
                "utterance_len_median": int(statistics.median(lens)),
                "utterance_len_max": max(lens),
                "attributed": attributed,
                "attribution_rate": round(attributed / max(1, len(kaiwa)), 3),
            }
        )
    return out


def save(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
