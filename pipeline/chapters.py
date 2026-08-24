"""F-05 — 章分割。章数・総文字数を定数で書かず、不変量で縛る(HC-016)。

不変量: 前付け + 各章の文字数の総和 == 本文長
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .aozora import Document, Note, Ruby, serialize

MIDASHI = re.compile(r"^「(?P<label>.+)」は(?P<level>大|中|小)見出し$")

_KANJI_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
              "七": 7, "八": 8, "九": 9, "十": 10}


def kanji_number(s: str) -> int | None:
    """「十一」のような漢数字を整数にする(章見出しの検査用。順序の検証に使う)。"""
    if not s or any(ch not in _KANJI_NUM for ch in s):
        return None
    if "十" not in s:
        return _KANJI_NUM.get(s) if len(s) == 1 else None
    head, _, tail = s.partition("十")
    return (_KANJI_NUM[head] if head else 1) * 10 + (_KANJI_NUM[tail] if tail else 0)


@dataclass
class Chapter:
    index: int          # 出現順(1 始まり)
    label: str          # 見出しの文字列(例: 「十一」)
    number: int | None  # 漢数字として解釈できた場合の値
    level: str          # 大 / 中 / 小
    start: int          # body_raw 上の開始文字オフセット
    end: int            # body_raw 上の終了文字オフセット(排他)

    @property
    def chars(self) -> int:
        return self.end - self.start


def find_chapters(doc: Document) -> tuple[list[Chapter], int]:
    """見出し注記から章境界を求める。戻り値は (章一覧, 前付けの文字数)。"""
    body = doc.body_raw
    heads: list[tuple[int, str, str]] = []  # (見出し行の開始オフセット, label, level)

    pos = 0
    for node in doc.nodes:
        rendered = node.render()
        if isinstance(node, Note):
            m = MIDASHI.match(node.inner)
            if m:
                line_start = body.rfind("\r\n", 0, pos)
                line_start = 0 if line_start < 0 else line_start + 2
                heads.append((line_start, m.group("label"), m.group("level")))
        pos += len(rendered)

    chapters: list[Chapter] = []
    for i, (start, label, level) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(body)
        chapters.append(Chapter(i + 1, label, kanji_number(label), level, start, end))

    prologue = heads[0][0] if heads else len(body)
    return chapters, prologue


def check_invariants(doc: Document, chapters: list[Chapter], prologue: int) -> dict:
    """章分割の不変量を検査する(T-121)。件数ではなく被覆で縛る。"""
    body_len = len(doc.body_raw)
    total = prologue + sum(c.chars for c in chapters)
    monotone = all(chapters[i].end == chapters[i + 1].start for i in range(len(chapters) - 1))
    numbers = [c.number for c in chapters]
    return {
        "body_chars": body_len,
        "prologue_chars": prologue,
        "sum_chars": total,
        "covers_body": total == body_len,
        "contiguous": monotone and (not chapters or chapters[-1].end == body_len),
        "numbers_sequential": numbers == list(range(1, len(chapters) + 1)),
        "chapter_count": len(chapters),
    }
