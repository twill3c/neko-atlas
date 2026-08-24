"""L1 の成果物を生成する。data/chapters.json / data/serial.json / docs/notation_inventory.md"""
from __future__ import annotations

import collections
import io
import json
import re
from pathlib import Path

from .aozora import Accent, Note, Ruby, Text, split_document
from .chapters import check_invariants, find_chapters
from .serial import footer_issues, reconcile

DATA = Path("data")
DOCS = Path("docs")


def load_doc(card_id: str):
    raw = (DATA / "raw" / f"{card_id}.txt").read_bytes().decode("utf-8")
    return split_document(raw)


def build(card_id: str = None) -> dict:
    cards = json.loads((DATA / "aozora_cards.json").read_text(encoding="utf-8"))
    honbun = [w for w in cards["inventory"]
              if w["role"] == "honbun" and w.get("text", {}).get("source") == "zip"]
    if card_id:
        honbun = [w for w in honbun if w["card_id"] == card_id]
    if len(honbun) != 1:
        raise ValueError(f"往復検査の対象となる本文カードが 1 件ではない: {[w['card_id'] for w in honbun]}")
    work = honbun[0]
    doc = load_doc(work["card_id"])

    roundtrip_ok = doc.render() == (DATA / "raw" / f"{work['card_id']}.txt").read_bytes().decode("utf-8")
    chapters, prologue = find_chapters(doc)
    inv = check_invariants(doc, chapters, prologue)

    (DATA / "chapters.json").write_text(json.dumps({
        "card_id": work["card_id"],
        "title": doc.title,
        "author": doc.author,
        "invariants": inv,
        "chapters": [
            {"index": c.index, "label": c.label, "number": c.number, "level": c.level,
             "start": c.start, "end": c.end, "chars": c.chars}
            for c in chapters
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    rec = reconcile(work["issues"], footer_issues(doc.footer_raw))
    rec["chapter_count"] = inv["chapter_count"]
    rec["one_to_one"] = rec["count"] == inv["chapter_count"]
    rec["chapter_to_issue"] = None
    rec["chapter_to_issue_status"] = (
        "needs_review — 連載 %d 回に対し章は %d。どの回が 2 章分を含むかを決められる出所を "
        "本ループでは持たない。推定で埋めない(F-13 と同じ規律)" % (rec["count"], inv["chapter_count"])
        if not rec["one_to_one"] else "1:1"
    )
    (DATA / "serial.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    write_inventory(doc, chapters)
    return {"roundtrip_ok": roundtrip_ok, "invariants": inv, "serial": rec, "doc": doc}


def write_inventory(doc, chapters) -> None:
    body = doc.body_raw
    rubies = [n for n in doc.nodes if isinstance(n, Ruby)]
    notes = [n for n in doc.nodes if isinstance(n, Note)]

    note_kinds = collections.Counter()
    for n in notes:
        s = n.inner
        if "見出し" in s:
            note_kinds["見出し指定"] += 1
        elif "傍点" in s:
            note_kinds["傍点"] += 1
        elif "字下げ" in s or "字上げ" in s:
            note_kinds["字下げ・字上げ"] += 1
        elif re.search(r"水準|U\+|Unicode", s):
            note_kinds["外字注記"] += 1
        elif "底本では" in s or "ママ" in s:
            note_kinds["校異・ママ注記"] += 1
        else:
            note_kinds["その他"] += 1

    base_kinds = collections.Counter()
    for r in rubies:
        b = r.base_raw
        if "［＃" in b:
            base_kinds["外字注記を含む"] += 1
        elif re.fullmatch(r"[一-鿿々〆ヶ]+", b):
            base_kinds["漢字のみ"] += 1
        elif re.fullmatch(r"[ァ-ヺーヽヾ]+", b):
            base_kinds["片仮名のみ"] += 1
        elif re.fullmatch(r"[ぁ-ゟ]+", b):
            base_kinds["平仮名のみ"] += 1
        else:
            base_kinds["その他(要確認)"] += 1

    odoriji = collections.Counter(ch for ch in body if ch in "々ゝゞヽヾ〳〴〵")
    stripped = re.sub(r"《[^》]*》", "", re.sub(r"［＃[^］]*］", "", body)).replace("｜", "")

    lines = [
        "# notation_inventory — 青空文庫記法の全件実測",
        "",
        f"対象: `data/raw/{json.loads((DATA / 'chapters.json').read_text(encoding='utf-8'))['card_id']}.txt`"
        f"(『{doc.title}』{doc.author})",
        "",
        "**このファイルは実測の出力であり、手で書かない。**パーサー(`pipeline/aozora.py`)の",
        "場合分けはここに現れた記法のみを根拠とする。パーサーを触ったら再生成して差分を見ること。",
        "",
        "## 文書の構成",
        "",
        "| 区画 | 文字数 |",
        "|---|---|",
        f"| ヘッダ(題名・著者・記号説明) | {len(doc.header_raw):,} |",
        f"| 本文 | {len(doc.body_raw):,} |",
        f"| フッタ(底本情報) | {len(doc.footer_raw):,} |",
        f"| **合計(= 原文)** | **{len(doc.header_raw) + len(doc.body_raw) + len(doc.footer_raw):,}** |",
        "",
        "## ノード種別(本文)",
        "",
        "| 種別 | 件数 |",
        "|---|---|",
        f"| ルビ `《》` | {len(rubies):,} |",
        f"| うち `｜` によるベース明示 | {sum(1 for r in rubies if r.bar):,} |",
        f"| 入力者注 `［＃…］`(ルビのベースに取り込まれたものを除く) | {len(notes):,} |",
        f"| アクセント分解欧文 `〔…〕` | {sum(1 for n in doc.nodes if isinstance(n, Accent)):,} |",
        f"| 地のテキスト断片 | {sum(1 for n in doc.nodes if isinstance(n, Text)):,} |",
        "",
        "## 入力者注の内訳",
        "",
        "| 種別 | 件数 |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v:,} |" for k, v in note_kinds.most_common()]
    lines += [
        "",
        "## ルビのベース字種",
        "",
        "ベース決定は「直前が `］` なら外字注記を取り込み、以後は同一字種を遡る」規則による。",
        "",
        "| ベースの字種 | 件数 |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v:,} |" for k, v in base_kinds.most_common()]
    lines += [
        "",
        "## 踊り字",
        "",
        "| 文字 | 件数 |",
        "|---|---|",
    ]
    lines += [f"| `{k}` | {v:,} |" for k, v in odoriji.most_common()] or ["| (なし) | 0 |"]
    lines += [
        "",
        "## 括弧の対応(L2 の二声分離 O-2 の前提)",
        "",
        "注記・ルビを除去した本文で数える。**注記の中に `「」` が現れるため、除去前に数えてはならない**",
        f"(除去前: 「 {body.count('「'):,} / 」 {body.count('」'):,} ← 釣り合わない)。",
        "",
        "| 括弧 | 開 | 閉 |",
        "|---|---|---|",
        f"| `「」` | {stripped.count('「'):,} | {stripped.count('」'):,} |",
        f"| `『』` | {stripped.count('『'):,} | {stripped.count('』'):,} |",
        f"| `（）` | {stripped.count('（'):,} | {stripped.count('）'):,} |",
        "",
        "## 章見出し",
        "",
        "| # | 見出し | 水準 | 文字数 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c.index} | 「{c.label}」 | {c.level} | {c.chars:,} |" for c in chapters]
    lines.append("")
    DOCS.mkdir(exist_ok=True)
    (DOCS / "notation_inventory.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    r = build()
    print("往復検査(O-1):", "一致" if r["roundtrip_ok"] else "不一致")
    print("章分割の不変量:", json.dumps(r["invariants"], ensure_ascii=False))
    print("連載回:", r["serial"]["count"], "／ 章:", r["serial"]["chapter_count"],
          "／ 2 出所一致:", r["serial"]["agree"])
    print("章↔回:", r["serial"]["chapter_to_issue_status"])
