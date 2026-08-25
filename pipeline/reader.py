"""F-16 — リーダー用の章シャード。

段落は body_raw 上の開始オフセットを持ち、**各項目は原文で消費する文字数(raw)を必ず持つ**。
帯からの遷移(F-17)と話者色の位置合わせはこの raw を足していくことで行うので、
表示文字列の長さで代用してはならない(ルビのベースは注記を除いてあり、原文長と一致しない)。

項目:
  ["t", 表示文字列, raw]           地のテキスト
  ["r", ベース, ルビ, raw]         ルビ
  ["n", "", raw]                   入力者注(描画しないが原文を消費する)

外字(※ + 入力者注)は 1 文字 〓 に畳む(voices.GAIJI と同じ扱い)。
**傍点など他の入力者注はこの版では描画しない** — 件数を shard に記録して明示する。
"""
from __future__ import annotations

import json
from pathlib import Path

from .aozora import Note, Ruby
from .voices import GAIJI, _note_spans_in

NL = "\r\n"


def _strip_notes(raw: str) -> str:
    """ルビのベースから入力者注を除き、※ を 〓 に畳む。"""
    spans = _note_spans_in(raw)
    out = []
    for i, ch in enumerate(raw):
        if any(s <= i < e for s, e in spans):
            continue
        out.append(GAIJI if ch == "※" else ch)
    return "".join(out)


def build_chapter(doc, start: int, end: int) -> dict:
    """[start, end) の範囲を段落列にする。段落内の raw の総和で原文位置が復元できる。"""
    paragraphs: list[dict] = []
    items: list[list] = []
    para_start: int | None = None
    notes_dropped = 0

    def has_content() -> bool:
        return any(
            (it[0] == "t" and it[1].strip().strip("　")) or it[0] == "r" for it in items
        )

    def flush() -> None:
        nonlocal items, para_start
        if items and has_content():
            paragraphs.append({"start": para_start, "items": items})
        items, para_start = [], None

    def open_at(offset: int) -> None:
        nonlocal para_start
        if para_start is None:
            para_start = offset

    pos = 0
    for node in doc.nodes:
        rendered = node.render()
        n = len(rendered)
        node_start, node_end = pos, pos + n
        pos = node_end
        if node_end <= start or node_start >= end:
            continue

        if isinstance(node, Note):
            notes_dropped += 1
            open_at(node_start)
            items.append(["n", "", n])
            continue
        if isinstance(node, Ruby):
            open_at(node_start)
            items.append(["r", _strip_notes(node.base_raw), node.reading, n])
            continue

        off = node_start
        for k, chunk in enumerate(rendered.split(NL)):
            if k > 0:
                flush()
                off += len(NL)
            if chunk:
                open_at(off)
                shown = chunk.replace("※", GAIJI)
                if items and items[-1][0] == "t":
                    items[-1][1] += shown
                    items[-1][2] += len(chunk)
                else:
                    items.append(["t", shown, len(chunk)])
            off += len(chunk)
    flush()
    return {"paragraphs": paragraphs, "notes_not_rendered": notes_dropped}


def plain_length(chapter: dict) -> int:
    """段落の可読文字数(ルビの読み・注記は含まない)。"""
    total = 0
    for p in chapter["paragraphs"]:
        for it in p["items"]:
            if it[0] in ("t", "r"):
                total += len(it[1])
    return total


def raw_length(chapter: dict) -> int:
    """段落が原文で消費する文字数の総和(改行を除く)。"""
    return sum(it[-1] for p in chapter["paragraphs"] for it in p["items"])


def check_offsets(chapter: dict) -> dict:
    """投影の不変量(HC-024): 段落は原文上で重ならず、raw の総和と一致する。"""
    ok = True
    prev_end = -1
    for p in chapter["paragraphs"]:
        end = p["start"] + sum(it[-1] for it in p["items"])
        if p["start"] < prev_end:
            ok = False
        prev_end = end
    return {
        "paragraphs": len(chapter["paragraphs"]),
        "non_overlapping": ok,
        "plain_chars": plain_length(chapter),
        "raw_chars": raw_length(chapter),
    }


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
