"""F-01 / F-02 / F-06 — 青空文庫からの取得と作品カードの確定。

規律:
- カード ID を定数で書かない。作家ページの「公開中の作品」との照合で確定する(HC-016)
- 全版を列挙し、採用/不採用の理由を evidence に残す
- 取得はキャッシュ優先・間隔 1 秒以上(N-02)、provenance 必須(N-03)
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

from .http import fetch

AUTHOR_ID = "000148"  # 夏目漱石。person ページの実測で確定した作家 ID
AUTHOR_LIST_URL = f"https://www.aozora.gr.jp/index_pages/person{int(AUTHOR_ID)}.html"
CARD_BASE = f"https://www.aozora.gr.jp/cards/{AUTHOR_ID}/"

#: 本文として採る作品の題名(表記ゆれは fold_title で吸収する)
TARGET_TITLE = "吾輩は猫である"

DATA = Path("data")

_KATA = {chr(c): chr(c - 0x60) for c in range(0x30A1, 0x30F7)}


def fold_title(title: str) -> str:
    """題名の表記ゆれを畳む。カタカナ→ひらがな、記号除去。

    「吾輩ハ猫デアル」(旧字旧仮名) と「吾輩は猫である」(新字新仮名) を
    同一題名として照合するために使う。カード ID の直書きを避けるための鍵。
    """
    s = "".join(_KATA.get(ch, ch) for ch in title)
    return re.sub(r"[\s　]+", "", s)


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def parse_author_list(html: str) -> list[dict]:
    """作家ページの「公開中の作品」節を全件パースする。"""
    start = html.find('<a name="sakuhin_list_1">')
    end = html.find('<a name="sakuhin_list_2">')
    if start < 0:
        raise ValueError("公開中の作品の節が見つからない(ページ構造の変化 — DATA-SRC)")
    section = html[start : end if end > start else len(html)]

    works: list[dict] = []
    for li in re.findall(r"<li>(.*?)</li>", section, re.S):
        m = re.search(r'href="\.\./cards/(\d+)/card(\d+)\.html"[^>]*>(.*?)</a>', li, re.S)
        if not m:
            continue
        author_id, card_id, title_html = m.groups()
        meta = re.search(r"（([^、]+)、作品ID：(\d+)）", _strip_tags(li))
        works.append(
            {
                "card_id": card_id,
                "author_dir": author_id,
                "title": _strip_tags(title_html).strip(),
                "kanazukai": meta.group(1) if meta else None,
                "work_id": meta.group(2) if meta else None,
                "card_url": f"https://www.aozora.gr.jp/cards/{author_id}/card{card_id}.html",
            }
        )
    return works


def classify(title: str) -> tuple[str, str]:
    """作品を 本文 / 付属テキスト / 対象外 に分類し、理由を返す。"""
    folded = fold_title(title)
    target = fold_title(TARGET_TITLE)
    if folded == target:
        return "honbun", "題名が対象作品と一致(カタカナ→ひらがなの畳み込み後)"
    if target in folded:
        return "paratext", "対象作品の題名を含むが本文ではない(自序等の付属テキスト)"
    return "other", "対象作品ではない"


_FILE_ROW = re.compile(
    r"<tr>(?:(?!</tr>).)*?href=\"(\./files/[^\"]+)\"(?:(?!</tr>).)*?</tr>", re.S
)


def parse_card_page(html: str) -> dict:
    """カードページから初出・底本・配布ファイルを取り出す。"""
    flat = re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "\t", html))

    def field(label: str) -> str | None:
        m = re.search(re.escape(label) + r"：\t*([^\t\n]+)", flat)
        return m.group(1).strip() if m else None

    files = []
    for m in re.finditer(r'href="\./files/([^"]+)"', html):
        name = m.group(1)
        if name in [f["name"] for f in files]:
            continue
        if name.endswith(".zip"):
            kind = "text_ruby" if "_ruby_" in name else "text_noruby"
        elif name.endswith((".html", ".xhtml")):
            kind = "html"
        else:
            kind = "other"
        files.append({"name": name, "kind": kind, "url": CARD_BASE + "files/" + name})

    return {
        "shoshutsu": field("初出"),
        "teihon": field("底本"),
        "ndc": field("分類"),
        "files": files,
    }


def parse_shoshutsu(text: str) -> list[dict]:
    """初出欄「「ホトトギス」1905（明治38）年1月、2月、…」を回ごとに分解する(F-06)。

    西暦は直前に現れたものを引き継ぐ。件数を定数で書かず、文字列の実測から作る。
    """
    if not text:
        return []
    media = None
    m = re.match(r"「([^」]+)」", text)
    if m:
        media = m.group(1)
    issues: list[dict] = []
    year = None
    era = None
    for tok in re.finditer(r"(?:(\d{4})（([^）]+)）年)?\s*(\d{1,2})月", text):
        y, e, month = tok.groups()
        if y:
            year, era = int(y), e
        if year is None:
            continue
        issues.append({"media": media, "year": year, "era": era, "month": int(month)})
    return issues


def zip_text(body: bytes) -> tuple[str, str]:
    """青空文庫の配布 zip から本文テキストを取り出す。戻り値は (テキスト, 内部ファイル名)。"""
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if len(names) != 1:
            raise ValueError(f"zip 内の .txt が 1 件ではない: {names}")
        raw = zf.read(names[0])
    for enc in ("shift_jis", "cp932"):
        try:
            return raw.decode(enc), names[0]
        except UnicodeDecodeError:
            continue
    raise ValueError("Shift_JIS として復号できない(DATA-QUAL)")


def main() -> dict:
    DATA.mkdir(exist_ok=True)
    (DATA / "raw").mkdir(exist_ok=True)

    body, prov = fetch(AUTHOR_LIST_URL)
    works = parse_author_list(body.decode("utf-8"))

    inventory = []
    for w in works:
        role, reason = classify(w["title"])
        inventory.append({**w, "role": role, "reason": reason})

    honbun = [w for w in inventory if w["role"] == "honbun"]
    if not honbun:
        raise ValueError("本文カードが 1 件も見つからない(DATA-SRC)")

    for w in honbun:
        cbody, cprov = fetch(w["card_url"])
        card = parse_card_page(cbody.decode("utf-8"))
        w["card"] = card
        w["card_provenance"] = cprov
        w["issues"] = parse_shoshutsu(card["shoshutsu"] or "")

        zips = [f for f in card["files"] if f["kind"].startswith("text_")]
        zips.sort(key=lambda f: 0 if f["kind"] == "text_ruby" else 1)
        if zips:
            f = zips[0]
            zbody, zprov = fetch(f["url"])
            text, inner = zip_text(zbody)
            out = DATA / "raw" / f"{w['card_id']}.txt"
            out.write_bytes(text.encode("utf-8"))
            w["text"] = {
                "path": str(out).replace("\\", "/"),
                "text_kind": "ruby" if f["kind"] == "text_ruby" else "noruby",
                "source": "zip",
                "inner_name": inner,
                "chars": len(text),
                "provenance": zprov,
            }
        else:
            # 配布 zip が無いカード。HTML のみで配られている(実測 2026-08-25: card790)
            html = [f for f in card["files"] if f["kind"] == "html"]
            w["text"] = {
                "source": "html_only",
                "note": "テキスト配布 zip が無く HTML のみ。記法テキストではないため往復検査(O-1)の対象外",
                "files": html,
            }

    result = {
        "author_list": {"url": AUTHOR_LIST_URL, "provenance": prov, "count": len(works)},
        "target_title": TARGET_TITLE,
        "inventory": inventory,
    }
    (DATA / "aozora_cards.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    r = main()
    inv = r["inventory"]
    print(f"公開中の作品: {len(inv)} 件")
    for role in ("honbun", "paratext"):
        for w in inv:
            if w["role"] != role:
                continue
            t = w.get("text", {})
            print(f"  [{role}] card{w['card_id']} {w['title']} ({w['kanazukai']}) "
                  f"src={t.get('source')} chars={t.get('chars')} issues={len(w.get('issues', []))}")
