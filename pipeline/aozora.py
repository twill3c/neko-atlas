"""F-03 / F-04 — 青空文庫記法のパーサーと再直列化(往復検査 O-1)。

分岐の根拠は docs/notation_inventory.md の全件実測に置く。記憶で場合分けしない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEPARATOR = re.compile(r"^-{10,}$")
TEIHON = re.compile(r"^底本：")

# --- ノード ------------------------------------------------------------------


@dataclass
class Text:
    s: str

    def render(self) -> str:
        return self.s


@dataclass
class Note:
    """［＃…］ 入力者注(外字の説明・傍点指定・字下げ・見出し指定など)。"""

    inner: str

    def render(self) -> str:
        return f"［＃{self.inner}］"


@dataclass
class Accent:
    """〔…〕 アクセント分解された欧文。"""

    inner: str

    def render(self) -> str:
        return f"〔{self.inner}〕"


@dataclass
class Ruby:
    """《…》 ルビ。base_raw は原文の該当スライスをそのまま持つ(往復検査のため)。"""

    base_raw: str
    reading: str
    bar: bool  # ｜ による明示的なベース指定があったか

    def render(self) -> str:
        return ("｜" if self.bar else "") + self.base_raw + f"《{self.reading}》"


Node = Text | Note | Accent | Ruby


# --- ルビのベース決定 ---------------------------------------------------------

_KANJI = re.compile(r"[一-鿿々〆ヶ㐀-䶿豈-﫿]")
_KATA = re.compile(r"[ァ-ヺーヽヾ]")
_HIRA = re.compile(r"[ぁ-ゟ]")
_LATIN = re.compile(r"[0-9A-Za-zＡ-Ｚａ-ｚ０-９]")


def _char_class(ch: str) -> str | None:
    for name, pat in (("kanji", _KANJI), ("kata", _KATA), ("hira", _HIRA), ("latin", _LATIN)):
        if pat.match(ch):
            return name
    return None


def _auto_base_start(body: str, end: int, note_spans: list[tuple[int, int]]) -> int:
    """《 の直前 end からベース先頭位置を後方走査で決める。

    実測(2026-08-25)に基づく規則:
    - 直前が ］ のとき、その入力者注(外字注記)をベースに取り込む(本文中 17 件)
    - 以後は同一字種(漢字/片仮名/平仮名/英数)が続く限り遡る
    """
    note_start_by_end = {e: s for s, e in note_spans}
    i = end
    cls = None
    while i > 0:
        if i in note_start_by_end:  # 直前が ］ で終わる注記
            if cls not in (None, "kanji"):
                break
            i = note_start_by_end[i]
            # 外字は ※ と注記の対で 1 文字を成す。※ を切り離してはならない
            if i > 0 and body[i - 1] == "※":
                i -= 1
            cls = "kanji"
            continue
        ch = body[i - 1]
        c = _char_class(ch)
        if c is None:
            break
        if cls is None:
            cls = c
        elif c != cls:
            break
        i -= 1
    return i


# --- パース ------------------------------------------------------------------


def _spans(pattern: re.Pattern, body: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(body)]


NOTE_RE = re.compile(r"［＃[^］]*］")
ACCENT_RE = re.compile(r"〔[^〕]*〕")
RUBY_RE = re.compile(r"《[^》]*》")


def parse_body(body: str) -> list[Node]:
    """本文文字列をノード列にする。ノード列は本文を隙間なく分割する(直和)。"""
    note_spans = _spans(NOTE_RE, body)
    accent_spans = _spans(ACCENT_RE, body)

    # ルビ span(ベース先頭 → 》 の直後)を先に確定する
    ruby_spans: list[tuple[int, int, str, str, bool]] = []
    for m in RUBY_RE.finditer(body):
        reading = body[m.start() + 1 : m.end() - 1]
        bar_pos = body.rfind("｜", 0, m.start())
        # ｜ とこの 《 の間に別の 《》 が挟まっていなければ、その ｜ のベース指定とみなす
        if bar_pos >= 0 and "《" not in body[bar_pos:m.start()] and "\r\n" not in body[bar_pos:m.start()]:
            start = bar_pos
            base_raw = body[bar_pos + 1 : m.start()]
            bar = True
        else:
            start = _auto_base_start(body, m.start(), note_spans)
            base_raw = body[start : m.start()]
            bar = False
        ruby_spans.append((start, m.end(), base_raw, reading, bar))

    covered = {s: (e, kind) for (s, e), kind in
               [(sp, "note") for sp in note_spans] + [(sp, "accent") for sp in accent_spans]}
    ruby_by_start = {s: (e, base, read, bar) for s, e, base, read, bar in ruby_spans}
    ruby_ranges = [(s, e) for s, e, *_ in ruby_spans]

    def inside_ruby(pos: int) -> bool:
        return any(s <= pos < e for s, e in ruby_ranges)

    nodes: list[Node] = []
    buf: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        if i in ruby_by_start:
            e, base, read, bar = ruby_by_start[i]
            if buf:
                nodes.append(Text("".join(buf)))
                buf = []
            nodes.append(Ruby(base, read, bar))
            i = e
            continue
        if i in covered and not inside_ruby(i):
            e, kind = covered[i]
            if buf:
                nodes.append(Text("".join(buf)))
                buf = []
            inner = body[i + 2 : e - 1] if kind == "note" else body[i + 1 : e - 1]
            nodes.append(Note(inner) if kind == "note" else Accent(inner))
            i = e
            continue
        buf.append(body[i])
        i += 1
    if buf:
        nodes.append(Text("".join(buf)))
    return nodes


def serialize(nodes: list[Node]) -> str:
    return "".join(node.render() for node in nodes)


# --- 文書の分割 --------------------------------------------------------------


@dataclass
class Document:
    header_raw: str
    body_raw: str
    footer_raw: str
    title: str
    author: str
    nodes: list[Node] = field(default_factory=list)

    def render(self) -> str:
        """往復検査(O-1): 原文と完全一致すること。"""
        return self.header_raw + serialize(self.nodes) + self.footer_raw


def split_document(text: str, newline: str = "\r\n") -> Document:
    lines = text.split(newline)

    seps = [i for i, l in enumerate(lines) if SEPARATOR.match(l)]
    if len(seps) >= 2:
        head_end = seps[1] + 1
    else:
        head_end = 2  # 記号説明ブロックが無い版(題名・著者のみ)
    while head_end < len(lines) and lines[head_end] == "":
        head_end += 1

    foot_candidates = [i for i, l in enumerate(lines) if TEIHON.match(l)]
    if not foot_candidates:
        raise ValueError("底本行が見つからない(DATA-SRC)")
    foot_start = foot_candidates[-1]
    while foot_start > 0 and lines[foot_start - 1] == "":
        foot_start -= 1

    header_raw = newline.join(lines[:head_end]) + newline
    body_raw = newline.join(lines[head_end:foot_start]) + newline
    footer_raw = newline.join(lines[foot_start:])

    title = lines[0]
    # 著者は題名ブロックの最終行(副題を持つ作品があるため)
    author = lines[head_end - 1] if head_end >= 2 else lines[1]
    for i in range(1, min(head_end, len(lines))):
        if lines[i] == "":
            author = lines[i - 1]
            break

    doc = Document(header_raw, body_raw, footer_raw, title, author)
    doc.nodes = parse_body(body_raw)
    return doc
