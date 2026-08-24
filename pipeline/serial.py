"""F-06 — 連載回メタデータ。2 出所(カードページの初出欄・本文フッタの初出行)から取る。"""
from __future__ import annotations

import re

from .fetch_aozora import parse_shoshutsu


def footer_issues(footer_raw: str) -> list[dict]:
    """フッタの「初出：」ブロックを回ごとに分解する(第 2 の出所)。"""
    lines = footer_raw.split("\r\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.startswith("初出："))
    except StopIteration:
        return []
    block = [lines[i][len("初出："):]]
    for l in lines[i + 1:]:
        if not l.startswith("　") or re.match(r"^\s*$", l):
            break
        block.append(l.strip("　 "))
    return parse_shoshutsu("".join(block))


def reconcile(card: list[dict], footer: list[dict]) -> dict:
    """2 出所を突き合わせる。食い違いは潰さず、そのまま記録する。"""
    key = lambda xs: [(x["year"], x["month"]) for x in xs]
    return {
        "card_issues": card,
        "footer_issues": footer,
        "agree": key(card) == key(footer),
        "card_only": [x for x in key(card) if x not in key(footer)],
        "footer_only": [x for x in key(footer) if x not in key(card)],
        "count": len(card),
    }
