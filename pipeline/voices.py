"""F-07 / F-08 — 二声分離(地の文 / 会話文)と直和検査(O-2)。

本文の**全文字**をちょうど 1 つの区分に割り当てる:
  jinomon(地の文) / kaiwa(会話文) / note(入力者注) / ruby(ルビ読み) / bar(｜)
この 5 区分の文字数の総和が本文長に一致することを不変量とする。率や近似で通さない。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .aozora import Document, Note, Ruby

#: 外字(※ + 入力者注)は 1 文字として扱う。青空文庫の慣行に合わせた代替文字
GAIJI = "〓"

CLASSES = ("jinomon", "kaiwa", "note", "ruby", "bar")


@dataclass
class Segment:
    kind: str  # jinomon / kaiwa
    start: int  # body_raw 上の開始オフセット
    end: int  # body_raw 上の終了オフセット(排他)
    text: str  # 記法を除いた可読テキスト(外字は 〓)

    @property
    def chars(self) -> int:
        return len(self.text)


def _note_spans_in(s: str) -> list[tuple[int, int]]:
    spans = []
    i = 0
    while True:
        j = s.find("［＃", i)
        if j < 0:
            break
        k = s.find("］", j)
        if k < 0:
            break
        spans.append((j, k + 1))
        i = k + 1
    return spans


def classify_chars(doc: Document) -> tuple[list[str], list[int]]:
    """本文の各文字に区分ラベルを付ける。戻り値は (ラベル配列, 内容文字のオフセット列)。

    内容文字 = 地の文か会話文になりうる文字(注記・ルビ読み・｜ を除いたもの)。
    """
    body = doc.body_raw
    labels: list[str] = [""] * len(body)
    content: list[int] = []

    pos = 0
    for node in doc.nodes:
        rendered = node.render()
        n = len(rendered)
        if isinstance(node, Note):
            for k in range(pos, pos + n):
                labels[k] = "note"
        elif isinstance(node, Ruby):
            off = pos
            if node.bar:
                labels[off] = "bar"
                off += 1
            base_end = off + len(node.base_raw)
            inner_notes = _note_spans_in(node.base_raw)
            for k in range(off, base_end):
                rel = k - off
                if any(s <= rel < e for s, e in inner_notes):
                    labels[k] = "note"
                else:
                    labels[k] = "content"
                    content.append(k)
            for k in range(base_end, pos + n):
                labels[k] = "ruby"
        else:  # Text / Accent
            for k in range(pos, pos + n):
                labels[k] = "content"
                content.append(k)
        pos += n

    assert pos == len(body), "ノード列が本文を覆っていない"
    assert all(labels), "区分の付いていない文字がある"
    return labels, content


def _readable(doc: Document, start: int, end: int, labels: list[str]) -> str:
    """区間の可読テキスト。

    **記法の文字(注記・ルビ読み・｜)は 1 文字も残さない。** 内容文字だけを取り、
    外字(※ + 注記)は 1 文字 〓 に畳む。ここでルビ読みを残すと、下流の形態素解析が
    ルビ込みの文字列を食う(L3 で発覚。可読テキスト長 == 内容ラベル数 が守り)。
    """
    body = doc.body_raw
    out: list[str] = []
    for i in range(start, end):
        if labels[i] in ("note", "ruby", "bar"):
            continue
        ch = body[i]
        out.append(GAIJI if ch == "※" else ch)
    return "".join(out)


def split_voices(doc: Document) -> dict:
    """地の文と会話文に分ける。鉤括弧の対応・入れ子・段落またぎを記録する。"""
    body = doc.body_raw
    labels, content = classify_chars(doc)

    segments: list[Segment] = []
    quotes: list[dict] = []
    inner_quotes: list[dict] = []
    unclosed: list[dict] = []

    depth = 0
    open_stack: list[int] = []
    inner_stack: list[int] = []
    seg_start = content[0] if content else 0
    seg_kind = "jinomon"

    def flush(end_exclusive: int) -> None:
        if end_exclusive <= seg_start:
            return
        segments.append(
            Segment(seg_kind, seg_start, end_exclusive, _readable(doc, seg_start, end_exclusive, labels))
        )

    prev = None
    for off in content:
        ch = body[off]
        if ch == "「":
            if depth == 0:
                flush(off)
                seg_kind = "kaiwa"
                seg_start = off
            depth += 1
            open_stack.append(off)
        elif ch == "」":
            if depth == 0:
                unclosed.append({"offset": off, "kind": "close_without_open"})
            else:
                depth -= 1
                start = open_stack.pop()
                if depth == 0:
                    quotes.append({"start": start, "end": off + 1})
                    flush(off + 1)
                    seg_kind = "jinomon"
                    seg_start = off + 1
        elif ch == "『":
            inner_stack.append(off)
        elif ch == "』":
            if inner_stack:
                start = inner_stack.pop()
                inner_quotes.append(
                    {
                        "start": start,
                        "end": off + 1,
                        "kind": "nested" if depth > 0 else "inline_quote",
                    }
                )
            else:
                unclosed.append({"offset": off, "kind": "inner_close_without_open"})
        prev = off

    if prev is not None:
        flush(prev + 1)
    for off in open_stack:
        unclosed.append({"offset": off, "kind": "open_without_close"})
    for off in inner_stack:
        unclosed.append({"offset": off, "kind": "inner_open_without_close"})

    for seg in segments:
        if seg.kind != "kaiwa":
            continue
        for k in range(seg.start, seg.end):
            if labels[k] == "content":
                labels[k] = "kaiwa"
    for k, label in enumerate(labels):
        if label == "content":
            labels[k] = "jinomon"

    counts = {c: labels.count(c) for c in CLASSES}
    multiline = sum(
        1 for s in segments if s.kind == "kaiwa" and "\r\n" in body[s.start : s.end]
    )

    return {
        "labels": labels,
        "segments": segments,
        "quotes": quotes,
        "inner_quotes": inner_quotes,
        "unclosed": unclosed,
        "counts": counts,
        "body_chars": len(body),
        "multiline_utterances": multiline,
    }


def check_direct_sum(result: dict) -> dict:
    """O-2: 5 区分の総和が本文長に一致し、被覆に漏れ・重複が無いこと。

    セグメントの被覆は body 全体ではなく**内容文字**に対して見る。本文は章見出しの
    注記(内容文字ではない)から始まるので、body の 0 番地を要求するのは誤り。
    """
    counts = result["counts"]
    labels = result["labels"]
    segs = result["segments"]
    contiguous = all(segs[i].end == segs[i + 1].start for i in range(len(segs) - 1))

    # 内容文字がちょうど 1 つのセグメントに属し、区分ラベルとセグメント種別が一致すること
    seen = 0
    mismatched = 0
    for seg in segs:
        for k in range(seg.start, seg.end):
            if labels[k] in ("jinomon", "kaiwa"):
                seen += 1
                if labels[k] != seg.kind:
                    mismatched += 1
    content_chars = counts["jinomon"] + counts["kaiwa"]
    # 下流に渡す可読テキストの総長が内容文字数と一致すること。
    # ラベルの直和が成立していても、_readable が記法を残していればここで落ちる
    readable_chars = sum(s.chars for s in segs)

    return {
        "readable_chars": readable_chars,
        "readable_matches_labels": readable_chars == content_chars,
        "counts": counts,
        "sum": sum(counts.values()),
        "body_chars": result["body_chars"],
        "covers_body": sum(counts.values()) == result["body_chars"],
        "segments_contiguous": contiguous,
        "segments_cover_content": seen == content_chars,
        "segment_label_mismatch": mismatched,
        "unclosed_count": len(result["unclosed"]),
        "kaiwa_ratio": round(counts["kaiwa"] / max(1, content_chars), 4),
    }


def save(result: dict, path: Path) -> None:
    payload = {
        "body_chars": result["body_chars"],
        "counts": result["counts"],
        "check": check_direct_sum(result),
        "multiline_utterances": result["multiline_utterances"],
        "unclosed": result["unclosed"],
        "inner_quotes": result["inner_quotes"],
        "utterances": result["quotes"],
        "segments": [
            {"kind": s.kind, "start": s.start, "end": s.end, "chars": s.chars}
            for s in result["segments"]
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
